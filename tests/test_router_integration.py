"""Router integration tests — classifier + canned + meter together.

Each unit has its own coverage; this verifies the full triage chain
behaves correctly when composed."""

from __future__ import annotations

from src.router.classifier import classify, Classification
from src.router.canned import canned_response
from src.router.intent_router import Route
from src.cost import CallMeter


def test_canned_greeting_does_NOT_short_circuit_to_canned():
    """Regression: greeting was never safe-canned because a generic
    "Hello sir" overrides script. Even if classifier says trivial,
    canned_response must return None for greeting."""
    cls = classify("hello")
    reply = canned_response(cls, call_language="en")
    assert reply is None


def test_canned_bye_returns_response():
    cls = classify("ok bye")
    reply = canned_response(cls, call_language="en")
    # bye IS in _SAFE_CANNED_INTENTS, must return a canned line.
    assert reply is not None and len(reply) > 0


def test_canned_thanks_returns_response():
    cls = classify("thanks a lot")
    reply = canned_response(cls, call_language="en")
    assert reply is not None


def test_canned_repeat_returns_response():
    cls = classify("repeat please")
    reply = canned_response(cls, call_language="en")
    assert reply is not None


def test_canned_uses_call_language_not_classifier():
    """If the call is in Telugu but the trivial line is Roman ("bye"),
    response MUST be in Telugu (call_language wins)."""
    cls = classify("bye")
    te_reply = canned_response(cls, call_language="te")
    en_reply = canned_response(cls, call_language="en")
    assert te_reply != en_reply
    # Telugu reply should contain Telugu chars.
    has_te = any(0x0C00 <= ord(c) <= 0x0C7F for c in (te_reply or ""))
    assert has_te, f"Telugu reply lacks Telugu chars: {te_reply!r}"


def test_full_meter_accumulates_across_route_mix():
    """Realistic call: greeting (LLM) + 2× canned + cache hit + 1× LLM."""
    m = CallMeter()
    m.record_route(Route.LLM)       # greeting -> LLM (script)
    m.record_route(Route.CANNED)    # affirm/bye
    m.record_route(Route.CANNED)
    m.record_route(Route.CACHE)     # FAQ hit
    m.record_route(Route.LLM)       # one real LLM call
    assert sum(m.routes.values()) == 5
    assert m.llm_calls == 2
    # 5 turns, 2 LLM → 60% bypass.
    assert abs(m.llm_bypass_rate - 0.6) < 1e-9


def test_unknown_intent_falls_through_to_llm():
    """A novel question must NOT be canned — classifier returns
    is_trivial=False; canned must skip."""
    cls = classify("can you tell me the procedure for crown installation?")
    assert cls.is_trivial is False
    reply = canned_response(cls, call_language="en")
    assert reply is None


def test_canned_handles_None_language_gracefully():
    cls = classify("bye")
    # None call_language should fall back to classifier language.
    reply = canned_response(cls, call_language=None)
    assert reply is not None


def test_trivial_class_with_unknown_intent_does_not_canned():
    """Manual classification with bogus intent must not crash canned."""
    cls = Classification(language="en", intent="unknown", is_trivial=True, confidence=0.5)
    reply = canned_response(cls, call_language="en")
    assert reply is None


def test_canned_telugu_response_has_native_script():
    cls = classify("bye")
    reply = canned_response(cls, call_language="te")
    assert reply
    has_te = any(0x0C00 <= ord(c) <= 0x0C7F for c in reply)
    assert has_te


def test_canned_hindi_response_has_devanagari():
    cls = classify("bye")
    reply = canned_response(cls, call_language="hi")
    assert reply
    has_hi = any(0x0900 <= ord(c) <= 0x097F for c in reply)
    assert has_hi
