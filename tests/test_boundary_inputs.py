"""Boundary / negative input tests — empty, very long, malformed.

Production voice agents receive every kind of garbage transcript: empty
strings, 10,000-char hallucinated streams, raw control characters,
emoji-only turns. None should crash a live call."""

from __future__ import annotations

from src.router.classifier import detect_language, classify
from src.memory import detect_emotion, extract_name, CallMemory
from src.cache import _entry_id, ns_for
from src.audio import _norm, EchoGuard
from src.cost import trim_history
from src.filler import pick_filler
from src.pipeline.stabilizer import TranscriptStabilizer
from src.db import norm_time, resolve_date


# ─── Empty inputs ─────────────────────────────────────────────────


def test_classify_empty_does_not_crash():
    c = classify("")
    assert c.intent in ("unknown", "")
    assert c.language == "en"


def test_classify_whitespace_only():
    c = classify("   \t\n  ")
    assert isinstance(c.language, str)


def test_detect_emotion_empty():
    assert detect_emotion("") == "neutral"


def test_extract_name_empty():
    assert extract_name("") is None


def test_entry_id_empty_query_stable():
    # Even empty string must produce a stable hash, not crash.
    h = _entry_id("")
    assert isinstance(h, str) and len(h) == 20


def test_norm_empty_returns_empty():
    assert _norm("") == ""


def test_norm_time_empty():
    assert norm_time("") is None


def test_resolve_date_empty():
    assert resolve_date("") is None


def test_pick_filler_unknown_lang_does_not_crash():
    assert isinstance(pick_filler(""), str)
    assert isinstance(pick_filler("xx-XX"), str)


# ─── Very long inputs ─────────────────────────────────────────────


def test_classify_handles_10k_chars():
    """A hallucinated STT stream could be very long. Must not hang."""
    long = "what is my order " * 1000
    c = classify(long)
    assert isinstance(c.language, str)


def test_norm_handles_10k_chars():
    long = "Hello world, how are you? " * 500
    out = _norm(long)
    assert isinstance(out, str)


def test_entry_id_long_query_still_20_chars():
    long = "a" * 5000
    h = _entry_id(long)
    assert len(h) == 20


def test_extract_name_long_input_no_match():
    long = "x" * 1000 + " my name is Rahul " + "y" * 1000
    # Despite the noise, name must be captured.
    assert extract_name(long) == "Rahul"


# ─── Malformed / control characters ──────────────────────────────


def test_classify_handles_null_bytes():
    """STT shouldn't emit null bytes, but defensive code should not crash."""
    c = classify("hello\x00world")
    assert isinstance(c.language, str)


def test_norm_handles_control_chars():
    out = _norm("hello\x01\x02world")
    assert isinstance(out, str)


def test_detect_language_handles_emoji_only():
    """Pure-emoji turn from STT mishears. Should default to English."""
    assert detect_language("😀😀😀") == "en"


def test_classify_handles_emoji_mixed():
    c = classify("hello 😀 world")
    assert isinstance(c.intent, str)


# ─── Numerical edge cases ────────────────────────────────────────


def test_norm_time_handles_hour_24():
    """24-hour wraparound should snap to midnight or return None."""
    # 24:00 is invalid (must be 00:00 next day) — but in our domain
    # we return None for out-of-window.
    out = norm_time("24:00")
    assert out is None or out in ("00:00",)


def test_norm_time_handles_decimal():
    # "5.30" sometimes parsed as 5:30
    out = norm_time("5.30 pm")
    assert out is None or out.startswith("17") or out.startswith("05")


def test_trim_history_with_huge_max_turns():
    """If memoryMaxTurns is set to 1000, we don't crash with a giant slice."""
    msgs = [type("M", (), {"role": "user", "content": "x"})() for _ in range(100)]
    out = trim_history(msgs, max_turns=10000)
    # Returns the full list (no system messages to preserve).
    assert len(out) == 100


def test_trim_history_negative_max_turns():
    """Negative max_turns must NOT explode — defensive."""
    msgs = [
        type("M", (), {"role": "system", "content": "p"})(),
        type("M", (), {"role": "user", "content": "u"})(),
    ]
    out = trim_history(msgs, max_turns=-5)
    # Should return only system messages (treat negative as 0).
    assert all(getattr(m, "role", None) == "system" for m in out)


# ─── Stabilizer with pathological input ──────────────────────────


def test_stabilizer_huge_word_count():
    """STT hallucinated 1000-word transcript — must not OOM/slow."""
    s = TranscriptStabilizer(min_stable_partials=2, debounce_seconds=0.0)
    huge = " ".join(["word"] * 1000)
    s.push(huge, now=1.0)
    s.push(huge, now=1.1)
    # Should stabilize the whole thing.
    assert "word" in s.stable_text


def test_stabilizer_unicode_safety():
    s = TranscriptStabilizer(min_stable_partials=2, debounce_seconds=0.0)
    s.push("మంచి రోజు", now=1.0)
    s.push("మంచి రోజు", now=1.1)
    assert "మంచి" in s.stable_text


# ─── Echo guard with extreme input ───────────────────────────────


def test_echo_guard_huge_utterance():
    eg = EchoGuard()
    huge = "abc " * 500
    eg.on_agent_started(huge)
    assert eg.is_echo(huge) is True


def test_echo_guard_empty_after_started():
    eg = EchoGuard()
    eg.on_agent_started("hello")
    # Empty caller text is NOT echo.
    assert eg.is_echo("") is False


# ─── Negative confidence / nonsense inputs ──────────────────────


def test_call_memory_with_nonsense_emotion():
    """If detect_emotion returns garbage (shouldn't, but defensive)
    the memory should accept it without crashing."""
    m = CallMemory(call_id="c1")
    m.update_from_turn("test", "te", "unknown")
    # emotion stays whatever detect_emotion returned for "test" (likely neutral)
    assert m.emotion in ("neutral", "angry", "frustrated", "urgent",
                          "confused", "happy")
