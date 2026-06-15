"""Shared OpenAI embedding helper with a tiny in-process cache.

A single FAQ turn used to embed the SAME query up to 3 times:
  router cache.lookup  ->  kb_store.search  ->  cache.store
= 3 OpenAI round-trips (~300-900ms of dead air) for one question.

This module gives one `embed()` both paths call. A small TTL+LRU cache
(keyed by model+text) collapses those repeated calls in a turn into ONE
real API call. Ingestion uses `embed_batch()` (token-aware, no cache).
"""

from __future__ import annotations

import asyncio
import logging
import time

from src.config import settings

logger = logging.getLogger("embeddings")

_CACHE: dict[str, tuple[float, list[float]]] = {}
_CACHE_TTL = 90.0      # seconds — long enough to cover a single turn
_CACHE_MAX = 256
_lock = asyncio.Lock()


_embed_client = None


def _client():
    """Process-wide AsyncOpenAI client for embeddings.

    LATENCY FIX: this used to build a FRESH `AsyncOpenAI(...)` on every
    call — each with its own httpx pool, so every cache lookup / KB embed
    / predictive prefetch paid a cold TLS handshake (~100-180ms
    India→US-East) for a request that's otherwise ~30-60ms. We now reuse
    the process-wide, keepalive-pooled, already-warmed client from the
    LLM module (same OpenAI key + base) so embeddings ride the SAME warm
    HTTP/2 connections as chat completions — zero per-request handshake
    after the pool is lit. Falls back to a single cached dedicated client
    if the shared one isn't available (e.g. non-OpenAI deploy)."""
    global _embed_client
    if _embed_client is not None:
        return _embed_client
    try:
        from src.pipeline.llm import _build_shared_client

        shared = _build_shared_client()
        if shared is not None:
            _embed_client = shared
            return _embed_client
    except Exception:
        logger.debug("embeddings: shared client unavailable", exc_info=True)
    from openai import AsyncOpenAI

    _embed_client = AsyncOpenAI(api_key=settings.openai_api_key or None)
    return _embed_client


def _prune() -> None:
    if len(_CACHE) <= _CACHE_MAX:
        return
    now = time.monotonic()
    for k in [k for k, (ts, _) in _CACHE.items() if now - ts > _CACHE_TTL]:
        _CACHE.pop(k, None)
    if len(_CACHE) > _CACHE_MAX:  # still big -> drop oldest
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[: _CACHE_MAX // 2]:
            _CACHE.pop(k, None)


async def embed(text: str) -> list[float] | None:
    """Embed one string. Cached per (model,text) for ~90s so the 3
    same-query calls in a turn become 1 real request. Returns None on
    failure (callers degrade gracefully)."""
    text = (text or "").strip()
    if not text:
        return None
    key = f"{settings.embedding_model}\x00{text}"
    hit = _CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL:
        return hit[1]
    try:
        async with _lock:  # de-dupe concurrent identical embeds
            hit = _CACHE.get(key)
            if hit and (time.monotonic() - hit[0]) < _CACHE_TTL:
                return hit[1]
            resp = await _client().embeddings.create(
                model=settings.embedding_model, input=text
            )
            vec = resp.data[0].embedding
            _CACHE[key] = (time.monotonic(), vec)
            _prune()
            return vec
    except Exception:
        logger.debug("embed failed", exc_info=True)
        return None


# Rough token estimate (OpenAI ~4 chars/token for English; Indic script
# is denser, so use 3 to stay safely under limits).
def _est_tokens(s: str) -> int:
    return max(1, len(s) // 3)

# text-embedding-3 hard limit is 8192 tokens/input; keep a safe ceiling
# per input and per request batch.
_MAX_INPUT_TOKENS = 7000
_MAX_REQ_TOKENS = 90_000


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed many strings for ingestion. Token-aware: never sends an
    over-limit input or an over-limit request batch (the old fixed
    64-chunk batch could silently exceed the API limit)."""
    out: list[list[float]] = []
    batch: list[str] = []
    btok = 0
    client = _client()

    async def _flush():
        nonlocal batch, btok
        if not batch:
            return
        resp = await client.embeddings.create(
            model=settings.embedding_model, input=batch
        )
        out.extend(d.embedding for d in resp.data)
        batch, btok = [], 0

    for t in texts:
        t = (t or "").strip() or " "
        tok = min(_est_tokens(t), _MAX_INPUT_TOKENS)
        if t and _est_tokens(t) > _MAX_INPUT_TOKENS:
            t = t[: _MAX_INPUT_TOKENS * 3]  # hard-trim oversized chunk
        if batch and (btok + tok > _MAX_REQ_TOKENS or len(batch) >= 128):
            await _flush()
        batch.append(t)
        btok += tok
    await _flush()
    return out
