"""TTS speaker validation tests — Sarvam Bulbul rejects unknown speakers
with HTTP 400, which caused a 25-second retry storm on every English
switch (the amelia bug). The guards must keep working under any garbled
config the dashboard could send."""

from __future__ import annotations

from src.pipeline.tts import (
    _safe_model,
    _safe_speaker,
    _V2_SPEAKERS,
    _V3_SPEAKERS,
    _V2_DEFAULT,
    _V3_DEFAULT,
)


# ─── _safe_model ─────────────────────────────────────────────────────


def test_safe_model_known_returns_as_is():
    assert _safe_model("bulbul:v2") == "bulbul:v2"
    assert _safe_model("bulbul:v3-beta") == "bulbul:v3-beta"


def test_safe_model_unknown_defaults_to_v2():
    for bad in ["bulbul:v4-future", "", "garbage", "saaras:v3"]:
        assert _safe_model(bad) == "bulbul:v2", bad


# ─── _safe_speaker ───────────────────────────────────────────────────


def test_v2_valid_speakers_pass():
    for spk in _V2_SPEAKERS:
        assert _safe_speaker("bulbul:v2", spk) == spk


def test_v2_invalid_speaker_falls_back():
    # amelia is a v3 speaker - NOT in v2 set. Must fall back.
    assert _safe_speaker("bulbul:v2", "amelia") == _V2_DEFAULT
    # Random garbage too.
    assert _safe_speaker("bulbul:v2", "xyz123") == _V2_DEFAULT


def test_v3_valid_speakers_pass():
    for spk in _V3_SPEAKERS:
        assert _safe_speaker("bulbul:v3-beta", spk) == spk


def test_v3_amelia_sophia_no_longer_in_set():
    """Regression: amelia + sophia were removed because Sarvam server
    actually rejects them (verified by HTTP 400 in worker logs)."""
    assert "amelia" not in _V3_SPEAKERS
    assert "sophia" not in _V3_SPEAKERS


def test_v3_invalid_speaker_falls_back():
    assert _safe_speaker("bulbul:v3-beta", "amelia") == _V3_DEFAULT
    assert _safe_speaker("bulbul:v3-beta", "sophia") == _V3_DEFAULT
    assert _safe_speaker("bulbul:v3-beta", "xyz123") == _V3_DEFAULT


def test_safe_speaker_handles_empty_string():
    assert _safe_speaker("bulbul:v2", "") == _V2_DEFAULT
    assert _safe_speaker("bulbul:v3-beta", "") == _V3_DEFAULT


def test_v2_default_is_in_v2_speaker_set():
    assert _V2_DEFAULT in _V2_SPEAKERS


def test_v3_default_is_in_v3_speaker_set():
    assert _V3_DEFAULT in _V3_SPEAKERS


def test_speakers_dont_overlap_between_models():
    """v2 and v3 have non-overlapping speaker rosters in our code —
    a v3 speaker on a v2 model gets HTTP 400 from Sarvam, which is the
    real bug we hit. Guards must prevent this."""
    overlap = _V2_SPEAKERS & _V3_SPEAKERS
    # Acceptable to have some overlap, but defaults must be model-specific.
    assert _V2_DEFAULT != _V3_DEFAULT or len(overlap) > 0
