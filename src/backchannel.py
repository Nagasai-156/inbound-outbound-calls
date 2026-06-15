"""Real-time backchanneling — active-listening acks.

The strongest "this is a human, not a bot" signal on a phone call is the
short murmur a listener makes WHILE the other person is still talking:
"హా… అవును…", "हाँ… जी…", "mhm… right…". A bot that stays dead silent
until the caller finishes, then replies, feels like a walkie-talkie.

This module decides WHEN to drop one such ack during a long caller
utterance, and supplies the (very short) phrase. The actual audio is
played by the caller (agent.py) via the TTS cache, so it's ~instant and
synthesis-free after the first use.

Design rules (so it helps, never annoys):
  * ONE ack per utterance, max — never a stream of "mhm mhm mhm".
  * Only on LONG utterances (>= N words AND >= T seconds of talking) —
    short caller turns need no acknowledgement.
  * Cooldown across utterances so acks stay occasional, not every turn.
  * Anti-repeat phrase rotation so it never sounds canned.
  * The caller-side wiring additionally suppresses acks while the agent
    itself is speaking and feeds every ack to the echo guard, so the
    backchannel is never transcribed back as caller speech.

All thresholds come from `settings` (global tuning, not per-campaign).
"""

from __future__ import annotations

import random

from src.config import settings

# Short, telephony-safe acks per language. Kept tiny on purpose: a
# backchannel is a murmur, not a sentence. These synthesise cleanly on
# Sarvam and cache to near-instant replay.
# Single-syllable tokens ("హా", "हाँ", "जी", "mhm") excluded — Sarvam
# returns zero audio frames for them (live failure 2026-06-12).
_POOLS: dict[str, list[str]] = {
    # At most one అండి/జీ entry — the honorific everywhere was a robotic
    # tell (live feedback 2026-06-12).
    "te": ["అవును", "సరే", "ఆహా", "హా అండి"],
    "hi": ["अच्छा", "ठीक है", "हाँ जी", "हम्म ठीक है"],
    "en": ["okay", "right", "I see", "sure"],
}

_last_idx: dict[str, int] = {}


def _lang_key(language: str | None) -> str:
    if not language:
        return "en"
    if language.startswith("te"):
        return "te"
    if language.startswith("hi"):
        return "hi"
    return "en"


def pick_backchannel(language: str | None) -> str:
    """A short ack in the caller's language, never the same one twice in
    a row (so repeated acks across a call don't sound looped)."""
    lang = _lang_key(language)
    pool = _POOLS.get(lang) or _POOLS["en"]
    prev = _last_idx.get(lang, -1)
    choices = [i for i in range(len(pool)) if i != prev] or [0]
    idx = random.choice(choices)
    _last_idx[lang] = idx
    return pool[idx]


class Backchanneler:
    """Per-call state machine deciding when to emit one listening ack.

    Fed the caller's running (interim) transcript. Returns True at most
    once per utterance, only when the utterance is long enough and the
    cooldown since the last ack has elapsed.
    """

    def __init__(self) -> None:
        self._utt_start: float | None = None
        self._fired_this_utt: bool = False
        self._last_ack_at: float = -1e9  # long ago, so the first can fire

    def reset_utterance(self) -> None:
        """Call on a FINAL transcript — the caller finished this utterance."""
        self._utt_start = None
        self._fired_this_utt = False

    def should_ack(self, interim_text: str, now: float) -> bool:
        """Decide whether to drop an ack given the current interim text.

        `now` is a monotonic timestamp (seconds). Returns True at most
        once per utterance.
        """
        if self._utt_start is None:
            self._utt_start = now
        if self._fired_this_utt:
            return False
        words = len((interim_text or "").split())
        if words < settings.backchannel_min_words:
            return False
        if (now - self._utt_start) < settings.backchannel_min_seconds:
            return False
        if (now - self._last_ack_at) < settings.backchannel_cooldown_seconds:
            return False
        self._fired_this_utt = True
        self._last_ack_at = now
        return True
