"""CallTelemetry lifecycle + state tests (no Redis/DB connection)."""

from __future__ import annotations

import asyncio
import pytest

from src.telemetry import CallTelemetry


def _new(call_id: str = "test") -> CallTelemetry:
    return CallTelemetry(call_id=call_id, room=call_id, direction="inbound")


def test_initial_state():
    t = _new()
    assert t.call_id == "test"
    assert t._call_ready is False
    assert t._tasks == set()


def test_lat_dict_has_three_kinds_initially():
    t = _new()
    assert set(t._lat.keys()) == {
        "eou", "llm_ttft", "tts_ttfb", "response",
        "assembly", "snapshot_db",
    }
    for k, slot in t._lat.items():
        assert slot["sum"] == 0.0
        assert slot["count"] == 0
        assert slot["max"] == 0.0


def test_record_latency_increments_correctly():
    t = _new()
    t.record_latency("eou", 0.5)
    assert t._lat["eou"]["count"] == 1
    assert t._lat["eou"]["sum"] == 0.5
    assert t._lat["eou"]["max"] == 0.5


def test_record_latency_max_tracks_max():
    t = _new()
    t.record_latency("eou", 0.5)
    t.record_latency("eou", 0.2)
    t.record_latency("eou", 0.9)
    t.record_latency("eou", 0.3)
    assert t._lat["eou"]["max"] == 0.9


def test_record_latency_zero_value_counts():
    """0s latency is valid (instant) — must count."""
    t = _new()
    t.record_latency("eou", 0.0)
    assert t._lat["eou"]["count"] == 1
    # Max stays 0 (which is correct — 0 isn't > 0).
    assert t._lat["eou"]["max"] == 0.0


def test_payload_is_int_milliseconds():
    """Dashboard reads integers from DB; payload must be int."""
    t = _new()
    t.record_latency("eou", 0.123)
    payload = t._latency_payload()
    assert isinstance(payload["avg_eou_ms"], int)
    assert isinstance(payload["max_eou_ms"], int)


def test_payload_rounds_to_nearest_ms():
    t = _new()
    # 0.1235s = 123.5ms -> rounds to 124.
    t.record_latency("eou", 0.1235)
    payload = t._latency_payload()
    assert payload["avg_eou_ms"] in (123, 124)


def test_payload_keys_complete_for_six_fields():
    """Dashboard expects latency fields per call (now incl. response)."""
    t = _new()
    payload = t._latency_payload()
    expected = {
        "avg_eou_ms", "max_eou_ms",
        "avg_llm_ttft_ms", "max_llm_ttft_ms",
        "avg_tts_ttfb_ms", "max_tts_ttfb_ms",
        "avg_response_ms", "max_response_ms",
        "avg_assembly_ms", "max_assembly_ms",
        "avg_snapshot_db_ms", "max_snapshot_db_ms",
    }
    assert set(payload.keys()) == expected


@pytest.mark.asyncio
async def test_spawn_tracks_task():
    t = _new()

    async def work():
        await asyncio.sleep(0.01)

    t.spawn(work())
    assert len(t._tasks) >= 1


@pytest.mark.asyncio
async def test_spawn_auto_removes_completed_task():
    t = _new()

    async def fast():
        return None

    t.spawn(fast())
    await asyncio.sleep(0.05)
    # done callback should have discarded.
    assert len(t._tasks) == 0


@pytest.mark.asyncio
async def test_flush_awaits_all_pending():
    t = _new()
    results = []

    async def work(i):
        await asyncio.sleep(0.05)
        results.append(i)

    for i in range(3):
        t.spawn(work(i))
    await t.flush(timeout=2.0)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_flush_respects_timeout():
    """If tasks exceed timeout, flush returns without hanging the call
    teardown."""
    t = _new()

    async def slow():
        await asyncio.sleep(10)

    t.spawn(slow())
    import time
    t0 = time.monotonic()
    await t.flush(timeout=0.1)
    elapsed = time.monotonic() - t0
    # Should return within ~timeout, not 10s.
    assert elapsed < 1.0


def test_record_latency_with_huge_value_doesnt_overflow():
    t = _new()
    # 10 minute LLM "latency" — pathological but must not break math.
    t.record_latency("llm_ttft", 600.0)
    payload = t._latency_payload()
    assert payload["max_llm_ttft_ms"] == 600000


def test_payload_independent_kinds_stay_independent():
    t = _new()
    t.record_latency("eou", 0.5)
    payload = t._latency_payload()
    # LLM and TTS should still be 0.
    assert payload["avg_llm_ttft_ms"] == 0
    assert payload["max_llm_ttft_ms"] == 0
    assert payload["avg_tts_ttfb_ms"] == 0
    assert payload["max_tts_ttfb_ms"] == 0
