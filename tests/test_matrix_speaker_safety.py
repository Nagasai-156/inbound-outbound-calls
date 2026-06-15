"""TTS speaker validation matrix — exhaustive cross-product test."""

from __future__ import annotations

import pytest

from src.pipeline.tts import (
    _safe_speaker, _safe_model,
    _V2_SPEAKERS, _V3_SPEAKERS,
    _V2_DEFAULT, _V3_DEFAULT,
)


@pytest.mark.parametrize("spk", sorted(_V2_SPEAKERS))
def test_every_v2_speaker_passes(spk):
    assert _safe_speaker("bulbul:v2", spk) == spk


@pytest.mark.parametrize("spk", sorted(_V3_SPEAKERS))
def test_every_v3_speaker_passes(spk):
    assert _safe_speaker("bulbul:v3-beta", spk) == spk


@pytest.mark.parametrize("bad_speaker", [
    "amelia", "sophia", "xyz", "anushka_clone",
    "", "  ", "anushka123", "ANUSHKA", "Anushka",
    "ritu_v4", "future-speaker", "test", "tts",
])
def test_invalid_v2_speakers_fall_back_to_default(bad_speaker):
    out = _safe_speaker("bulbul:v2", bad_speaker)
    assert out in _V2_SPEAKERS, f"{bad_speaker!r} → {out}"


@pytest.mark.parametrize("bad_speaker", [
    "amelia", "sophia", "anushka", "abhilash",
    "", "  ", "ritu_clone", "RITU", "future",
    "v4-speaker", "test-only", "garbage",
])
def test_invalid_v3_speakers_fall_back_to_default(bad_speaker):
    out = _safe_speaker("bulbul:v3-beta", bad_speaker)
    assert out in _V3_SPEAKERS, f"{bad_speaker!r} → {out}"


@pytest.mark.parametrize("model", [
    "bulbul:v2", "bulbul:v3-beta",
])
def test_known_models_pass(model):
    assert _safe_model(model) == model


@pytest.mark.parametrize("bad_model", [
    "bulbul:v4", "bulbul:v3", "saaras:v3", "bulbul",
    "", "garbage", "BULBUL:V2",  # case-sensitive
])
def test_unknown_models_default_v2(bad_model):
    """Defensive: unknown model must fall back to a known one."""
    out = _safe_model(bad_model)
    assert out in {"bulbul:v2", "bulbul:v3-beta"}


# Cross-model: every v2 speaker on v3 model and vice versa
@pytest.mark.parametrize("spk", sorted(_V2_SPEAKERS))
def test_v2_speaker_on_v3_model_falls_back(spk):
    if spk in _V3_SPEAKERS:
        # speaker IS valid on v3 — no fallback needed
        assert _safe_speaker("bulbul:v3-beta", spk) == spk
    else:
        assert _safe_speaker("bulbul:v3-beta", spk) == _V3_DEFAULT


@pytest.mark.parametrize("spk", sorted(_V3_SPEAKERS))
def test_v3_speaker_on_v2_model_falls_back(spk):
    if spk in _V2_SPEAKERS:
        assert _safe_speaker("bulbul:v2", spk) == spk
    else:
        assert _safe_speaker("bulbul:v2", spk) == _V2_DEFAULT
