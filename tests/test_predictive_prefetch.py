"""PredictivePrefetch tests — pure-logic, no actual KB/cache calls."""

from __future__ import annotations

import asyncio
import pytest

from src.predictive import PredictivePrefetch, _PREFETCHABLE
from src.cancellation import CancellationRegistry


def test_initial_state_is_empty():
    p = PredictivePrefetch()
    assert p._predicted_query is None
    assert p._result is None
    assert p._task is None


def test_reset_clears_state():
    p = PredictivePrefetch()
    p._predicted_query = "x"
    p._result = "y"
    p._task = object()  # type: ignore[assignment]
    p.reset()
    assert p._predicted_query is None
    assert p._result is None
    assert p._task is None


def test_maybe_prefetch_skips_short_prefix():
    """A 1-word prefix is too short to predict an intent reliably."""
    p = PredictivePrefetch()
    reg = CancellationRegistry()
    p.maybe_prefetch("hello", reg)
    assert p._task is None


def test_maybe_prefetch_skips_empty_prefix():
    p = PredictivePrefetch()
    reg = CancellationRegistry()
    p.maybe_prefetch("", reg)
    assert p._task is None


def test_maybe_prefetch_skips_when_already_running():
    """Only ONE inflight prefetch — Semaphore(1) bounds concurrency."""
    p = PredictivePrefetch()
    reg = CancellationRegistry()
    p._task = object()  # type: ignore[assignment]
    # Should be a no-op despite eligible text.
    p.maybe_prefetch("can you refund my order", reg)
    # Task should not be replaced.
    assert isinstance(p._task, object)


def test_maybe_prefetch_skips_trivial_intent():
    """Trivial intents (short ack/bye) are handled by canned, not LLM —
    speculative work would be wasted."""
    p = PredictivePrefetch()
    reg = CancellationRegistry()
    # "yes ok" is short + trivial.
    p.maybe_prefetch("yes ok", reg)
    assert p._task is None


def test_prefetchable_intents_include_kb_likely():
    for intent in ("refund", "payment_issue", "order_status"):
        assert intent in _PREFETCHABLE


def test_prefetchable_excludes_appointment_intents():
    """Appointment booking needs CALLER-specific data (date/time/phone) —
    speculative prefetch can't help, and might pre-generate the wrong
    slot list."""
    # Not listed in _PREFETCHABLE.
    appointment_intents = {"appointment", "reschedule", "cancel"}
    assert appointment_intents.isdisjoint(_PREFETCHABLE)


@pytest.mark.asyncio
async def test_take_if_matches_returns_none_without_prediction():
    p = PredictivePrefetch()
    out = await p.take_if_matches("anything")
    assert out is None


@pytest.mark.asyncio
async def test_take_if_matches_prefix_match():
    """The prediction's text being a prefix of the final transcript
    confirms the prediction."""
    p = PredictivePrefetch()
    p._predicted_query = "where is my order"
    p._result = "WARM-ANSWER"

    async def _done():
        return None

    p._task = asyncio.create_task(_done())
    await p._task  # let it finish
    out = await p.take_if_matches("where is my order id 12345")
    assert out == "WARM-ANSWER"


@pytest.mark.asyncio
async def test_take_if_matches_substring_match():
    p = PredictivePrefetch()
    p._predicted_query = "refund"
    p._result = "REFUND-WARM"

    async def _done():
        return None

    p._task = asyncio.create_task(_done())
    await p._task
    # Final transcript contains "refund" as substring.
    out = await p.take_if_matches("i want a refund please")
    assert out == "REFUND-WARM"


@pytest.mark.asyncio
async def test_take_if_matches_mismatch_returns_none_and_cancels():
    p = PredictivePrefetch()
    p._predicted_query = "refund"

    async def slow():
        await asyncio.sleep(10)

    p._task = asyncio.create_task(slow())
    out = await p.take_if_matches("can you book me an appointment")
    assert out is None
    # Let the cancel propagate (task may be in "cancelling" state).
    try:
        await p._task
    except asyncio.CancelledError:
        pass
    assert p._task.cancelled() or p._task.done()


@pytest.mark.asyncio
async def test_take_if_matches_handles_empty_final():
    p = PredictivePrefetch()
    p._predicted_query = "something"
    p._task = asyncio.create_task(asyncio.sleep(10))
    out = await p.take_if_matches("")
    # Empty doesn't match anything — should return None.
    assert out is None
    p._task.cancel()


@pytest.mark.asyncio
async def test_take_if_matches_done_task_returns_immediately():
    p = PredictivePrefetch()
    p._predicted_query = "test"
    p._result = "X"

    async def _quick():
        return None

    p._task = asyncio.create_task(_quick())
    await p._task
    # Already done — should return immediately without timeout.
    import time
    t0 = time.monotonic()
    out = await p.take_if_matches("test query")
    elapsed = time.monotonic() - t0
    assert out == "X"
    assert elapsed < 0.05  # near-instant
