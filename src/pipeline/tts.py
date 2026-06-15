"""Sarvam streaming TTS factory with per-language voice.

Replies are kept to 1-2 short sentences by the persona, so first-audio
latency stays low. Voice/language/model/pace all come from the
dashboard-editable RuntimeConfig and can change between calls.

Sarvam Bulbul: 460ms TTFB, proven Telugu quality.
"""

from __future__ import annotations

import logging

from livekit.plugins import sarvam

from src.config import settings
from src.runtime_config import RuntimeConfig

logger = logging.getLogger("tts")

LANG_CODE = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}
DEFAULT_LANG = "en"

# Sarvam rejects (HTTP 400) a speaker that doesn't belong to the model.
# Guard here so a stale dashboard value never breaks a live call.
_MODELS = {"bulbul:v2", "bulbul:v3-beta"}
_V2_SPEAKERS = {
    "anushka", "manisha", "vidya", "arya", "abhilash", "karun", "hitesh",
}
_V3_SPEAKERS = {
    "shubh", "ritu", "rahul", "pooja", "simran", "kavya", "amit", "ratan",
    "rohan", "dev", "ishita", "shreya", "manan", "sumit", "priya",
    "aditya", "kabir", "neha", "varun", "roopa", "aayan", "ashutosh",
    "advait",
}
_V2_DEFAULT = "anushka"
_V3_DEFAULT = "ritu"


def _code(language: str) -> str:
    return LANG_CODE.get(language, LANG_CODE[DEFAULT_LANG])


def _safe_model(model: str) -> str:
    return model if model in _MODELS else "bulbul:v2"


def _safe_speaker(model: str, speaker: str) -> str:
    """Return a speaker guaranteed valid for the (sanitized) model."""
    if model == "bulbul:v3-beta":
        return speaker if speaker in _V3_SPEAKERS else _V3_DEFAULT
    return speaker if speaker in _V2_SPEAKERS else _V2_DEFAULT


def build_tts(
    cfg: RuntimeConfig | None = None, language: str | None = None
) -> sarvam.TTS:
    cfg = cfg or RuntimeConfig()
    language = language or cfg.default_language

    # Sarvam TTS: proven Telugu quality
    model = _safe_model(cfg.tts_model)
    return sarvam.TTS(
        model=model,
        target_language_code=_code(language),
        speaker=_safe_speaker(model, cfg.speaker_for(language)),
        pace=cfg.pace_for(language),
        # TELEPHONY AUDIO FIX: pin output to 24 kHz. The plugin default is
        # 22050 Hz, which does NOT resample cleanly to the telephony 8 kHz
        # PSTN rate (ratio 2.756) nor LiveKit's 48 kHz internal rate — the
        # fractional-ratio resampler injects "salt-and-pepper" static and
        # makes the voice sound gritty/distorted on real SIP calls.
        # 24000 downsamples to 8 kHz at an exact 3:1 ratio (and 48 kHz at
        # 2:1), giving clean, artifact-free audio. (Browser previews use
        # the HTTP path played at 22050 with no telephony resample, which
        # is why previews sounded clean but live calls didn't.)
        speech_sample_rate=24000,
        # Round 4: server-side preprocessing so "17:30" / "INR 25,000" /
        # "Dr. Lakshmi" / "10/12/2025" / "GST" are spoken cleanly instead
        # of letter-by-letter. Dashboard-flippable via tts_enable_preprocessing.
        enable_preprocessing=getattr(cfg, "tts_enable_preprocessing", True),
        api_key=settings.sarvam_api_key or None,
    )


# Emotion-driven pace multipliers applied on top of the per-language
# base pace. A real human call-center exec naturally slows down when
# the caller is confused/elderly, speeds up to match an excited caller,
# and softens (slightly slower) when the caller is angry/frustrated so
# the response doesn't sound dismissive. Bounded multipliers so a wrong
# emotion read never produces unintelligibly fast or sluggish speech.
_EMOTION_PACE = {
    "angry":      0.95,   # slightly slower — calm, deliberate, not dismissive
    "urgent":     1.00,   # match urgency, but don't rush past clarity
    "frustrated": 0.92,   # noticeably slower — empathetic
    "confused":   0.85,   # clearly slower — give them time to follow
    "elderly":    0.85,   # clarity over speed
    "happy":      1.05,   # match the energy — feels alive
    "neutral":    1.00,
}


def _emotion_factor(emotion: str | None) -> float:
    """Bounded multiplier in [0.80, 1.10] so a misclassified emotion
    can never produce dangerously slow or fast speech."""
    if not emotion:
        return 1.0
    f = _EMOTION_PACE.get(emotion.lower(), 1.0)
    return max(0.80, min(1.10, f))


def retune_tts(
    tts: sarvam.TTS,
    cfg: RuntimeConfig,
    language: str,
    *,
    emotion: str | None = None,
) -> None:
    """Adapt the live TTS to the caller's language + emotion mid-call.

    Sarvam Bulbul speakers are multilingual and `target_language_code`
    is fixed at construction (update_options can't change it), so we
    switch the per-language *speaker* + pace in place — no reconnect,
    natural enough since codemix STT already handles mixed input.

    `emotion` (optional): when provided, modulates the per-language base
    pace by a bounded multiplier (see _EMOTION_PACE). A confused caller
    hears a measurably slower answer; a happy caller hears matched energy.
    Bounded to [0.80, 1.10] of base pace so a misclassified emotion
    cannot produce unintelligibly fast/slow speech.
    """
    spk = _safe_speaker(_safe_model(cfg.tts_model), cfg.speaker_for(language))
    fn = getattr(tts, "update_options", None)
    if not callable(fn):
        logger.warning(
            "retune_tts: this Sarvam build has no update_options; "
            "voice stays as set at session start"
        )
        return
    try:
        base_pace = cfg.pace_for(language)
        factor = _emotion_factor(emotion)
        pace = round(base_pace * factor, 3)
        fn(speaker=spk, pace=pace)
        logger.info(
            "retune_tts -> speaker=%s base_pace=%.2f emotion=%s factor=%.2f final_pace=%.2f",
            spk, base_pace, emotion or "-", factor, pace,
        )
    except Exception:
        logger.warning("retune_tts failed (keeping current voice)",
                        exc_info=True)
