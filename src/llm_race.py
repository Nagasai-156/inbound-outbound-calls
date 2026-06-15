"""Parallel LLM racing — kill time-to-first-token variance.

The single biggest *felt* latency problem on our calls is not the median
LLM TTFT (~700ms-1s) but the LONG TAIL: occasional spikes to 3-4s on the
exact same prompt+model (measured: avg 1560ms, max 4140ms). A spike =
multiple seconds of perceived dead air on one turn.

Fast platforms (Vapi documented this) solve it the same way: fire the
SAME request to N backends in parallel and stream whichever returns its
first token first, cancelling the losers. It does NOT make the median
faster — it clips the tail, so the call feels *consistent*. Cost is ~Nx
tokens on the racing turns (cheap on gpt-4o-mini).

This module contains ONLY the provider-agnostic racing primitive over
async generators, so it is unit-testable with fakes (no live network).
`agent.llm_node` builds N identical `Agent.default.llm_node(...)` streams
and delegates here.

Safety contract (critical — past hasty changes caused mid-call dead air):
  * If NO generator yields anything, this yields nothing and returns
    cleanly, so the caller can fall back to a single normal stream.
  * Losers are always cancelled AND aclose()d (frees the HTTP stream /
    cancels the OpenAI request) — even on exceptions, via finally.
  * A generator that errors on its FIRST pull is treated as a non-winner
    (the other(s) can still win) — one backend hiccup never kills the turn.
  * Once a winner is chosen and its first chunk yielded, we stream the
    rest of THAT generator; if it errors mid-stream the error propagates
    (the caller must NOT re-run — that would double the reply).
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

logger = logging.getLogger("llm_race")


async def _safe_aclose(gen) -> None:
    aclose = getattr(gen, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        pass


async def _first_item(gen):
    """Pull the first item from `gen`. Returns a (ok, item) tuple:
    (True, chunk) if it yielded, (False, None) if it ended empty or
    raised. The generator is left paused after its first item so the
    winner can be resumed."""
    try:
        item = await gen.__anext__()
        return True, item
    except StopAsyncIteration:
        return False, None
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.debug("raced stream errored on first pull", exc_info=True)
        return False, None


async def race_async_gens(gens: list) -> AsyncIterator:
    """Yield from whichever generator produces its first item soonest;
    cancel + close the rest. Yields nothing if none produce an item.

    `gens` must be freshly-created async generators (not yet iterated).
    """
    if not gens:
        return
    if len(gens) == 1:
        # Degenerate "race": just stream it (no overhead).
        async for item in gens[0]:
            yield item
        return

    # Map each first-pull task back to its generator.
    tasks: dict[asyncio.Task, object] = {
        asyncio.ensure_future(_first_item(g)): g for g in gens
    }
    winner = None
    first_chunk = None
    try:
        while tasks and winner is None:
            done, _pending = await asyncio.wait(
                tasks.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            for t in done:
                g = tasks.pop(t)
                try:
                    ok, item = t.result()
                except asyncio.CancelledError:
                    ok, item = False, None
                except Exception:
                    ok, item = False, None
                if ok and winner is None:
                    winner, first_chunk = g, item
                else:
                    # Empty/errored stream (or a slower one we won't use
                    # yet) — if it lost, close it. If winner already set,
                    # remaining done losers are closed below.
                    await _safe_aclose(g)

        # Cancel + close every remaining (pending) loser.
        for t, g in list(tasks.items()):
            t.cancel()
            await _safe_aclose(g)
        tasks.clear()

        if winner is None:
            return  # nobody produced anything -> caller falls back

        yield first_chunk
        async for item in winner:
            yield item
    finally:
        # Belt-and-suspenders: ensure no stream is left open.
        for t, g in list(tasks.items()):
            t.cancel()
            await _safe_aclose(g)
        if winner is not None:
            # winner is fully consumed by the async-for above on the happy
            # path; aclose is a no-op if already exhausted.
            await _safe_aclose(winner)
