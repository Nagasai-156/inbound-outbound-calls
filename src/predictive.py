"""Predictive (speculative) response prefetch.

While the caller is still talking, the stabilized partial ("can you
chec—") often already reveals the intent. We classify that stable prefix
and, if it points at a cacheable/KB question, start the cache+KB lookup
*before the turn ends*. If the final transcript confirms the same intent,
the answer is already warm → "crazy fast" feel. If the prediction was
wrong, the speculative task is discarded (bounded concurrency, cancelled
via the CancellationRegistry on barge-in) — cheap and invisible.

Only STABLE prefixes from the transcript stabilizer drive this, never raw
flickering partials.
"""

from __future__ import annotations

import asyncio
import logging

from src.cache import semantic_cache
from src.kb import kb_answer
from src.router.classifier import classify

logger = logging.getLogger("predictive")

# Intents worth speculatively resolving (they hit cache/KB, not actions
# that need caller-specific ids). Expanded with greeting/thanks/bye so
# borderline stable-prefix turns ("thanks bro—") can warm a tail like
# "thanks bro one more thing" — bounded by the Semaphore(1) below.
_PREFETCHABLE = {"refund", "payment_issue", "order_status", "unknown",
                 "greeting", "thanks", "bye"}


class PredictivePrefetch:
    def __init__(self, max_inflight: int = 1) -> None:
        self._sem = asyncio.Semaphore(max_inflight)
        self._predicted_query: str | None = None
        self._result: str | None = None
        self._task: asyncio.Task | None = None

    def reset(self) -> None:
        """Call at end of a user turn."""
        self._predicted_query = None
        self._result = None
        self._task = None

    async def _prefetch(self, query: str) -> None:
        async with self._sem:
            try:
                hit = await semantic_cache.lookup(query)
                self._result = hit or await kb_answer(query)
                if self._result:
                    logger.debug("predictive warm answer ready")
            except asyncio.CancelledError:  # barge-in / wrong prediction
                raise
            except Exception:
                logger.debug("predictive prefetch failed", exc_info=True)

    def maybe_prefetch(self, stable_prefix: str, registry) -> None:
        """Given a newly extended stable prefix, kick off speculative
        work if the intent looks prefetchable and we haven't already."""
        text = (stable_prefix or "").strip()
        if not text or len(text.split()) < 2 or self._task is not None:
            return
        cls = classify(text)
        if cls.intent not in _PREFETCHABLE or cls.is_trivial:
            return
        self._predicted_query = text
        # Track via the cancellation registry so a barge-in kills it.
        self._task = registry.spawn(self._prefetch(text))

    async def take_if_matches(self, final_text: str) -> str | None:
        """If the final transcript matches the prediction, return the
        warm answer (awaiting the in-flight task briefly). Else None and
        the speculative work is dropped.

        TIMEOUT POLICY (revised after measurement-driven audit):
          * 0.1s wait was tuned for cache lookups (50-80ms typical) but
            CHOKED KB-backed answers (200-400ms typical) — predictive's
            potential 400-600ms win was wasted because the timeout
            tripped just before the KB synthesis finished.
          * New policy: 0.30s wait. On the median the prefetch is done
            before this call returns (no wait at all). On the slow tail
            we accept up to +200ms perceived wait to claim the full
            speculative-prefetch win instead of falling back to a 400-
            600ms LLM round-trip. Net positive on every percentile we
            care about.
          * If the speculative path is still not ready after 0.30s, the
            main LLM is genuinely faster — bail out and let the real
            path run."""
        if not self._predicted_query or self._task is None:
            return None
        final = (final_text or "").strip().lower()
        pred = self._predicted_query.lower()
        # Confirmed if the prediction is a prefix of / contained in final.
        if not (final.startswith(pred) or pred in final):
            self._task.cancel()
            return None
        # Fast path: task already finished — no wait at all.
        if self._task.done() or self._task.cancelled():
            return self._result
        try:
            # Reduced from 0.30s to 0.20s for sub-500ms target. With Groq LLM
            # (100-250ms TTFT), we can afford shorter wait on prefetch miss.
            await asyncio.wait_for(asyncio.shield(self._task), timeout=0.20)
        except asyncio.TimeoutError:
            return None
        except Exception:
            # NOTE: asyncio.CancelledError is deliberately NOT caught — on
            # barge-in / session teardown the turn handler is cancelled
            # while awaiting here; swallowing it would let a cancelled
            # turn keep running (router -> _say) for input the caller
            # already interrupted. Let it propagate (it's a BaseException
            # in 3.8+, so `except Exception` won't catch it either).
            return None
        return self._result
