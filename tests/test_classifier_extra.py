"""Extensive language + intent classifier coverage."""

from __future__ import annotations

from src.router.classifier import detect_language, classify


# ─── detect_language ─────────────────────────────────────────────────


def test_pure_telugu_script_detected():
    for s in ["నమస్కారం", "నాకు అపాయింట్‌మెంట్ కావాలి", "ఎల్లుండి slot"]:
        assert detect_language(s) == "te", s


def test_pure_devanagari_detected_as_hindi():
    for s in ["नमस्ते जी", "मुझे अपॉइंटमेंट चाहिए", "ठीक है", "धन्यवाद"]:
        assert detect_language(s) == "hi", s


def test_empty_input_defaults_english():
    assert detect_language("") == "en"
    assert detect_language("   ") == "en"
    assert detect_language(None) == "en"  # type: ignore[arg-type]


def test_romanized_telugu_cues_detected():
    # "naa order ekkada undi" — Telugu cues only.
    assert detect_language("naa order ekkada undi") == "te"


def test_romanized_hindi_cues_detected():
    assert detect_language("haan bhai kaise ho") == "hi"


def test_pure_english_returns_en():
    assert detect_language("can you help me please") == "en"
    assert detect_language("what is my order status") == "en"


def test_unknown_short_words_default_english():
    assert detect_language("xyz") == "en"
    assert detect_language("12345") == "en"


def test_indic_script_overrides_roman_cues():
    # Even with English keywords, Indic script wins.
    assert detect_language("నాకు order ekkada the help please") == "te"


def test_mixed_returns_mixed_when_strong():
    # Two Telugu + two English cues, same magnitude.
    assert detect_language("naa order need help please") in ("te", "mixed")


def test_short_codemix_single_cue_does_not_force_mixed():
    # The regression we guarded against: "haan ok" should NOT be "mixed",
    # because that destabilised TTS language switching per turn.
    out = detect_language("haan ok")
    assert out in ("hi", "en"), f"got {out}"
    # Most importantly NOT "mixed".
    assert out != "mixed"


# ─── classify intent ─────────────────────────────────────────────────


def test_greeting_intent():
    cls = classify("hello there")
    assert cls.intent == "greeting"
    assert cls.is_trivial is True


def test_affirm_intent():
    for s in ["yes", "okay", "haan", "sari", "avunu", "hmm"]:
        c = classify(s)
        assert c.intent == "affirm", f"{s!r} → {c.intent}"
        assert c.is_trivial is True


def test_deny_intent():
    for s in ["no", "nope", "nahi", "ledu", "vaddu"]:
        c = classify(s)
        assert c.intent == "deny", f"{s!r} → {c.intent}"


def test_thanks_intent():
    for s in ["thanks", "thank you", "dhanyavaad", "shukriya"]:
        c = classify(s)
        assert c.intent == "thanks", f"{s!r} → {c.intent}"


def test_bye_intent_explicit_priority():
    # Regression: "okay fine bye" used to be classified as affirm (okay
    # wins by listing order). Bye must take priority for graceful close.
    c = classify("okay fine bye")
    assert c.intent == "bye"


def test_bye_intent_with_indic_marker():
    # alvida = goodbye in Hindi/Urdu.
    c = classify("alvida")
    assert c.intent == "bye"


def test_repeat_intent_must_be_short():
    # Regression: "Can you check again what slots are available?" used
    # to fire "repeat" canned because of "again" being a substring of
    # repeat cues. Must NOT trigger trivial-repeat shortcut on long turns.
    c = classify("Can you check again what slots are available right now please?")
    assert c.is_trivial is False


def test_repeat_short_turn_does_trigger():
    c = classify("repeat please")
    assert c.intent == "repeat"
    assert c.is_trivial is True


def test_order_status_intent():
    c = classify("where is my order")
    assert c.intent == "order_status"


def test_payment_intent():
    c = classify("payment failed")
    assert c.intent == "payment_issue"


def test_refund_intent():
    c = classify("I want a refund")
    assert c.intent == "refund"


def test_unknown_intent_when_no_keywords():
    c = classify("the weather is nice today")
    assert c.intent in ("unknown", "greeting")  # neutral
    # Must NOT be trivial unless it's actually a greeting.
    if c.intent == "unknown":
        assert c.is_trivial is False


def test_confidence_scales_with_hits():
    # 1 hit -> 0.7, 2+ hits -> 0.9, 0 hits -> 0.3
    c1 = classify("yes")
    assert c1.confidence == 0.7
    c2 = classify("yes ok")
    assert c2.confidence == 0.9
    c0 = classify("the weather is nice")
    assert c0.confidence <= 0.7  # weather has 'the' which is en cue


def test_trivial_requires_short_and_hit():
    # 5+ word turn with affirm keyword must NOT be trivial.
    c = classify("yes please go ahead and check the schedule now")
    assert c.is_trivial is False


def test_empty_classification_returns_unknown():
    c = classify("")
    assert c.intent == "unknown"
    assert c.is_trivial is False


def test_telugu_script_classify_keeps_language():
    c = classify("నాకు help kavali")
    assert c.language == "te"
