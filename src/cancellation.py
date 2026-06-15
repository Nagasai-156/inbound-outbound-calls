"""Token-level interruption cancellation.

LiveKit's AgentSession already aborts ITS own in-flight LLM stream and
flushes TTS on barge-in (allow_interruptions=True). What it does NOT know
about is OUR speculative work: predictive KB/cache prefetch tasks and any
filler/say coroutine we launched. If we don't cancel those on a barge-in
they keep running — wasted OpenAI cost and latency, and a stale answer
can land after the caller already moved on.

This registry tracks per-call background tasks so the FSM `INTERRUPTED`
transition can cancel them in one idempotent call.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("cancellation")


@dataclass
class CancellationRegistry:
    """One per call. Register every speculative asyncio.Task here."""

    call_id: str = "default"
    _tasks: set[asyncio.Task] = field(default_factory=set)

    def track(self, task: asyncio.Task) -> asyncio.Task:
        """Register a speculative task; auto-deregisters on completion.

        The discard callback can fire during cancel_generation iteration
        when a barge-in races a natural task completion (set mutation
        during iteration). Snapshotting `_tasks` and then `.clear()`-ing
        in one synchronous frame guarantees we never iterate a mutating
        set — done callbacks land on the now-empty set as harmless no-ops.
        """
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def spawn(self, coro) -> asyncio.Task:
        """Schedule + track a coroutine in one call."""
        return self.track(asyncio.ensure_future(coro))

    def cancel_generation(self) -> int:
        """Cancel all tracked speculative work. Idempotent — safe to call
        on every barge-in even if nothing is in flight. Returns the count
        cancelled (useful for tests/metrics)."""
        # Drain into a local list atomically (synchronous; no await between
        # snapshot + clear) so a done-callback firing during iteration
        # mutates the now-empty set, not the one we're walking.
        pending = list(self._tasks)
        self._tasks.clear()
        n = 0
        for task in pending:
            if not task.done():
                task.cancel()
                n += 1
        if n:
            logger.debug("cancelled %d speculative task(s) on barge-in", n)
        return n

    async def flush_tts(self, session) -> None:
        """Stop any current agent speech immediately.

        AgentSession flushes on detected interruption, but we also call
        this explicitly from the FSM so a programmatic barge-in (or a
        resilience path) stops audio in <~200ms regardless of detector.
        """
        for method in ("interrupt", "stop_speaking", "clear_audio"):
            fn = getattr(session, method, None)
            if callable(fn):
                try:
                    res = fn()
                    if asyncio.iscoroutine(res):
                        await res
                    return
                except Exception:  # pragma: no cover - API varies
                    logger.debug("flush via %s failed", method, exc_info=True)

    async def on_interrupt(self, session) -> None:
        """Single entry point bound to FSM -> INTERRUPTED."""
        self.cancel_generation()
        await self.flush_tts(session)
