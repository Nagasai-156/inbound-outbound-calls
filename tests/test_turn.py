"""Turn detection — the Telugu soft guard.

The failure we must prevent: VAD reads a natural Telugu pause as
end-of-turn and the agent cuts the caller off. The safe guard is a
LONGER per-language endpointing floor for Telugu (not a per-turn
StopResponse, which previously muted normal short turns).
"""

from src.pipeline.turn import endpointing_delay_for
from src.runtime_config import RuntimeConfig
from src.config import settings


def test_telugu_gets_longer_endpointing_floor():
    # With a real RuntimeConfig, Telugu must wait longer than En/Hi.
    cfg = RuntimeConfig(
        telugu_min_endpointing_delay=0.45, min_endpointing_delay=0.30
    )
    assert endpointing_delay_for("te", cfg) == 0.45
    assert endpointing_delay_for("tenglish", cfg) == 0.45
    assert endpointing_delay_for("en", cfg) == 0.30
    assert endpointing_delay_for("hi", cfg) == 0.30
    # Telugu floor is strictly larger than the generic floor.
    assert endpointing_delay_for("te", cfg) > endpointing_delay_for("en", cfg)


def test_endpointing_defaults_track_env_settings():
    # No cfg passed -> falls back to env-default RuntimeConfig.
    assert endpointing_delay_for("te") == settings.telugu_min_endpointing_delay
    assert endpointing_delay_for("en") == settings.min_endpointing_delay
