"""Memory: emotion + name extraction tests.

These pure-function extractors run on every turn — wrong output drives
the rhythm engine, the persona's emotional tone, and the caller-name
that subsequent turns reference. Coverage here matters."""

from __future__ import annotations

from src.memory import detect_emotion, extract_name, CallMemory


# ─── detect_emotion ─────────────────────────────────────────────────


def test_angry_emotion():
    for s in ["this is the worst", "useless service", "what a scam"]:
        assert detect_emotion(s) == "angry", s


def test_frustrated_emotion():
    for s in ["I called again", "still not working", "marokkasari try chesta"]:
        assert detect_emotion(s) == "frustrated", s


def test_urgent_emotion():
    for s in ["this is urgent", "I need it ASAP", "jaldi karo"]:
        assert detect_emotion(s) == "urgent", s


def test_confused_emotion():
    for s in ["samajh nahi aya", "what do you mean", "ardham kaledu"]:
        assert detect_emotion(s) == "confused", s


def test_happy_emotion():
    for s in ["thank you so much", "this is great", "chala bagundi"]:
        assert detect_emotion(s) == "happy", s


def test_neutral_when_no_cues():
    for s in ["what is my order id", "book an appointment", "12345"]:
        assert detect_emotion(s) == "neutral", s


def test_emotion_case_insensitive():
    assert detect_emotion("WORST EXPERIENCE") == "angry"


def test_emotion_handles_empty():
    assert detect_emotion("") == "neutral"
    assert detect_emotion(None) == "neutral"


# ─── extract_name ──────────────────────────────────────────────────


def test_extract_name_english():
    assert extract_name("my name is Rahul") == "Rahul"
    assert extract_name("My Name Is amit") == "Amit"  # title-cased


def test_extract_name_telugu_romanised():
    assert extract_name("naa peru Suresh") == "Suresh"
    assert extract_name("naa peeru ravi") == "Ravi"


def test_extract_name_hindi():
    assert extract_name("mera naam hai Vikram") == "Vikram"
    assert extract_name("mera naam Akash") == "Akash"


def test_extract_name_no_match_returns_none():
    """Regression: 'I am suffering' / 'main problem' / 'I am here' used
    to be captured as names. Self-introductions ALWAYS use an explicit
    name-marker; the regex was deliberately tightened."""
    for s in [
        "I am suffering",
        "I am here",
        "main problem hai",
        "I have a question",
        "nothing to say",
    ]:
        assert extract_name(s) is None, f"{s!r} should not capture a name"


def test_extract_name_handles_empty():
    assert extract_name("") is None
    assert extract_name(None) is None


def test_extract_name_strips_trailing_punctuation():
    """Name capture should land on the bare name word."""
    name = extract_name("my name is Rahul, nice to meet you")
    assert name == "Rahul"


# ─── CallMemory.update_from_turn ───────────────────────────────────


def test_update_from_turn_changes_language():
    m = CallMemory(call_id="t1", language="en")
    m.update_from_turn("hi there", "te", "greeting")
    assert m.language == "te"


def test_update_from_turn_changes_intent():
    m = CallMemory(call_id="t1")
    m.update_from_turn("where is my order", "en", "order_status")
    assert m.intent == "order_status"


def test_update_from_turn_captures_emotion():
    m = CallMemory(call_id="t1")
    m.update_from_turn("this is the worst", "en", "complaint")
    assert m.emotion == "angry"


def test_update_from_turn_does_not_clobber_seeded_name():
    """Campaign-seeded name (Nagasai from outbound metadata) must NOT
    be overwritten by a mid-call false positive."""
    m = CallMemory(call_id="t1", name="Nagasai")
    m.update_from_turn("my name is Rahul", "en", "greeting")
    # First explicit name wins (the seeded one).
    assert m.name == "Nagasai"


def test_update_from_turn_captures_first_name_when_unseeded():
    m = CallMemory(call_id="t1")
    m.update_from_turn("my name is Priya", "en", "greeting")
    assert m.name == "Priya"


def test_update_from_turn_keeps_neutral_emotion_default():
    m = CallMemory(call_id="t1")
    m.update_from_turn("12345", "en", "unknown")
    assert m.emotion == "neutral"
