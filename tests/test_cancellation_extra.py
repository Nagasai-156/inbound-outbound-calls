"""Extended CancellationRegistry tests beyond the basic existing one."""

from __future__ import annotations

import asyncio
import pytest

from src.cancellation import CancellationRegistry


@pytest.mark.asyncio
async def test_track_registers_task():
    reg = CancellationRegistry()

    async def slow():
        await asyncio.sleep(10)

    t = asyncio.ensure_future(slow())
    reg.track(t)
    assert t in reg._tasks
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_completed_task_auto_removed():
    reg = CancellationRegistry()

    async def fast():
        return "done"

    t = reg.spawn(fast())
    await t  # let it complete
    # done callback should have removed it.
    await asyncio.sleep(0)
    assert t not in reg._tasks


@pytest.mark.asyncio
async def test_cancel_generation_cancels_pending():
    reg = CancellationRegistry()

    async def slow():
        await asyncio.sleep(10)

    reg.spawn(slow())
    reg.spawn(slow())
    reg.spawn(slow())
    n = reg.cancel_generation()
    assert n == 3


@pytest.mark.asyncio
async def test_cancel_generation_idempotent():
    reg = CancellationRegistry()
    # No pending tasks.
    assert reg.cancel_generation() == 0
    assert reg.cancel_generation() == 0
    assert reg.cancel_generation() == 0


@pytest.mark.asyncio
async def test_cancel_skips_already_done_tasks():
    reg = CancellationRegistry()

    async def fast():
        return None

    t = reg.spawn(fast())
    await t
    # Task already completed — cancel_generation should return 0.
    assert reg.cancel_generation() == 0


@pytest.mark.asyncio
async def test_spawn_returns_trackable_task():
    reg = CancellationRegistry()

    async def work():
        await asyncio.sleep(0.01)
        return 42

    t = reg.spawn(work())
    assert isinstance(t, asyncio.Task)
    result = await t
    assert result == 42


@pytest.mark.asyncio
async def test_flush_tts_calls_interrupt():
    class FakeSession:
        called = False
        async def interrupt(self):
            FakeSession.called = True

    reg = CancellationRegistry()
    await reg.flush_tts(FakeSession())
    assert FakeSession.called is True


@pytest.mark.asyncio
async def test_flush_tts_fallbacks_to_stop_speaking():
    class FakeSession:
        called = False
        def stop_speaking(self):
            FakeSession.called = True

    reg = CancellationRegistry()
    await reg.flush_tts(FakeSession())
    assert FakeSession.called is True


@pytest.mark.asyncio
async def test_flush_tts_handles_no_method():
    """Session with none of the known methods must not crash."""
    class FakeSession:
        pass

    reg = CancellationRegistry()
    # Must not raise.
    await reg.flush_tts(FakeSession())


@pytest.mark.asyncio
async def test_on_interrupt_runs_both():
    """on_interrupt = cancel pending + flush TTS."""
    class FakeSession:
        called = False
        async def interrupt(self):
            FakeSession.called = True

    reg = CancellationRegistry()

    async def slow():
        await asyncio.sleep(10)

    reg.spawn(slow())
    await reg.on_interrupt(FakeSession())
    assert FakeSession.called is True
    # Pending task should be cancelled.
    assert len(reg._tasks) == 0
