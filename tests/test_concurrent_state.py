"""Concurrent / race-condition tests for shared in-memory state.

CallMemory, CallMeter, CancellationRegistry, and TranscriptStabilizer
are all mutated concurrently in a real call (telemetry tasks, persist
coroutines, metrics handlers). Tests pin behaviour under concurrent
access patterns."""

from __future__ import annotations

import asyncio
import pytest

from src.cost import CallMeter
from src.cancellation import CancellationRegistry
from src.memory import CallMemory
from src.router.intent_router import Route


@pytest.mark.asyncio
async def test_meter_concurrent_record_routes_no_loss():
    """Counter increments under asyncio are safe because Python's GIL
    serialises bytecode. Verify no count loss under heavy concurrency."""
    m = CallMeter()
    N = 1000

    async def bump():
        m.record_route(Route.CANNED)

    await asyncio.gather(*[bump() for _ in range(N)])
    assert sum(m.routes.values()) == N


@pytest.mark.asyncio
async def test_meter_concurrent_mixed_routes():
    m = CallMeter()
    N = 200

    async def llm():
        m.record_route(Route.LLM)
    async def canned():
        m.record_route(Route.CANNED)
    async def kb():
        m.record_kb()

    await asyncio.gather(
        *[llm() for _ in range(N)],
        *[canned() for _ in range(N)],
        *[kb() for _ in range(N)],
    )
    assert m.llm_calls == N
    assert m.kb_calls == N
    assert sum(m.routes.values()) == 2 * N


@pytest.mark.asyncio
async def test_cancellation_registry_concurrent_spawn_and_cancel():
    """Spawn 100 long tasks concurrently, cancel them all — no task
    should leak."""
    reg = CancellationRegistry()

    async def slow():
        await asyncio.sleep(60)

    tasks = [reg.spawn(slow()) for _ in range(100)]
    n = reg.cancel_generation()
    assert n == 100
    # All tasks should be cancelled.
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_cancellation_registry_done_callback_race():
    """A task completing naturally while cancel_generation iterates must
    not raise (set mutation during iteration)."""
    reg = CancellationRegistry()

    async def fast():
        return None

    # Spawn many; some will complete before cancel.
    tasks = [reg.spawn(fast()) for _ in range(50)]
    await asyncio.sleep(0)  # give them a chance to finish
    # Should not raise.
    reg.cancel_generation()


@pytest.mark.asyncio
async def test_call_memory_concurrent_updates():
    """Two coroutines updating the same memory concurrently."""
    m = CallMemory(call_id="c1")

    async def updater(intent):
        m.update_from_turn("test", "te", intent)

    await asyncio.gather(*[updater(f"intent_{i}") for i in range(50)])
    # Last write wins on intent — but the field is a string, not None/corrupted.
    assert isinstance(m.intent, str)
    assert m.language == "te"


@pytest.mark.asyncio
async def test_meter_summary_during_concurrent_record():
    """Reading summary string while concurrent writes happen should
    not crash and should return some valid string."""
    m = CallMeter()

    async def writer():
        for _ in range(100):
            m.record_route(Route.LLM)
            await asyncio.sleep(0)

    async def reader():
        for _ in range(100):
            s = m.summary()
            assert "turns=" in s
            await asyncio.sleep(0)

    await asyncio.gather(writer(), reader())
