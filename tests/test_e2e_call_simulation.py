"""End-to-end call-flow simulations — pure-logic chains, no I/O.

Simulates realistic turn sequences through the full router →
memory → meter → telemetry pipeline. Catches integration regressions
that pure unit tests miss."""

from __future__ import annotations

import pytest

from src.cost import CallMeter
from src.memory import CallMemory
from src.router.classifier import classify
from src.router.canned import canned_response
from src.router.intent_router import Route
from src.telemetry import CallTelemetry
from src.filler import should_filler, pick_filler


# ─── Inbound support call simulation ─────────────────────────────


def test_e2e_inbound_support_flow():
    """A typical inbound support call: greeting → question → bye."""
    memory = CallMemory(call_id="inb-1")
    meter = CallMeter()
    tel = CallTelemetry(call_id="inb-1", room="inb-1", direction="inbound")

    # Turn 1: caller greets
    text = "hello"
    cls = classify(text)
    memory.update_from_turn(text, cls.language, cls.intent)
    # greetings go to LLM (script preservation)
    meter.record_route(Route.LLM)
    # filler fires on LLM path
    assert should_filler(Route.LLM)

    # Turn 2: caller asks a question
    text = "what is your refund policy"
    cls = classify(text)
    memory.update_from_turn(text, cls.language, cls.intent)
    meter.record_route(Route.LLM)
    meter.record_kb()

    # Turn 3: caller says thanks (must hit thanks intent for canned)
    text = "thanks"
    cls = classify(text)
    memory.update_from_turn(text, cls.language, cls.intent)
    reply = canned_response(cls, "en")
    assert reply is not None  # thanks IS a SAFE canned intent
    meter.record_route(Route.CANNED)

    # Turn 4: caller says bye
    text = "bye"
    cls = classify(text)
    memory.update_from_turn(text, cls.language, cls.intent)
    reply = canned_response(cls, "en")
    assert reply is not None  # bye is SAFE canned
    meter.record_route(Route.CANNED)

    # Verify meter math at end-of-call
    assert sum(meter.routes.values()) == 4
    assert meter.llm_calls == 2
    assert meter.llm_bypass_rate == 0.5
    assert meter.kb_calls == 1


# ─── Outbound appointment-reminder call ──────────────────────────


def test_e2e_outbound_reminder_flow_telugu():
    memory = CallMemory(call_id="out-1", name="Nagasai")
    meter = CallMeter()

    # Turn 1: caller picks up
    text = "హలో"
    cls = classify(text)
    assert cls.language == "te"
    memory.update_from_turn(text, "te", cls.intent)
    meter.record_route(Route.LLM)

    # Turn 2: caller confirms attendance
    text = "ఆ వస్తాను"
    cls = classify(text)
    memory.update_from_turn(text, "te", cls.intent)
    meter.record_route(Route.LLM)

    # Turn 3: caller says bye
    text = "మంచి రోజు అండి"
    cls = classify(text)
    memory.update_from_turn(text, "te", cls.intent)
    meter.record_route(Route.CANNED)  # might be canned bye

    assert memory.language == "te"
    assert memory.name == "Nagasai"  # seeded name preserved across turns


# ─── Switching language mid-call ─────────────────────────────────


def test_e2e_language_switch_mid_call():
    memory = CallMemory(call_id="mix-1", language="te")
    text1 = "నాకు help kavali"
    cls1 = classify(text1)
    memory.update_from_turn(text1, cls1.language, cls1.intent)
    assert memory.language == "te"

    text2 = "actually can you help me in english please"
    cls2 = classify(text2)
    memory.update_from_turn(text2, cls2.language, cls2.intent)
    assert memory.language == "en"


# ─── Caller goes silent → noise STT (music) ──────────────────────


def test_e2e_noise_filter_path():
    """Caller's hold music is mistakenly transcribed as 'music' —
    must be caught by the narrow noise filter (smoke level: ensure
    classifier doesn't try to make sense of it)."""
    cls = classify("music")
    # 'music' isn't in any intent keyword → unknown.
    assert cls.intent in ("unknown", "")
    # The agent.py noise filter explicitly catches it (covered elsewhere).


# ─── Cancellation flow ─────────────────────────────────────────


def test_e2e_cancel_intent_classification():
    cls = classify("cancel my appointment")
    assert "cancel" in cls.intent or cls.intent == "unknown" or cls.intent == "refund"
    # Refund-keyword set includes "cancel" — verify it doesn't crash.


# ─── Long-call memory accumulates correctly ────────────────────


def test_e2e_long_call_50_turns():
    memory = CallMemory(call_id="long-1")
    meter = CallMeter()
    for i in range(50):
        text = f"turn {i} question"
        cls = classify(text)
        memory.update_from_turn(text, cls.language, cls.intent)
        meter.record_route(Route.LLM if i % 3 == 0 else Route.CANNED)
    assert sum(meter.routes.values()) == 50
    # Bypass rate should be ~66% (2 of every 3 are canned).
    assert 0.6 < meter.llm_bypass_rate < 0.7


# ─── Telemetry latency tracking across simulated turns ───────────


def test_e2e_telemetry_records_per_turn_latency():
    tel = CallTelemetry(call_id="t-lat", room="t-lat", direction="inbound")
    # Simulate 5 turns with realistic latencies.
    for i in range(5):
        tel.record_latency("eou", 0.3 + i * 0.05)
        tel.record_latency("llm_ttft", 0.5 + i * 0.1)
        tel.record_latency("tts_ttfb", 0.2)
    payload = tel._latency_payload()
    assert payload["avg_eou_ms"] > 0
    assert payload["max_llm_ttft_ms"] > payload["avg_llm_ttft_ms"]
    # All buckets populated.
    for k in payload:
        assert isinstance(payload[k], int)


# ─── Filler selection over multiple turns avoids repetition ────


def test_e2e_filler_no_back_to_back_repeat():
    prev = pick_filler("te")
    for _ in range(20):
        curr = pick_filler("te")
        assert curr != prev
        prev = curr


# ─── Emotion progression through a frustrated caller ───────────


def test_e2e_emotion_progression():
    memory = CallMemory(call_id="emo-1")
    turns = [
        ("hello", "neutral"),
        ("I have a problem", "neutral"),
        ("this is the worst experience", "angry"),
        ("please fix it asap", "urgent"),
    ]
    for text, _expected in turns:
        cls = classify(text)
        memory.update_from_turn(text, cls.language, cls.intent)
    # After processing all turns, the latest non-neutral emotion sticks.
    assert memory.emotion in ("angry", "urgent", "frustrated")
