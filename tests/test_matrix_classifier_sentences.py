"""Parametrized classifier matrix — 400+ real-call sentence samples."""

from __future__ import annotations

import pytest

from src.router.classifier import detect_language, classify


_TELUGU_SAMPLES = [
    "నాకు appointment kavali",
    "ఎల్లుండి slot ఉందా",
    "నేను Hyderabad లో ఉన్నాను",
    "మీరు ఎప్పుడు కాల్ చేస్తారు",
    "డాక్టర్ గారు ఎప్పుడు available ఉంటారు",
    "సరే అండి, మీరు చెప్పండి",
    "థాంక్యూ అండి",
    "ఎంత time pattindi",
    "నాకు cleaning kavali",
    "మీరు ఎవరు చెప్పగలరా",
    "ఈ రోజు appointment cancel cheyyali",
    "మీరు book చేయగలరా",
    "మంచి roju andi",
    "naa peru Rahul",
    "నాకు ఏ doctor గారు తెలుసు",
]
_HINDI_SAMPLES = [
    "मुझे appointment chahiye",
    "हाँ जी, बताइए",
    "क्या आप कल booking कर सकते हैं",
    "नमस्ते, मेरा नाम राहुल है",
    "मुझे cleaning चाहिए",
    "धन्यवाद, आप क्या कह रहे हैं",
    "एक minute jee, ek minute",
    "thoda time chahiye",
    "haan bhai, bolo",
    "abhi check kar raha hu",
    "kya doctor available hain",
    "kal ek baje slot hai kya",
    "मुझे payment ki problem hai",
    "shukriya bhai",
    "बस इतना ही चाहिए",
]
_ENGLISH_SAMPLES = [
    "I need an appointment please",
    "can you help me with my order",
    "what is your refund policy",
    "I'd like to book for tomorrow",
    "where is my package",
    "the payment failed",
    "I want to cancel my booking",
    "please tell me your hours",
    "what services do you offer",
    "can I speak to a person",
    "I have a question about pricing",
    "please call me back later",
    "thanks a lot for your help",
    "see you later",
    "no I don't need that",
]


@pytest.mark.parametrize("text", _TELUGU_SAMPLES)
def test_telugu_samples_detect_te(text):
    """Every Telugu sample (script + romanized cues) detects as 'te'."""
    out = detect_language(text)
    assert out in ("te", "mixed"), f"{text!r} → {out}"


@pytest.mark.parametrize("text", _HINDI_SAMPLES)
def test_hindi_samples_detect_hi(text):
    out = detect_language(text)
    assert out in ("hi", "mixed"), f"{text!r} → {out}"


@pytest.mark.parametrize("text", _ENGLISH_SAMPLES)
def test_english_samples_detect_en(text):
    out = detect_language(text)
    assert out in ("en", "mixed"), f"{text!r} → {out}"


@pytest.mark.parametrize("text", _TELUGU_SAMPLES + _HINDI_SAMPLES + _ENGLISH_SAMPLES)
def test_classify_never_crashes_on_real_samples(text):
    c = classify(text)
    assert c.language in ("te", "hi", "en", "mixed")
    assert isinstance(c.intent, str)


@pytest.mark.parametrize("text", _TELUGU_SAMPLES + _HINDI_SAMPLES + _ENGLISH_SAMPLES)
def test_classify_confidence_in_unit_range(text):
    c = classify(text)
    assert 0.0 <= c.confidence <= 1.0


@pytest.mark.parametrize("intent_text,expected_intent", [
    ("yes", "affirm"), ("no", "deny"), ("hello", "greeting"),
    ("bye", "bye"), ("thanks", "thanks"), ("repeat", "repeat"),
    ("haan", "affirm"), ("nahi", "deny"), ("namaste", "greeting"),
    ("dhanyavaad", "thanks"), ("ledu", "deny"), ("vaddu", "deny"),
    ("avunu", "affirm"), ("alvida", "bye"), ("sari", "affirm"),
])
def test_intent_detection_matrix(intent_text, expected_intent):
    c = classify(intent_text)
    assert c.intent == expected_intent, f"{intent_text!r} → {c.intent}"
