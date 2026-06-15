"""Conditional + dynamic filler responses.

The plan's #1 fix: do NOT prefix every reply with "okay sir...". A filler
is only worth it when the real answer will actually be slow. So we emit
one ONLY when:

  * the turn routed to LLM or KB (real latency incoming), OR
  * STT confidence is low (we need a beat anyway), OR
  * measured think-time has already exceeded the latency threshold.

Canned and cache routes are instant -> NO filler (that's what made it
feel artificial). When we do speak one, it's drawn from a per-language
pool with anti-repeat rotation so it never sounds canned.
"""

from __future__ import annotations

from src.content import content_store
from src.router.intent_router import Route
from src.runtime_config import RuntimeConfig

_last_idx: dict[str, int] = {}

# Intents whose answer requires a real lookup — a "checking" filler
# ("one second, let me see") is then HONEST, not a fake.
_LOOKUP_INTENTS = {"order_status", "payment_issue", "refund", "repeat"}

# A "checking" filler is ONLY honest when the caller asked something the
# agent must actually look up (availability / booking / price / order).
# A plain question ("who are you", "how does it work") is answered from
# memory — that gets a soft ack, never a fake "I'm checking". Saying
# "checking" on every question was the robotic tell.
_LOOKUP_CUES = {
    # en — scheduling / availability / money / order
    "slot", "slots", "available", "availability", "time", "timing",
    "book", "booking", "appointment", "appoint", "schedule", "reschedule",
    "cancel", "order", "price", "cost", "fee", "charge", "free", "when",
    "khali", "unda", "undha", "eppudu",
    # te script
    "ఖాళీ", "స్లాట్", "టైం", "టైము", "బుక్", "అపాయింట్‌మెంట్", "ధర",
    "ఎప్పుడు", "ఉందా",
    # hi script
    "स्लॉट", "समय", "बुक", "अपॉइंटमेंट", "कब", "कीमत",
}


def filler_kind(intent: str | None = None, user_text: str = "") -> str:
    """Which filler to use IF one fires: "checking" only when the caller
    asked something we genuinely look up (a lookup intent or a booking/
    availability/price cue); otherwise a soft "ack". This never decides
    WHETHER to fire — only which phrase. Never say "I'm checking" when
    the agent isn't actually checking anything."""
    if intent in _LOOKUP_INTENTS:
        return "checking"
    text = (user_text or "").strip().lower()
    if not text:
        return "ack"
    words = {w.strip(".,!?") for w in text.split()}
    if words & _LOOKUP_CUES:
        return "checking"
    return "ack"


def _lang_key(language: str | None) -> str:
    if not language:
        return "en"
    if language.startswith("te"):
        return "te"
    if language.startswith("hi"):
        return "hi"
    return "en"


def should_filler(
    route: Route,
    stt_confidence: float = 1.0,
    elapsed_seconds: float = 0.0,
    cfg: RuntimeConfig | None = None,
) -> bool:
    """Determine whether to play a vocal filler to cover latency.

    Triggered when:
      * the route is LLM/KB (these are always slow: >0.3s) AND threshold is positive,
      * OR the elapsed thinking time has already exceeded the latency threshold,
      * OR STT confidence is low (need to buy time for stabilizer/context).
    """
    cfg = cfg or RuntimeConfig()
    threshold = cfg.filler_latency_threshold

    # If the route is slow (LLM), we immediately know it will exceed the threshold (e.g. 0.3s)
    if route == Route.LLM and threshold > 0:
        return True

    # Legacy / fallback opt-in triggers (if threshold is negative or zero)
    if threshold <= 0:
        if route == Route.LLM:
            return True
        if stt_confidence < cfg.filler_min_stt_confidence:
            return True
        if elapsed_seconds > 0:
            return True

    # If elapsed time already exceeded threshold
    if elapsed_seconds > threshold:
        return True

    # Low confidence on transcription warrants a filler beat
    if stt_confidence < cfg.filler_min_stt_confidence:
        return True

    return False


def pick_filler(
    language: str, intent: str | None = None, user_text: str = ""
) -> str:
    """A short filler in the caller's language, chosen by what they just
    said (question/lookup -> "checking", statement -> soft ack) with
    deterministic sequential rotation — never the same one twice in a
    row, and never a random pick."""
    lang = _lang_key(language)
    kind = filler_kind(intent, user_text)
    pool = content_store.fillers(lang, kind)
    if not pool:
        return ""
    key = f"{lang}:{kind}"
    idx = (_last_idx.get(key, -1) + 1) % len(pool)
    _last_idx[key] = idx
    return pool[idx]
