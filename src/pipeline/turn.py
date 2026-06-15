"""VAD + turn detection.

Phase 2 provides the baseline: Silero VAD (fast voice activity) plus the
LiveKit MultilingualModel for contextual end-of-turn. Phase 3 layers the
Telugu/Tenglish continuation heuristic on top (the MultilingualModel covers
Hindi + English but NOT Telugu, so Telugu relies on tuned VAD endpointing
plus a trailing-token continuation guard).
"""

from __future__ import annotations

from src.config import settings
from src.runtime_config import RuntimeConfig

# LiveKit plugins MUST be imported at module load on the main thread
# (Plugin.register_plugin asserts this). They are imported here, guarded
# so the pure helpers below still import in a no-livekit unit-test env.
try:
    from livekit.plugins import silero as _silero

    try:
        from livekit.plugins.turn_detector.multilingual import (
            MultilingualModel as _MultilingualModel,
        )
    except Exception:  # pragma: no cover - optional dependency
        _MultilingualModel = None
    _PLUGINS = True
except Exception:  # pragma: no cover - unit tests without livekit
    _silero = None
    _MultilingualModel = None
    _PLUGINS = False


def build_vad():
    """Load Silero VAD (<100ms voice detection).

    Loaded once per worker process via the prewarm hook (caches weights).
    """
    if _silero is None:
        raise RuntimeError("livekit silero plugin not available")
    # PSTN echo suppression tuning (from env): start = min speech before
    # we treat audio as a turn, stop = silence before end-of-speech,
    # min_volume = activation threshold (higher rejects line echo/noise).
    return _silero.VAD.load(
        min_speech_duration=settings.vad_start_secs,
        min_silence_duration=settings.vad_stop_secs,
        activation_threshold=settings.vad_min_volume,
    )


def build_turn_detection():
    """Contextual end-of-turn detector for the AgentSession.

    Returns the MultilingualModel (Hi/En contextual EOT) when available,
    otherwise the string ``"vad"`` so the AgentSession falls back to pure
    VAD endpointing. The Telugu continuation guard below covers the gap
    (MultilingualModel does not support Telugu).
    """
    if _MultilingualModel is not None:
        return _MultilingualModel()
    return "vad"


# ─── Telugu / Tenglish continuation handling ─────────────────────
# MultilingualModel covers Hindi + English but NOT Telugu. Telugu speech
# has longer emotional/continuation pauses that pure VAD can read as
# end-of-turn.
#
# The SOFT guard for this is `endpointing_delay_for()` below: Telugu
# sessions get a longer minimum endpointing floor so the agent waits a
# bit more before responding. This is wired in agent.entrypoint via
# AgentSession(min_endpointing_delay=endpointing_delay_for(lang, cfg)).
#
# A prior per-turn `looks_incomplete()` heuristic that raised
# StopResponse was REMOVED on purpose — it muted normal short turns
# ("yes", "haan", "order status") and there is no safe per-turn
# endpointing override API. The per-language floor is the correct,
# regression-free soft guard.


def endpointing_delay_for(
    language: str, cfg: RuntimeConfig | None = None
) -> float:
    """Per-language minimum endpointing delay.

    Telugu/Tenglish get a longer floor because their natural pauses are
    longer; Hindi/English use the MultilingualModel + the shorter floor.
    Values come from the dashboard-editable RuntimeConfig.
    """
    cfg = cfg or RuntimeConfig()
    if language and (language.startswith("te") or language == "tenglish"):
        return cfg.telugu_min_endpointing_delay
    return cfg.min_endpointing_delay
