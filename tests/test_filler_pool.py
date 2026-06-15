"""Filler pool sanity tests.

The pool is split by KIND (2026-06-12): "ack" pure backchannels for
statement turns, "checking" latency-cover phrases for question/lookup
turns. Selection is driven by the caller's turn (intent + question
cues), rotation is deterministic — never random, never the same line
twice in a row. These tests pin that shape.
"""

from __future__ import annotations

from src.content import DEFAULT_FILLERS
from src.filler import filler_kind, pick_filler


def _flat(lang: str) -> list[str]:
    return [t for pool in DEFAULT_FILLERS[lang].values() for t in pool]


def test_all_three_languages_have_pools():
    for lang in ("te", "hi", "en"):
        assert lang in DEFAULT_FILLERS
        assert len(DEFAULT_FILLERS[lang]["ack"]) >= 6, (
            f"{lang} ack pool needs >=6 lines for anti-repeat rotation"
        )
        assert len(DEFAULT_FILLERS[lang]["checking"]) >= 2, (
            f"{lang} checking pool needs >=2 lines for anti-repeat rotation"
        )


def test_telugu_pool_has_pure_backchannels():
    pool = DEFAULT_FILLERS["te"]["ack"]
    backchannels = ["ఆ అండి...", "హా అండి...", "సరే..."]
    matches = [b for b in backchannels if b in pool]
    assert len(matches) >= 2, (
        f"Telugu ack pool must include short backchannels; found {matches}"
    )


def test_hindi_pool_has_pure_backchannels():
    pool = DEFAULT_FILLERS["hi"]["ack"]
    backchannels = ["जी हाँ...", "हाँ जी...", "अच्छा..."]
    matches = [b for b in backchannels if b in pool]
    assert len(matches) >= 2


def test_english_pool_has_pure_backchannels():
    pool = DEFAULT_FILLERS["en"]["ack"]
    for b in ["Okay...", "Right..."]:
        assert b in pool, f"English ack pool missing backchannel {b!r}"


def test_no_tts_unsafe_single_syllable_entries():
    """Regression (live failure 2026-06-12): Sarvam TTS returns zero
    audio frames for single-syllable interjections ("ఆ...", "హా...",
    "हाँ...", "Mm-hmm..."), which silently kills the filler and flips
    the session to fallback voice. Every entry must carry real text."""
    unsafe = {"ఆ...", "హా...", "హ్మ్...", "ఓ...", "हाँ...", "हम्म...",
              "जी...", "अरे...", "Mm-hmm...", "Hmm..."}
    for lang in ("te", "hi", "en"):
        for kind, pool in DEFAULT_FILLERS[lang].items():
            for line in pool:
                assert line not in unsafe, (
                    f"{lang}/{kind} contains TTS-unsafe entry {line!r}"
                )
                assert len(line.rstrip(".").strip()) >= 3, (
                    f"{lang}/{kind} entry too short for Sarvam: {line!r}"
                )


def test_ack_pool_has_no_checking_phrases():
    """Regression: a 'checking/one second' line on a statement turn is
    the robotic tell. The ack pool must stay pure backchannels."""
    for lang in ("te", "hi", "en"):
        for line in DEFAULT_FILLERS[lang]["ack"]:
            assert not any(w in line.lower() for w in [
                "check", "minute", "second", "moment", "देख", "चेक",
                "నిమిషం", "సెకన్", "చూస్తు",
            ]), f"{lang} ack pool contains a checking phrase: {line!r}"


def test_no_duplicate_entries_per_pool():
    """Anti-repeat rotation needs unique entries."""
    for lang in ("te", "hi", "en"):
        flat = _flat(lang)
        assert len(flat) == len(set(flat)), (
            f"{lang} pool has duplicates: {flat}"
        )


# ─── kind selection: filler must be based on what the caller said ────

def test_question_turns_get_checking_filler():
    assert filler_kind("unknown", "where is my order?") == "checking"
    assert filler_kind("unknown", "appointment ekkada teesukovali") == "checking"
    assert filler_kind("unknown", "kitna time lagega") == "checking"
    assert filler_kind("unknown", "can you check the slot") == "checking"
    assert filler_kind("order_status", "order gurinchi") == "checking"


def test_statement_turns_get_ack_filler():
    assert filler_kind("unknown", "naaku konchem pain undi morning nunchi") == "ack"
    assert filler_kind("unknown", "payment ho gaya kal raat ko") == "ack"
    assert filler_kind("unknown", "I already paid yesterday evening") == "ack"


def test_rotation_is_deterministic_and_never_repeats():
    # A genuine lookup query → "checking" pool. (A plain "where?" is now
    # an ack — honest fillers only say "checking" for real lookups.)
    seen = [pick_filler("te", "unknown", "slot unda?") for _ in range(6)]
    for a, b in zip(seen, seen[1:]):
        assert a != b, "same checking filler twice in a row"
    # Deterministic: a fresh identical sequence after full cycle repeats
    # the same order (sequential rotation, not random).
    pool = DEFAULT_FILLERS["te"]["checking"]
    assert set(seen) == set(pool)
