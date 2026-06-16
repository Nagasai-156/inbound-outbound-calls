"""OpenAI LLM factory — voice-grade, streaming.

Voice systems need speed, not essay-level reasoning, so the default is a
small fast model (never o3 / 4.1-full). Model + temperature come from the
dashboard-editable RuntimeConfig. Tokens stream into the sentence chunker
so TTS starts mid-generation; the stream is abortable on barge-in.

PROCESS-WIDE HTTP CLIENT (Round 3 — connection-pool keepalive):
  India → US-East OpenAI RTT is ~200-300ms; without keepalive the first
  request of each call paid a fresh TLS handshake (~100-180ms) on top.
  A single process-wide `httpx.AsyncClient` reused across every call in
  this worker process holds a warm pool of HTTP/2 connections — after
  the first call lights up the pool, every subsequent call's LLM TTFT
  skips the TLS handshake entirely. `keepalive_expiry=300s` covers
  inter-call idle gaps; `max_keepalive_connections=10` covers up to ~10
  concurrent streaming calls without forcing new connections.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time

import httpx
import openai as _openai_sdk
from livekit.plugins import openai

from src.config import settings
from src.runtime_config import RuntimeConfig

logger = logging.getLogger("llm")

# Lazily-created process-wide AsyncOpenAI client. Shared across every
# call this worker process handles, so HTTP/2 connections + TLS sessions
# survive between calls (within keepalive_expiry).
_shared_async_client: _openai_sdk.AsyncOpenAI | None = None
# Same pattern for Sarvam — their LLM API is OpenAI-compatible
# (https://api.sarvam.ai/v1), so we can use the same livekit openai.LLM
# wrapper just by swapping the underlying client's base_url + key.
_sarvam_async_client: _openai_sdk.AsyncOpenAI | None = None
_SARVAM_BASE_URL = "https://api.sarvam.ai/v1"
# Mistral La Plateforme — selected via `mistral/<model>`, e.g.
# `mistral/mistral-small-latest`.
_mistral_async_client: _openai_sdk.AsyncOpenAI | None = None
_MISTRAL_BASE_URL = "https://api.mistral.ai/v1"
# Google Gemini — OpenAI-compatible endpoint, selected via
# `gemini/<model>`, e.g. `gemini/gemini-2.5-flash-lite`. Best Telugu
# script quality in testing. AI Studio endpoint (US) for now; Vertex
# Mumbai (asia-south1) is the production path for low latency.
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
# xAI Grok — OpenAI-compatible, selected via `xai/<model>`, e.g.
# `xai/grok-4.20-0309-non-reasoning`. US-hosted.
_XAI_BASE_URL = "https://api.x.ai/v1"
# Groq — OpenAI-compatible, Llama on LPU chips. Selected via
# `groq/<model>`, e.g. `groq/llama-3.3-70b-versatile`. US-hosted but
# LPU-fast (TTFT ~291ms from India in probe).
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _build_shared_client() -> _openai_sdk.AsyncOpenAI | None:
    """Return the process-wide AsyncOpenAI with pooled keepalive httpx
    transport. Returns None if no API key is configured (let livekit's
    plugin build its own default — keeps non-OpenAI deploys working)."""
    global _shared_async_client
    if _shared_async_client is not None:
        return _shared_async_client
    if not settings.openai_api_key:
        return None
    # Long keepalive + HTTP/2 mux. The pool is sized for the
    # worker_num_idle_processes-bounded concurrency of a single process.
    limits = httpx.Limits(
        max_keepalive_connections=10,
        max_connections=20,
        keepalive_expiry=300.0,
    )
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    http_client = httpx.AsyncClient(
        http2=True, limits=limits, timeout=timeout,
    )
    _shared_async_client = _openai_sdk.AsyncOpenAI(
        api_key=settings.openai_api_key,
        http_client=http_client,
        max_retries=0,  # the livekit openai.LLM wrapper retries; don't double up
    )
    return _shared_async_client


def _build_mistral_client() -> _openai_sdk.AsyncOpenAI | None:
    """Process-wide Mistral client using its OpenAI-compatible API."""
    global _mistral_async_client
    if _mistral_async_client is not None:
        return _mistral_async_client
    key = getattr(settings, "mistral_api_key", "") or os.environ.get(
        "MISTRAL_API_KEY", ""
    )
    if not key:
        return None
    limits = httpx.Limits(
        max_keepalive_connections=10,
        max_connections=20,
        keepalive_expiry=300.0,
    )
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    http_client = httpx.AsyncClient(http2=True, limits=limits, timeout=timeout)
    _mistral_async_client = _openai_sdk.AsyncOpenAI(
        api_key=key,
        base_url=_MISTRAL_BASE_URL,
        http_client=http_client,
        max_retries=0,
    )
    return _mistral_async_client


# Amazon Bedrock — India-hosted (Mumbai) via its OpenAI-COMPATIBLE Chat
# Completions endpoint. Selected via `bedrock/<modelId>`, e.g.
# `bedrock/mistral.ministral-3-14b-instruct`. Auth = a Bedrock API key
# (bearer token, AWS_BEARER_TOKEN_BEDROCK). The model runs in ap-south-1
# so TTFT skips the US (OpenAI) / EU (Mistral) RTT — measured ~500-700ms
# vs ~1200ms for US OpenAI, with NO free-tier 429s (AWS managed). Verified:
# streaming + the exact tool_choice={"type":"function",...} forcing format
# the agent's deterministic booking uses both work through this endpoint.
_bedrock_async_client: _openai_sdk.AsyncOpenAI | None = None
_BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-south-1")
_BEDROCK_BASE_URL = (
    f"https://bedrock-runtime.{_BEDROCK_REGION}.amazonaws.com/openai/v1"
)


def _build_bedrock_client() -> _openai_sdk.AsyncOpenAI | None:
    """Process-wide Bedrock (Mumbai) client via its OpenAI-compatible API.
    Same pooled-keepalive pattern as the others; India→India RTT so the
    pool mostly just removes per-request TLS at crore-scale concurrency."""
    global _bedrock_async_client
    if _bedrock_async_client is not None:
        return _bedrock_async_client
    key = (getattr(settings, "aws_bearer_token_bedrock", "") or "").strip() \
        or os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
    if not key:
        return None
    limits = httpx.Limits(
        max_keepalive_connections=10, max_connections=20, keepalive_expiry=300.0,
    )
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    http_client = httpx.AsyncClient(http2=True, limits=limits, timeout=timeout)
    _bedrock_async_client = _openai_sdk.AsyncOpenAI(
        api_key=key, base_url=_BEDROCK_BASE_URL,
        http_client=http_client, max_retries=0,
    )
    return _bedrock_async_client


def _build_sarvam_client() -> _openai_sdk.AsyncOpenAI | None:
    """Process-wide Sarvam-LLM client. Same pooled-keepalive pattern as
    OpenAI but points at api.sarvam.ai. Used when the dashboard model
    name starts with `sarvam-` (e.g. `sarvam-m`). India→India RTT so
    keepalive payoff is smaller than OpenAI's, but the pool still removes
    per-request TLS for crore-scale concurrency."""
    global _sarvam_async_client
    if _sarvam_async_client is not None:
        return _sarvam_async_client
    if not settings.sarvam_api_key:
        return None
    limits = httpx.Limits(
        max_keepalive_connections=10,
        max_connections=20,
        keepalive_expiry=300.0,
    )
    timeout = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    http_client = httpx.AsyncClient(
        http2=True, limits=limits, timeout=timeout,
    )
    _sarvam_async_client = _openai_sdk.AsyncOpenAI(
        api_key=settings.sarvam_api_key,
        base_url=_SARVAM_BASE_URL,
        http_client=http_client,
        max_retries=0,
    )
    return _sarvam_async_client


_pool_warm = False


def warm_openai_pool() -> None:
    """Fire-and-forget warmup of the process-wide OpenAI HTTP/2 pool.

    Called from `agent.prewarm()` so the worker subprocess pays the TLS
    handshake + HTTP/2 SETTINGS exchange (~100-180ms India→US-East) BEFORE
    the first call lands, not during the caller's first turn. Subsequent
    calls in this subprocess re-use the warm pool for free.

    Safe to call multiple times — idempotent guard. Failures are silent
    (a warmup failure must NEVER block worker boot; the real call will
    just pay the handshake the first time, which was the prior behavior).
    """
    global _pool_warm
    if _pool_warm:
        return
    if not settings.openai_api_key:
        return
    _pool_warm = True

    def _run() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_warm_async())
        except Exception:
            logger.debug("openai pool warmup failed (non-fatal)", exc_info=True)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    # Background thread so prewarm() returns immediately. The pool warmup
    # races against the first call's LLM request — worst case the call's
    # request triggers its own handshake (the pre-fix behavior), so no
    # regression even if warmup hasn't completed in time.
    threading.Thread(target=_run, name="openai-pool-warm", daemon=True).start()


async def _warm_async() -> None:
    """Internal: light up the shared HTTP/2 pool by exercising BOTH the
    chat and embeddings endpoints concurrently (they share this client),
    so the first call's LLM TTFT *and* the first semantic-cache lookup
    skip the TLS handshake. gpt-4o-mini + 1 token = cheap; 5s timeout so
    a slow region never wedges boot."""
    t0 = time.monotonic()
    client = _build_shared_client()
    if client is None:
        return

    async def _warm_chat() -> None:
        try:
            await asyncio.wait_for(
                client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "."}],
                    max_tokens=1,
                    temperature=0,
                ),
                timeout=5.0,
            )
        except Exception:
            logger.debug("chat warmup request failed", exc_info=True)

    async def _warm_embed() -> None:
        try:
            await asyncio.wait_for(
                client.embeddings.create(
                    model=settings.embedding_model, input="."
                ),
                timeout=5.0,
            )
        except Exception:
            logger.debug("embed warmup request failed", exc_info=True)

    await asyncio.gather(_warm_chat(), _warm_embed(), return_exceptions=True)
    logger.info(
        "openai pool warmed (chat+embed) elapsed_ms=%.0f",
        (time.monotonic() - t0) * 1000,
    )


_bedrock_pool_warm = False


def warm_bedrock_pool() -> None:
    """Fire-and-forget warmup of the process-wide Bedrock (Mumbai) HTTP/2
    pool — mirrors `warm_openai_pool`. The first Bedrock call of a worker
    subprocess otherwise pays the TLS handshake + HTTP/2 SETTINGS exchange
    (~180-490ms cold, India→Mumbai) on the caller's FIRST turn; warming it
    in prewarm() moves that cost off the critical path so even the first
    (cold) call is fast. Idempotent; failures are silent (a warmup failure
    must never block worker boot — the real call just pays the handshake
    once, the pre-fix behavior)."""
    global _bedrock_pool_warm
    if _bedrock_pool_warm:
        return
    if _build_bedrock_client() is None:
        return  # no Bedrock key → nothing to warm
    _bedrock_pool_warm = True

    def _run() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_warm_bedrock_async())
        except Exception:
            logger.debug("bedrock pool warmup failed (non-fatal)", exc_info=True)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    threading.Thread(
        target=_run, name="bedrock-pool-warm", daemon=True
    ).start()


async def _warm_bedrock_async() -> None:
    """Light up the shared Bedrock HTTP/2 pool with a 1-token request so the
    first real call's LLM TTFT skips the TLS handshake. Model is env-
    overridable; any Bedrock model on the endpoint warms the shared pool
    (the TLS/HTTP2 cost is per-endpoint, not per-model). 6s timeout so a
    slow region never wedges boot."""
    t0 = time.monotonic()
    client = _build_bedrock_client()
    if client is None:
        return
    model = os.environ.get(
        "BEDROCK_WARM_MODEL", "mistral.ministral-3-14b-instruct"
    )
    try:
        await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "."}],
                max_tokens=1,
                temperature=0,
            ),
            timeout=6.0,
        )
    except Exception:
        logger.debug("bedrock warmup request failed", exc_info=True)
    logger.info(
        "bedrock pool warmed elapsed_ms=%.0f", (time.monotonic() - t0) * 1000
    )


def build_llm(cfg: RuntimeConfig | None = None) -> openai.LLM:
    cfg = cfg or RuntimeConfig()

    model_lc = (cfg.llm_model or "").lower()

    # Routing detection
    is_sarvam = model_lc.startswith("sarvam-")
    is_mistral = model_lc.startswith("mistral/")
    is_bedrock = model_lc.startswith("bedrock/")
    is_gemini = model_lc.startswith("gemini/")
    is_xai = model_lc.startswith("xai/")
    is_groq = model_lc.startswith("groq/")

    model_name = cfg.llm_model
    if is_mistral or is_bedrock or is_gemini or is_xai or is_groq:
        model_name = cfg.llm_model.split("/", 1)[1]

    kwargs: dict = {
        "model": model_name,
        "temperature": cfg.llm_temperature,
        # OpenAI gpt-4o-mini has shown throttle/degradation spikes
        # (observed 11.9s TTFT on a live call). 4 retries × backoff
        # stacked into ~12s of dead air. Cap to 2 retries + 6s/attempt so
        # worst-case is bounded — a throttled turn fails fast to the
        # resilience/filler path instead of 12s silence. The real fix is
        # an India-hosted / non-OpenAI provider; this only bounds the tail.
        "max_retries": 2,
        "timeout": 6.0,
        # BREVITY CAP: voice replies must be 1-2 short sentences (the
        # persona says so), but a verbose model (e.g. gpt-4o) can ignore
        # that and ramble — which sounds long-winded and adds TTS latency.
        # Hard-cap the completion so a turn can never run away. Read via
        # settings, NOT os.environ — .env loads into pydantic only, so
        # the old environ read silently stayed at 160 and truncated
        # Telugu replies mid-answer (live bug 2026-06-12, out=160).
        "max_completion_tokens": int(
            os.environ.get("LLM_MAX_OUTPUT_TOKENS")
            or settings.llm_max_output_tokens
        ),
    }
    if is_mistral:
        kwargs["max_retries"] = 0
        kwargs["timeout"] = 5.0
    if is_bedrock:
        # Bedrock Ministral ap-south-1 shows ~12% per-attempt transient 503s
        # under load (probe 2026-06-15). We TESTED max_retries=3 to absorb
        # them, but each retry's backoff lengthens the LLM TAIL (p95) on the
        # failing turns. Per the call owner, keeping the latency tail tight
        # beats squeezing out the last ~1.5% of 503 turns — so ONE retry
        # (the long-standing value). India-hosted + AWS-managed: no 429 to
        # stack on top.
        kwargs["max_retries"] = 1
        kwargs["timeout"] = 8.0
    if is_gemini or is_xai:
        kwargs["max_retries"] = 1
        kwargs["timeout"] = 8.0
    if is_groq:
        # LPU-fast; one quick retry covers a dev-tier 429/blip without
        # stacking latency.
        kwargs["max_retries"] = 1
        kwargs["timeout"] = 8.0
    if is_mistral:
        mistral = _build_mistral_client()
        if mistral is not None:
            kwargs["client"] = mistral
        else:
            logger.warning(
                "Mistral LLM selected but MISTRAL_API_KEY not configured; "
                "falling back to OpenAI defaults"
            )
    elif is_bedrock:
        bedrock = _build_bedrock_client()
        if bedrock is not None:
            kwargs["client"] = bedrock
        else:
            logger.warning(
                "Bedrock LLM selected but AWS_BEARER_TOKEN_BEDROCK not "
                "configured; falling back to OpenAI defaults"
            )
    elif is_sarvam:
        sarvam = _build_sarvam_client()
        if sarvam is not None:
            kwargs["client"] = sarvam
        elif settings.sarvam_api_key:
            # Fallback: pass key + base_url directly; plugin builds its own.
            kwargs["api_key"] = settings.sarvam_api_key
            kwargs["base_url"] = _SARVAM_BASE_URL
        else:
            logger.warning(
                "sarvam LLM selected but SARVAM_API_KEY not configured; "
                "falling back to OpenAI defaults"
            )
    elif is_gemini:
        if settings.gemini_api_key:
            kwargs["api_key"] = settings.gemini_api_key
            kwargs["base_url"] = _GEMINI_BASE_URL
        else:
            logger.warning(
                "Gemini LLM selected but GEMINI_API_KEY not configured; "
                "falling back to OpenAI defaults"
            )
    elif is_xai:
        if settings.xai_api_key:
            kwargs["api_key"] = settings.xai_api_key
            kwargs["base_url"] = _XAI_BASE_URL
        else:
            logger.warning(
                "xAI LLM selected but XAI_API_KEY not configured; "
                "falling back to OpenAI defaults"
            )
    elif is_groq:
        if settings.groq_api_key:
            kwargs["api_key"] = settings.groq_api_key
            kwargs["base_url"] = _GROQ_BASE_URL
        else:
            logger.warning(
                "Groq LLM selected but GROQ_API_KEY not configured; "
                "falling back to OpenAI defaults"
            )
    else:
        shared = _build_shared_client()
        if shared is not None:
            kwargs["client"] = shared
        elif settings.openai_api_key:
            # Fallback if shared client init somehow failed: at least pass
            # the key directly so the plugin builds its own non-pooled client.
            kwargs["api_key"] = settings.openai_api_key
    return openai.LLM(**kwargs)
