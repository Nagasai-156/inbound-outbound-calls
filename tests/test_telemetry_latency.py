"""CallTelemetry.record_latency aggregator tests.

The per-call Latency panel on the dashboard reads avg/max for 3 buckets
(eou, llm_ttft, tts_ttfb). These tests pin the running-aggregate math
(sum/count rounded → ms, max → ms) and bad-input rejection.
"""

from __future__ import annotations

from src.telemetry import CallTelemetry


def _new() -> CallTelemetry:
    return CallTelemetry(call_id="t-test", room="t-test", direction="inbound")


def test_record_and_payload_basic():
    t = _new()
    t.record_latency("eou", 0.6)
    t.record_latency("eou", 1.0)
    t.record_latency("eou", 0.2)
    t.record_latency("llm_ttft", 0.4)
    t.record_latency("tts_ttfb", 0.25)
    out = t._latency_payload()
    assert out["avg_eou_ms"] == 600       # (600 + 1000 + 200) / 3
    assert out["max_eou_ms"] == 1000
    assert out["avg_llm_ttft_ms"] == 400
    assert out["max_llm_ttft_ms"] == 400
    assert out["avg_tts_ttfb_ms"] == 250
    assert out["max_tts_ttfb_ms"] == 250


def test_empty_aggregates_are_zero():
    t = _new()
    out = t._latency_payload()
    for k in (
        "avg_eou_ms", "max_eou_ms",
        "avg_llm_ttft_ms", "max_llm_ttft_ms",
        "avg_tts_ttfb_ms", "max_tts_ttfb_ms",
    ):
        assert out[k] == 0, f"{k} should be 0 with no samples"


def test_unknown_kind_is_silently_ignored():
    # Defensive — a typo'd kind must not crash a live call.
    t = _new()
    t.record_latency("typo", 0.5)
    t.record_latency("LLM", 0.5)        # case-sensitive
    out = t._latency_payload()
    for k in out:
        assert out[k] == 0


def test_none_and_invalid_values_are_skipped():
    t = _new()
    t.record_latency("eou", None)        # type: ignore[arg-type]
    t.record_latency("eou", "abc")       # type: ignore[arg-type]
    t.record_latency("eou", -0.5)        # negative -> skip
    t.record_latency("eou", 0.4)         # only this counts
    out = t._latency_payload()
    assert out["avg_eou_ms"] == 400
    assert out["max_eou_ms"] == 400


def test_max_is_absolute_max_not_recent():
    t = _new()
    t.record_latency("llm_ttft", 2.0)
    t.record_latency("llm_ttft", 0.3)
    t.record_latency("llm_ttft", 0.4)
    out = t._latency_payload()
    assert out["max_llm_ttft_ms"] == 2000


def test_kinds_are_independent():
    t = _new()
    t.record_latency("eou", 1.5)
    t.record_latency("llm_ttft", 0.5)
    out = t._latency_payload()
    assert out["max_eou_ms"] == 1500
    assert out["max_llm_ttft_ms"] == 500  # NOT 1500
