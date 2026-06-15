"""Extended RuntimeConfig tests — speaker_for, pace_for, edge cases."""

from __future__ import annotations

import dataclasses

from src.runtime_config import RuntimeConfig


def _cfg(**kw) -> RuntimeConfig:
    return dataclasses.replace(RuntimeConfig(), **kw)


# ─── speaker_for ────────────────────────────────────────────────────


def test_speaker_for_telugu():
    cfg = _cfg(tts_speaker_te="anushka", tts_speaker_hi="ritu", tts_speaker_en="anushka")
    assert cfg.speaker_for("te") == "anushka"


def test_speaker_for_hindi():
    cfg = _cfg(tts_speaker_te="anushka", tts_speaker_hi="ritu", tts_speaker_en="anushka")
    assert cfg.speaker_for("hi") == "ritu"


def test_speaker_for_english():
    cfg = _cfg(tts_speaker_en="abhilash")
    assert cfg.speaker_for("en") == "abhilash"


def test_speaker_for_unknown_falls_back_to_default():
    """Unknown language should not crash; falls back."""
    cfg = _cfg()
    spk = cfg.speaker_for("xx")
    assert isinstance(spk, str) and len(spk) > 0


def test_speaker_for_language_with_prefix():
    """'te-IN' should resolve to Telugu speaker."""
    cfg = _cfg(tts_speaker_te="vidya", tts_speaker_hi="ritu", tts_speaker_en="anushka")
    assert cfg.speaker_for("te-IN") == "vidya"
    assert cfg.speaker_for("te-mix") == "vidya"


# ─── pace_for ──────────────────────────────────────────────────────


def test_pace_for_inherits_global_when_per_lang_zero():
    """0.0 per-language override means inherit global ttsPace."""
    cfg = _cfg(tts_pace=0.95, tts_pace_te=0.0, tts_pace_hi=0.0, tts_pace_en=0.0)
    assert cfg.pace_for("te") == 0.95
    assert cfg.pace_for("hi") == 0.95
    assert cfg.pace_for("en") == 0.95


def test_pace_for_per_language_override():
    cfg = _cfg(tts_pace=1.0, tts_pace_te=0.85, tts_pace_hi=1.1, tts_pace_en=0.0)
    assert cfg.pace_for("te") == 0.85   # explicit Telugu override
    assert cfg.pace_for("hi") == 1.1     # explicit Hindi override
    assert cfg.pace_for("en") == 1.0     # inherit global


def test_pace_for_unknown_language_uses_global():
    cfg = _cfg(tts_pace=0.92)
    assert cfg.pace_for("xx") == 0.92


# ─── defaults sanity ───────────────────────────────────────────────


def test_default_endpointing_is_telugu_friendly():
    """Telugu floor must be ≥ general floor (Telugu has longer pauses)."""
    cfg = _cfg()
    assert cfg.telugu_min_endpointing_delay >= cfg.min_endpointing_delay


def test_default_max_greater_than_min():
    cfg = _cfg()
    assert cfg.max_endpointing_delay > cfg.min_endpointing_delay


def test_default_cache_threshold_in_valid_range():
    cfg = _cfg()
    assert 0.0 <= cfg.cache_min_similarity <= 1.0


def test_default_llm_temperature_in_valid_range():
    cfg = _cfg()
    assert 0.0 <= cfg.llm_temperature <= 2.0


def test_default_memory_max_turns_positive():
    cfg = _cfg()
    assert cfg.memory_max_turns >= 1


def test_default_appt_hours_consistent():
    cfg = _cfg()
    assert cfg.appt_open_hour < cfg.appt_close_hour


def test_default_appt_slot_minutes_positive():
    cfg = _cfg()
    assert cfg.appt_slot_min > 0


def test_filler_latency_threshold_reasonable():
    cfg = _cfg()
    # Threshold between 0 and 2 seconds.
    assert 0.0 <= cfg.filler_latency_threshold <= 2.0


def test_filler_min_stt_confidence_in_unit_range():
    cfg = _cfg()
    assert 0.0 <= cfg.filler_min_stt_confidence <= 1.0
