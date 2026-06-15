"""RuntimeConfig defaults + helpers (network-free).

The dashboard edits these; the agent loads them per call. We only verify
the pure pieces here — DB/Redis paths are integration concerns.
"""

from src.config import settings
from src.pipeline.turn import endpointing_delay_for
from src.runtime_config import RuntimeConfig


def test_defaults_track_env_settings():
    c = RuntimeConfig()
    assert c.llm_model == settings.llm_model
    assert c.stt_model == settings.stt_model
    assert c.memory_max_turns == settings.memory_max_turns
    assert c.min_endpointing_delay == settings.min_endpointing_delay


def test_speaker_for_language():
    c = RuntimeConfig(
        tts_speaker_te="te_v", tts_speaker_hi="hi_v", tts_speaker_en="en_v"
    )
    assert c.speaker_for("te") == "te_v"
    assert c.speaker_for("hi") == "hi_v"
    assert c.speaker_for("en") == "en_v"
    assert c.speaker_for("mixed") == "en_v"  # safe fallback


def test_endpointing_uses_runtime_config():
    c = RuntimeConfig(
        telugu_min_endpointing_delay=0.9, min_endpointing_delay=0.3
    )
    assert endpointing_delay_for("te", c) == 0.9
    assert endpointing_delay_for("en", c) == 0.3
    assert endpointing_delay_for("hi", c) == 0.3
