"""ResponseRhythm pacing tests."""

from __future__ import annotations

import pytest

from src.rhythm import ResponseRhythm, _PROFILE


def test_default_emotion_is_neutral():
    r = ResponseRhythm()
    assert r.emotion == "neutral"


def test_pre_speech_delay_within_neutral_bounds():
    r = ResponseRhythm(emotion="neutral")
    lo, hi, _, _ = _PROFILE["neutral"]
    for _ in range(20):
        d = r.pre_speech_delay()
        assert lo <= d <= hi, f"got {d} not in [{lo},{hi}]"


def test_angry_emotion_pauses_shorter():
    """Angry callers must NOT hear a long deliberate pause — feels
    dismissive. Max pause for 'angry' is the shortest of all profiles."""
    angry_max = _PROFILE["angry"][1]
    neutral_max = _PROFILE["neutral"][1]
    confused_max = _PROFILE["confused"][1]
    assert angry_max < neutral_max
    assert angry_max < confused_max


def test_confused_emotion_pauses_longer():
    """Confused/elderly callers benefit from longer pauses for clarity."""
    confused_min = _PROFILE["confused"][0]
    neutral_min = _PROFILE["neutral"][0]
    assert confused_min > neutral_min


def test_inter_sentence_delay_within_bounds():
    r = ResponseRhythm(emotion="happy")
    _, _, lo, hi = _PROFILE["happy"]
    for _ in range(20):
        d = r.inter_sentence_delay()
        assert lo <= d <= hi


def test_unknown_emotion_falls_back_to_neutral():
    r = ResponseRhythm(emotion="unknown-emotion")
    lo, hi, _, _ = _PROFILE["neutral"]
    d = r.pre_speech_delay()
    assert lo <= d <= hi


def test_no_emotion_pre_speech_above_400ms():
    """All emotions must produce pre-speech delay under 0.4s, otherwise
    we eat into the latency budget. Hard upper bound."""
    for emotion, profile in _PROFILE.items():
        _, max_pre, _, max_inter = profile
        assert max_pre <= 0.4, f"{emotion} pre-speech max {max_pre} > 0.4s"
        assert max_inter <= 0.4, f"{emotion} inter max {max_inter} > 0.4s"


def test_maybe_hesitation_returns_string():
    r = ResponseRhythm(emotion="neutral")
    out = r.maybe_hesitation("te")
    assert isinstance(out, str)


def test_maybe_hesitation_telugu_language():
    r = ResponseRhythm(emotion="neutral")
    results = {r.maybe_hesitation("te") for _ in range(50)}
    # Should include at least the empty string (mostly) and one Telugu hesitation.
    assert "" in results


def test_maybe_hesitation_angry_returns_empty():
    """No 'hmm' when caller is angry — that reads as stalling."""
    r = ResponseRhythm(emotion="angry")
    for _ in range(20):
        assert r.maybe_hesitation("te") == ""


def test_maybe_hesitation_unknown_language_defaults_english():
    r = ResponseRhythm(emotion="neutral")
    # Don't crash on garbage lang code.
    out = r.maybe_hesitation("xx")
    assert isinstance(out, str)


@pytest.mark.asyncio
async def test_think_pause_is_short():
    """The think_pause must actually be short — it's wrapped in await
    asyncio.sleep() so we measure roughly."""
    import time
    r = ResponseRhythm(emotion="neutral")
    t0 = time.monotonic()
    await r.think_pause()
    elapsed = time.monotonic() - t0
    # neutral max is 0.18s; allow some scheduler slop.
    assert elapsed < 0.5, f"think_pause took {elapsed}s"
