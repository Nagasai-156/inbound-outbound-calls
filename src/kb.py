"""Knowledge base — pgvector retrieval (fast path) + optional synthesis.

Two entry points:

* `kb_context(query)` — RETRIEVAL ONLY. Shared-embed + pgvector search,
  ~200ms, NO LLM. Returns the top grounding chunks (or None if nothing
  relevant). This is what the live `kb_search` tool uses: the *main*
  streaming agent LLM — which is already running — turns these chunks
  into one short spoken answer. That removes a whole blocking LLM
  round-trip from every KB question (was 2.5-6s of dead air).

* `kb_answer(query)` — retrieval + a SEPARATE grounded synthesis LLM
  call, returning a finished spoken string. Kept ONLY for the off-
  critical-path users that need a ready-made answer string: speculative
  prefetch (runs while the caller is still talking, so its latency is
  hidden) and the offline smoke/e2e scripts. NOT used on the live turn.

Grounding: retrieval is strict — if nothing clears `kb_min_score` we
return None and the agent says it will check (never a hallucinated fact).
On the tool path the persona's GROUNDING rule + the tool-result wrapper
keep the main LLM strictly inside the returned context.
"""

from __future__ import annotations

import asyncio
import logging

from src.cache import semantic_cache
from src.config import settings
from src.kb_store import search

logger = logging.getLogger("kb")

# Floors are configurable (config.py / env). `kb_min_score` discards
# pure garbage (kept low for cross-lingual recall — the grounded prompt
# is the real anti-hallucination gate). `kb_cache_min_score` is higher:
# only CONFIDENT answers are cached so a marginal/likely-wrong answer is
# never propagated to many subsequent callers.

# Keep the context fed to the LLM TIGHT: every extra token in the prompt
# delays the main LLM's first token (the real perceived-latency floor on
# a KB turn). The answer is almost always in the top-1 chunk; top-2 is
# the safety margin. More than that just inflates the prompt and slows
# first audio without improving the spoken answer.
_MAX_CHUNKS = 2
_MAX_CHUNK_CHARS = 420
_MAX_CONTEXT_CHARS = 800

_SYS = (
    "You answer a phone caller using ONLY the CONTEXT below. One or two "
    "short spoken sentences, conversational, in the caller's language "
    "(Telugu/Hindi/English or their mix). Never quote the document, never "
    "say 'according to'. If the CONTEXT does not contain the answer, "
    "reply EXACTLY: NO_ANSWER"
)


async def _retrieve(query: str, kb_id: str = "") -> tuple[str | None, float]:
    """One pgvector search → (joined context | None, top_score).

    Shared by `kb_context` (live, retrieval-only) and `kb_answer` (off-
    path synthesis) so a KB lookup is exactly ONE pgvector query.
    """
    try:
        # Hard timeout: a stuck pgvector query must degrade to "no
        # context" (the LLM answers without grounding), never dead air.
        hits = await asyncio.wait_for(search(query, k=5, kb_id=kb_id), 1.5)
    except asyncio.TimeoutError:
        logger.warning("kb search timed out (>1.5s) — answering ungrounded")
        return None, 0.0
    except Exception:
        logger.debug("kb search failed", exc_info=True)
        return None, 0.0
    top = hits[0]["score"] if hits else 0.0
    if not hits or top < settings.kb_min_score:
        return None, top

    parts: list[str] = []
    total = 0
    for h in hits[:_MAX_CHUNKS]:
        chunk = (h["content"] or "").strip()[:_MAX_CHUNK_CHARS]
        if not chunk:
            continue
        if total + len(chunk) > _MAX_CONTEXT_CHARS:
            chunk = chunk[: _MAX_CONTEXT_CHARS - total]
        parts.append(chunk)
        total += len(chunk)
        if total >= _MAX_CONTEXT_CHARS:
            break
    return ("\n---\n".join(parts) if parts else None), top


async def kb_context(query: str, kb_id: str = "") -> str | None:
    """Fast grounding context for the live tool path — retrieval only.

    Returns the top KB chunks joined as plain text, or None if nothing
    relevant cleared `kb_min_score`. No LLM call → ~pgvector latency.
    """
    context, _ = await _retrieve(query, kb_id=kb_id)
    return context


async def kb_answer(query: str, kb_id: str = "") -> str | None:
    """Grounded short answer from the KB, or None if not covered.

    Off-critical-path only (speculative prefetch / offline tests): does a
    second LLM synthesis call. The live turn uses `kb_context` instead so
    the main streaming LLM does the synthesis with no extra round-trip.
    """
    context, top = await _retrieve(query, kb_id=kb_id)
    if not context:
        return None

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key or None)
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.0,  # grounded synthesis — no creative drift
            messages=[
                {"role": "system", "content": _SYS},
                {
                    "role": "user",
                    "content": f"CONTEXT:\n{context}\n\nQUESTION: {query}",
                },
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception:
        logger.debug("kb synthesis failed", exc_info=True)
        return None

    if not text or "NO_ANSWER" in text:
        return None
    # Only propagate to the cache when retrieval was CONFIDENT — a
    # marginal (cross-lingual / weak) match is still answered live but
    # not cached, so one shaky answer can't be served to many callers.
    if top >= settings.kb_cache_min_score:
        await semantic_cache.store(query, text)
    return text
