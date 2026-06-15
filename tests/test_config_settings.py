"""Config / Settings loading tests — env alias resolution + defaults."""

from __future__ import annotations

from src.config import Settings


def test_settings_has_all_required_fields():
    s = Settings()
    # Every required field must be accessible without raise.
    for attr in [
        "openai_api_key", "sarvam_api_key", "redis_url",
        "supabase_db_url", "livekit_url", "livekit_api_key",
        "livekit_api_secret", "log_level", "tts_model",
        "vad_start_secs", "vad_stop_secs", "vad_min_volume",
        "min_endpointing_delay", "max_endpointing_delay",
        "telugu_min_endpointing_delay", "min_interruption_duration",
        "filler_latency_threshold", "filler_min_stt_confidence",
        "semantic_cache_min_similarity", "semantic_cache_ttl_seconds",
        "kb_min_score", "appt_open_hour", "appt_close_hour",
        "appt_slot_min", "appt_open_weekdays",
    ]:
        assert hasattr(s, attr), f"Settings missing {attr}"


def test_endpointing_defaults_consistent():
    s = Settings()
    assert s.min_endpointing_delay < s.max_endpointing_delay
    # Telugu floor >= general floor.
    assert s.telugu_min_endpointing_delay >= s.min_endpointing_delay


def test_appt_defaults_valid_grid():
    s = Settings()
    assert 0 <= s.appt_open_hour < 24
    assert 1 <= s.appt_close_hour <= 24
    assert s.appt_close_hour > s.appt_open_hour
    assert s.appt_slot_min > 0


def test_appt_open_weekdays_parses_to_ints():
    s = Settings()
    raw = s.appt_open_weekdays
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    for p in parts:
        assert p.isdigit()
        assert 0 <= int(p) <= 6


def test_cache_threshold_in_unit_range():
    s = Settings()
    assert 0.0 <= s.semantic_cache_min_similarity <= 1.0


def test_cache_ttl_positive():
    s = Settings()
    assert s.semantic_cache_ttl_seconds > 0


def test_vad_params_valid():
    s = Settings()
    assert s.vad_start_secs >= 0
    assert s.vad_stop_secs >= 0
    assert 0.0 <= s.vad_min_volume <= 1.0


def test_filler_threshold_in_unit_range():
    s = Settings()
    assert 0.0 <= s.filler_min_stt_confidence <= 1.0
