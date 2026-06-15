"""Sarvam streaming STT factory.

`codemix` mode + `saaras:v3` is the key choice: it transcribes mixed-
language speech (Hinglish / Tenglish) without locking to a single
language, which enables natural mid-sentence Telugu/Hindi/English
switching. We always keep streaming/partial transcripts on — the
pipeline acts on partials, never waits for the final transcript.

Model/mode come from the dashboard-editable RuntimeConfig.
"""

from __future__ import annotations

from livekit.plugins import sarvam

from src.config import settings
from src.runtime_config import RuntimeConfig


# Sarvam STT defaults to language='en-IN'. If we don't set it, Telugu
# speech is transcribed with the English model and comes out English —
# the LLM then replies in English even when the caller spoke Telugu.
# So the STT language MUST match the call's language.
_STT_LANG = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}

# UNIVERSAL voice-agent terms only — apply to ANY business (scheduling
# words STT commonly mangles). NO business-specific vocabulary here
# (multi-tenant safe). Domain terms — "acne" for a skin clinic, "BHK"
# for real estate — come from each tenant's OWN business description +
# optional per-tenant keyword field, so every tenant biases the STT to
# THEIR words automatically. (The skin-clinic hardcoding was a bug.)
_GENERIC_TERMS = (
    "appointment, booking, slot, reschedule, cancel, consultation, "
    "fee, timing, available, callback"
)


def _stt_prompt(cfg: RuntimeConfig) -> str:
    """Per-tenant STT keyterm bias: universal scheduling terms + this
    business's own vocabulary (from its description + optional explicit
    `stt_keywords`). Fully tenant-scoped — no hardcoded business terms."""
    biz = (cfg.business_description or "").strip()[:380]
    explicit = (getattr(cfg, "stt_keywords", "") or "").strip()
    parts = [p for p in (_GENERIC_TERMS, explicit, biz) if p]
    return ". ".join(parts)


def build_stt(cfg: RuntimeConfig | None = None) -> sarvam.STT:
    cfg = cfg or RuntimeConfig()
    lang = _STT_LANG.get(cfg.default_language, "en-IN")
    return sarvam.STT(
        model=cfg.stt_model,          # saaras:v3 (broadest coverage)
        mode=cfg.stt_mode,            # codemix -> handles mixed within lang
        language=lang,                # te-IN / hi-IN / en-IN per the call
        api_key=settings.sarvam_api_key or None,
        # Keyterm biasing — fixes "acne" mis-heard as "ethnic" etc.
        prompt=_stt_prompt(cfg),
        # Make Sarvam's server-side VAD declare end-of-speech sooner so the
        # FINAL transcript flushes faster — kills the up-to-2s "dead gap"
        # that was the real perceived latency (not the LLM). Env-revertible.
        high_vad_sensitivity=settings.stt_high_vad_sensitivity,
        # Force the FINAL transcript the moment speech ends instead of
        # waiting on Sarvam's server-side endpointing. Without this,
        # finals intermittently arrived 7.8-20s after the caller stopped
        # (live call out-e232cb1fc4, 2026-06-12) — the whole perceived
        # "agent thinking forever" lag was STT-final wait, not the LLM.
        flush_signal=True,
    )
