"""Redis semantic cache with in-process memoization.

Frequent questions (refund / payment / delivery / pricing) should return
in ~cache latency, not ~LLM latency. We embed the utterance (via the
shared, in-process-cached embedder so the same query isn't embedded 3×
in one turn), cosine-match cached FAQ embeddings, and serve the stored
short answer on a hit. Misses fall through to the LLM+KB; the answer is
written back (with TTL) so the next caller is fast.

Two-tier design (NEW):
  L1 = in-process dict — pure-Python lookup, <1ms. Owned by THIS worker
       process. Refreshed every `_MEM_REFRESH_SEC` from Redis so writes
       made by other workers eventually propagate.
  L2 = Redis hash — authoritative shared store, ~50-150ms over network.

Robust:
  * stable SHA-1 entry id (Python `hash()` is per-process random -> on
    restart every entry was orphaned & duplicates collided),
  * expiry stored INLINE in the index value -> one HGETALL scan instead
    of an N+1 `EXISTS` Redis round-trip per cached entry,
  * degrades to a clean miss if Redis/embeddings are unavailable,
  * L1 cache is namespace-scoped (per business) so cross-business poison
    cannot occur even with the in-memory layer,
  * LRU-bounded by `_MEM_MAX_NAMESPACES` so a worker hosting many
    distinct campaigns can't leak memory unboundedly.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict

import numpy as np

from src.config import settings
from src.embeddings import embed as _shared_embed

logger = logging.getLogger("cache")

_INDEX_KEY = "kbcache:index"  # hash: entry_id -> json{vec, answer, exp}

# In-memory tier (L1) policy.
# Increased from 30s to 60s for sub-500ms target - reduces Redis round-trips
_MEM_REFRESH_SEC = 60.0          # re-pull from Redis after this gap
_MEM_MAX_NAMESPACES = 32         # LRU bound on namespaces kept in process


def _entry_id(query: str) -> str:
    return hashlib.sha1(query.strip().lower().encode()).hexdigest()[:20]


def ns_for(persona: str | None) -> str:
    """Stable per-business namespace from the active persona/script.

    The cache used to be ONE global index: an answer cached on business
    A's call ("website starts at 25000") could be served verbatim on a
    different business's call (dental) — the same cross-business poison
    as the content pools. Keying the index by a hash of the running
    persona isolates each business/campaign. Same persona -> shared
    cache (good); different script -> separate cache (no cross-talk).
    """
    sig = (persona or "default").strip().lower()
    return hashlib.sha1(sig.encode()).hexdigest()[:12]


class SemanticCache:
    def __init__(self) -> None:
        self._redis = None
        # Set once per call (agent entrypoint) from the effective
        # persona. Default keeps tests / ad-hoc use working.
        self.namespace = "default"
        # L1 in-memory cache. Each value is a tuple
        # (loaded_at_monotonic, {entry_id: {vec_ndarray, answer, exp}}).
        # OrderedDict so LRU eviction is O(1) on hot-namespace bump.
        self._mem: OrderedDict[
            str, tuple[float, dict[str, dict]]
        ] = OrderedDict()

    def _idx(self) -> str:
        return f"{_INDEX_KEY}:{self.namespace}"

    async def _r(self):
        if self._redis is None:
            import redis.asyncio as redis  # lazy import

            # Tight socket timeouts: a dead/misconfigured Redis must NOT
            # block call startup or the per-turn hot path for the default
            # ~5-30s. 2s connect + 2s op = fast clean miss → fall through
            # to the LLM path instead of hanging the caller's audio.
            self._redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._redis

    @staticmethod
    async def _embed(text: str) -> np.ndarray | None:
        vec = await _shared_embed(text)
        return None if vec is None else np.asarray(vec, dtype=np.float32)

    @staticmethod
    def _cos(a: np.ndarray, b: np.ndarray) -> float:
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
        return float(np.dot(a, b) / denom)

    def _evict_lru(self) -> None:
        """Bound the L1 cache size by namespace count (LRU)."""
        while len(self._mem) > _MEM_MAX_NAMESPACES:
            old_ns, _ = self._mem.popitem(last=False)
            logger.debug("cache L1 evict ns=%s", old_ns)

    async def _refresh_mem(self, ns: str) -> dict[str, dict]:
        """Pull the full namespace index from Redis into L1. Drop expired
        entries server-side along the way. Returns the loaded dict."""
        r = await self._r()
        index = await r.hgetall(f"{_INDEX_KEY}:{ns}")
        now = time.time()
        loaded: dict[str, dict] = {}
        stale: list[str] = []
        for entry_id, blob in index.items():
            try:
                rec = json.loads(blob)
            except Exception:
                stale.append(entry_id)
                continue
            if rec.get("exp", 0) < now:
                stale.append(entry_id)
                continue
            # Pre-convert the embedding to ndarray ONCE on load so the
            # hot lookup path is a pure dot-product (no per-call parse).
            try:
                rec["_vec_np"] = np.asarray(
                    rec.pop("vec"), dtype=np.float32
                )
            except Exception:
                stale.append(entry_id)
                continue
            loaded[entry_id] = rec
        if stale:
            try:
                await r.hdel(f"{_INDEX_KEY}:{ns}", *stale)
            except Exception:
                logger.debug("cache stale prune failed", exc_info=True)
        return loaded

    async def _get_mem(self, ns: str) -> dict[str, dict] | None:
        """L1 fetch. Refresh from Redis if absent or older than the TTL.
        Returns None only if Redis is unreachable and L1 is empty."""
        entry = self._mem.get(ns)
        now_m = time.monotonic()
        if entry is not None:
            loaded_at, mem_index = entry
            if (now_m - loaded_at) < _MEM_REFRESH_SEC:
                # Mark recently-used.
                self._mem.move_to_end(ns)
                return mem_index
        # Stale or missing — refresh.
        try:
            loaded = await self._refresh_mem(ns)
            self._mem[ns] = (now_m, loaded)
            self._mem.move_to_end(ns)
            self._evict_lru()
            return loaded
        except Exception:
            logger.debug("cache L1 refresh failed", exc_info=True)
            # Fall back to whatever stale copy we had, if any.
            return entry[1] if entry is not None else None

    async def lookup(
        self, query: str, min_similarity: float | None = None
    ) -> str | None:
        """Return a cached answer if a near-duplicate question exists.

        Hot path is now: L1 dict access (<1ms) + cosine scan over the
        already-parsed numpy embeddings. Redis is only touched when L1
        is stale (>30s) or empty.
        """
        threshold = (
            min_similarity
            if min_similarity is not None
            else settings.semantic_cache_min_similarity
        )
        try:
            vec = await self._embed(query)
            if vec is None:
                return None
            mem_index = await self._get_mem(self.namespace)
            if not mem_index:
                return None
            best_answer, best_sim = None, 0.0
            for rec in mem_index.values():
                sim = self._cos(vec, rec["_vec_np"])
                if sim > best_sim:
                    best_answer, best_sim = rec["answer"], sim
            if best_answer and best_sim >= threshold:
                logger.debug("semantic cache hit sim=%.3f", best_sim)
                return best_answer
            return None
        except Exception:
            logger.debug("cache lookup failed", exc_info=True)
            return None

    async def store(self, query: str, answer: str) -> None:
        """Write a (question, answer) pair back with inline TTL.

        Also patches the L1 cache for THIS namespace so the writer's
        next lookup hits the just-stored entry immediately — without
        waiting 30s for the natural refresh window."""
        try:
            r = await self._r()
            vec = await self._embed(query)
            if vec is None:
                return
            exp = time.time() + settings.semantic_cache_ttl_seconds
            blob = json.dumps(
                {
                    "vec": vec.tolist(),
                    "answer": answer,
                    "exp": exp,
                }
            )
            eid = _entry_id(query)
            await r.hset(self._idx(), eid, blob)
            # L1 patch: mirror the write so we don't lose the freshness
            # benefit of having JUST written until the next refresh.
            entry = self._mem.get(self.namespace)
            if entry is not None:
                _, mem_index = entry
                mem_index[eid] = {
                    "_vec_np": np.asarray(vec, dtype=np.float32),
                    "answer": answer,
                    "exp": exp,
                }
        except Exception:
            logger.debug("cache store failed", exc_info=True)


# Process-wide singleton.
semantic_cache = SemanticCache()
