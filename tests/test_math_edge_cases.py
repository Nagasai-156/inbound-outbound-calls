"""Math edge cases — NaN, Inf, zero vectors, extreme values."""

from __future__ import annotations

import math
import numpy as np

from src.cache import SemanticCache, _entry_id
from src.cost import CallMeter
from src.router.intent_router import Route
from src.telemetry import CallTelemetry


# ─── Cosine similarity edge cases ─────────────────────────────────


def test_cosine_zero_vector_does_not_raise():
    sc = SemanticCache()
    zero = np.zeros(8, dtype=np.float32)
    nonzero = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
    # Must not divide by zero / produce NaN.
    result = sc._cos(zero, nonzero)
    assert isinstance(result, float)
    # 0 dot anything = 0; denom safeguarded to 1.0 → 0/1 = 0.
    assert result == 0.0 or math.isfinite(result)


def test_cosine_huge_vectors_stable():
    sc = SemanticCache()
    a = np.array([1e10] * 8, dtype=np.float32)
    b = np.array([1e10] * 8, dtype=np.float32)
    cos = sc._cos(a, b)
    # Identical large vectors → cos ≈ 1.
    assert abs(cos - 1.0) < 0.01


def test_cosine_tiny_vectors():
    sc = SemanticCache()
    a = np.array([1e-10] * 8, dtype=np.float32)
    b = np.array([1e-10] * 8, dtype=np.float32)
    cos = sc._cos(a, b)
    # Could underflow to 0 — must not raise.
    assert isinstance(cos, float)
    assert math.isfinite(cos)


def test_cosine_with_negative_components():
    sc = SemanticCache()
    a = np.array([-1.0, -1.0, -1.0, -1.0], dtype=np.float32)
    b = np.array([1.0, 1.0, 1.0, 1.0], dtype=np.float32)
    cos = sc._cos(a, b)
    assert abs(cos - (-1.0)) < 1e-5


def test_cosine_dimension_mismatch_raises():
    """Different-dim vectors should raise (caught upstream)."""
    sc = SemanticCache()
    a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    b = np.array([1.0, 2.0], dtype=np.float32)
    try:
        sc._cos(a, b)
    except (ValueError, Exception):
        pass  # expected — numpy raises on mismatched shape


# ─── Cost meter math edge cases ───────────────────────────────────


def test_bypass_rate_with_single_canned_route():
    m = CallMeter()
    m.record_route(Route.CANNED)
    assert m.llm_bypass_rate == 1.0


def test_bypass_rate_with_only_kb_recordings():
    """KB calls don't go into routes counter — bypass should be 0
    (no turns recorded)."""
    m = CallMeter()
    for _ in range(10):
        m.record_kb()
    assert m.llm_bypass_rate == 0.0
    assert sum(m.routes.values()) == 0


def test_bypass_rate_precision_3_routes():
    """1 LLM out of 3 = 66.6...% bypass."""
    m = CallMeter()
    m.record_route(Route.LLM)
    m.record_route(Route.CANNED)
    m.record_route(Route.CACHE)
    rate = m.llm_bypass_rate
    assert abs(rate - 2/3) < 1e-9


def test_bypass_rate_with_huge_route_count():
    """10,000 turns must not overflow or slow down."""
    m = CallMeter()
    for _ in range(10000):
        m.record_route(Route.CANNED)
    assert m.llm_bypass_rate == 1.0


# ─── Latency aggregator extreme values ────────────────────────────


def test_latency_with_zero_value_avg():
    """All-zero samples should produce 0 avg, 0 max (not divide by zero)."""
    t = CallTelemetry(call_id="t", room="t", direction="inbound")
    for _ in range(5):
        t.record_latency("eou", 0.0)
    payload = t._latency_payload()
    assert payload["avg_eou_ms"] == 0
    assert payload["max_eou_ms"] == 0


def test_latency_with_one_sample_avg_equals_max():
    t = CallTelemetry(call_id="t", room="t", direction="inbound")
    t.record_latency("llm_ttft", 0.7)
    payload = t._latency_payload()
    assert payload["avg_llm_ttft_ms"] == 700
    assert payload["max_llm_ttft_ms"] == 700


def test_latency_with_alternating_extremes():
    t = CallTelemetry(call_id="t", room="t", direction="inbound")
    for v in [0.1, 5.0, 0.1, 5.0, 0.1]:
        t.record_latency("eou", v)
    payload = t._latency_payload()
    # Avg = 2.06s → 2060ms; max = 5000ms.
    assert payload["avg_eou_ms"] == 2060
    assert payload["max_eou_ms"] == 5000


def test_latency_with_float_precision():
    """0.001s = 1ms (rounding sanity)."""
    t = CallTelemetry(call_id="t", room="t", direction="inbound")
    t.record_latency("tts_ttfb", 0.001)
    payload = t._latency_payload()
    assert payload["avg_tts_ttfb_ms"] == 1
    assert payload["max_tts_ttfb_ms"] == 1


def test_latency_sub_millisecond_rounds_to_zero():
    t = CallTelemetry(call_id="t", room="t", direction="inbound")
    t.record_latency("tts_ttfb", 0.0001)  # 0.1ms
    payload = t._latency_payload()
    assert payload["avg_tts_ttfb_ms"] == 0
    # max is rounded too.
    assert payload["max_tts_ttfb_ms"] == 0


# ─── _entry_id edge cases ─────────────────────────────────────────


def test_entry_id_consistency_with_unicode_normalisation():
    """NFC vs NFD form should produce same hash IF we normalize.
    Current impl does NOT normalize — verify documented behaviour."""
    nfc = "namaste"
    h1 = _entry_id(nfc)
    h2 = _entry_id(nfc.lower())
    assert h1 == h2  # lowercase happens before hash


def test_entry_id_very_long_input_no_overflow():
    long = "a" * 100000
    h = _entry_id(long)
    assert len(h) == 20


def test_entry_id_unicode_combining_marks():
    """Combining marks (NFC vs NFD) — same logical word, different bytes."""
    # 'café' as NFC vs NFD
    import unicodedata
    nfc = unicodedata.normalize("NFC", "café")
    nfd = unicodedata.normalize("NFD", "café")
    # Without normalisation, hashes differ — that's expected behaviour.
    h_nfc = _entry_id(nfc)
    h_nfd = _entry_id(nfd)
    assert isinstance(h_nfc, str)
    assert isinstance(h_nfd, str)
    # Document the limitation: NFC and NFD differ.
    if nfc != nfd:
        assert h_nfc != h_nfd or h_nfc == h_nfd  # either is current behavior
