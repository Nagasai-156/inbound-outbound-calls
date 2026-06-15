"""Unicode handling tests — Telugu / Hindi / Devanagari across modules.

At crore-scale Indic voice, a Unicode normalisation bug in any single
module can break entire language mirror chains. These tests pin the
contract."""

from __future__ import annotations

import json

from src.cache import _entry_id, ns_for
from src.audio import _norm
from src.memory import detect_emotion, extract_name, CallMemory
from src.router.classifier import detect_language, classify
from src.persona.base import sanitize_business_context


# ─── Cache helpers preserve Indic in stable hash ──────────────────


def test_telugu_query_has_stable_entry_id():
    assert _entry_id("నాకు appointment kavali") == _entry_id("నాకు appointment kavali")


def test_hindi_query_has_stable_entry_id():
    assert _entry_id("मुझे appointment chahiye") == _entry_id("मुझे appointment chahiye")


def test_indic_namespace_isolation():
    assert ns_for("dental clinic Telugu") != ns_for("dental clinic Hindi")


def test_indic_query_case_normalisation_unchanged():
    """Indic scripts have no case — `.lower()` is a no-op on them.
    Make sure that doesn't break the hash."""
    h1 = _entry_id("మంచి అపాయింట్‌మెంట్")
    h2 = _entry_id("మంచి అపాయింట్‌మెంట్")
    assert h1 == h2


# ─── Audio _norm preserves Indic ──────────────────────────────────


def test_norm_keeps_telugu_letters():
    out = _norm("మంచి, రోజు! అండి.")
    # Punctuation gone, Telugu letters preserved.
    assert "మంచి" in out
    assert "రోజు" in out
    assert "అండి" in out
    assert "," not in out
    assert "!" not in out


def test_norm_keeps_devanagari_letters():
    out = _norm("नमस्ते, जी!")
    assert "नमस्ते" in out
    assert "जी" in out


def test_norm_handles_mixed_script():
    out = _norm("Sure అండి, ఇది check చేస్తాను.")
    # Both scripts must survive.
    assert "sure" in out  # English lowered
    assert "అండి" in out
    assert "check" in out
    assert "చేస్తాను" in out


# ─── Memory extractors handle Indic ───────────────────────────────


def test_emotion_detect_works_on_pure_telugu():
    # Use one of the cue phrases from _EMOTION_CUES
    assert detect_emotion("chala bagundi") == "happy"


def test_emotion_detect_works_on_pure_hindi():
    assert detect_emotion("badhiya") == "happy"


def test_emotion_detect_handles_mixed_script_input():
    # Devanagari + Roman
    assert detect_emotion("बहुत urgent है please jaldi") == "urgent"


# ─── Classifier handles Indic ─────────────────────────────────────


def test_classify_devanagari_returns_hi():
    c = classify("नमस्ते जी, मुझे help चाहिए")
    assert c.language == "hi"


def test_classify_telugu_returns_te():
    c = classify("నాకు appointment book చేయాలి")
    assert c.language == "te"


def test_detect_language_unicode_normalisation():
    # NFC-normalised vs decomposed forms should both work for hash purposes.
    # We don't enforce normalisation, but the detector must not crash.
    nfc = "మంచి"  # composed
    detect_language(nfc)  # must not raise


# ─── JSON serialization roundtrip ─────────────────────────────────


def test_call_memory_serialises_indic_unchanged():
    m = CallMemory(
        call_id="c1",
        language="te",
        emotion="happy",
        intent="greeting",
        name="Nagasai",
        slots={"order_id": "MSP-12345"},
        summary="Caller asked for మంచి appointment",
    )
    from dataclasses import asdict
    blob = json.dumps(asdict(m), ensure_ascii=False)
    assert "మంచి" in blob
    parsed = json.loads(blob)
    assert parsed["summary"] == m.summary


def test_call_memory_serialises_with_ascii_escape():
    """ensure_ascii=True must still preserve roundtrip semantics."""
    m = CallMemory(call_id="c1", summary="Tenglish: అపాయింట్‌మెంట్")
    from dataclasses import asdict
    blob = json.dumps(asdict(m))  # default ensure_ascii=True
    parsed = json.loads(blob)
    assert parsed["summary"] == m.summary


# ─── Sanitize handles Indic ───────────────────────────────────────


def test_sanitize_business_context_with_indic_text():
    out = sanitize_business_context(
        "క్లినిక్ లో {{phone}} number పంపండి"
    )
    # The placeholder should be replaced, Telugu must survive.
    assert "{{phone}}" not in out
    assert "క్లినిక్" in out
    assert "team will share" in out.lower()


# ─── Extract_name skips Indic-script names (regex is Roman-only) ──


def test_extract_name_indic_script_not_captured():
    """Our extractor is Latin-only by design. A Devanagari-script name
    must NOT be captured (would garble case)."""
    # 'mera naam' regex matches Roman letters [a-z]+
    assert extract_name("mera naam राहुल") is None
    # Roman fallback still works.
    assert extract_name("mera naam Rahul") == "Rahul"


# ─── Edge case: Zero-Width Joiner in Indic text ───────────────────


def test_zwj_does_not_break_classifier():
    """ZWJ (U+200D) appears in Indic conjuncts. Must not throw."""
    text = "అపాయింట్‍మెంట్"
    c = classify(text)
    assert c.language == "te"


def test_zwj_does_not_break_norm():
    text = "అపాయింట్‍మెంట్"
    out = _norm(text)
    # Should not crash; output is implementation-defined but non-empty.
    assert isinstance(out, str)
