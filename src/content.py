"""Dynamic content store (fillers + canned replies).

The whole point of fillers/canned replies is that they are served in
~100ms with NO runtime LLM call. So we DON'T call the LLM at call time.
Instead `scripts/gen_content.py` uses the LLM *offline* to generate large,
business/persona-specific pools and writes them to Redis. At runtime this
store just reads those pools (cached in-process) and the existing
anti-repeat rotation picks a line — instant.

If Redis is empty or unreachable it transparently falls back to the
built-in defaults, so the system always works (and unit tests stay
network-free).
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("content")

# Redis key layout (populated by scripts/gen_content.py):
#   content:filler:<lang>            -> JSON list[str]
#   content:canned:<intent>:<lang>   -> JSON list[str]
FILLER_KEY = "content:filler:{lang}"
CANNED_KEY = "content:canned:{intent}:{lang}"

# ─── Built-in defaults (fallback + seed for the generator) ───────────
# Fillers are split by KIND so selection is driven by what the caller
# just said (per LiveKit's research-backed guidance:
# https://livekit.com/blog/prompting-voice-agents-to-sound-more-realistic).
# Real humans don't say "ఒక్క నిమిషం" every turn — they acknowledge
# statements with short sounds (ఆ / హ్మ్ / mm-hmm) and only verbalize
# "one second / let me check" when the caller asked something that
# needs a lookup. Serving a checking-phrase on a non-question turn was
# the "checking but no tool" robotic tell seen in transcripts.
#   ack      — pure backchannels for statements/acknowledgement turns
#   checking — latency-cover for question/lookup turns (a real beat)
DEFAULT_FILLERS: dict[str, dict[str, list[str]]] = {
    # NOTE: single-syllable interjections ("ఆ...", "హా...", "హ్మ్...",
    # "हाँ...") are EXCLUDED — Sarvam TTS returns zero audio frames for
    # them (seen live 2026-06-12: APIError "no audio frames were pushed
    # for text: ఆ..."), which kicked the session into fallback voice.
    # Every entry below must be ≥2 syllables of real text.
    # Keep "అండి" RARE in these pools: live feedback 2026-06-12 — the
    # caller heard "అండి" in the filler AND at every clause of the reply
    # ("ఆ అండి... ఉంది అండి...") and called it robotic. At most ONE
    # అండి entry per pool; rotation spreads it thin.
    "te": {
        "ack": [
            "సరే...",
            "అలాగే...",
            "అవును...",
            "ఆహా...",
            "ఆ అండి...",
            "ఓకే...",
        ],
        "checking": [
            "ఆ... చూస్తున్నా...",
            "ఒక్క సెకన్...",
            "చెక్ చేస్తున్నా...",
        ],
    },
    "hi": {
        "ack": [
            "जी हाँ...",
            "अच्छा...",
            "हाँ जी...",
            "ठीक है...",
            "अच्छा अच्छा...",
            "ठीक है जी...",
        ],
        "checking": [
            "हाँ... देख रहा हूँ...",
            "एक second जी...",
            "जी, अभी check करता हूँ...",
        ],
    },
    "en": {
        "ack": [
            "Okay...",
            "Right...",
            "Got it...",
            "Sure...",
            "Ah, okay...",
            "I see...",
            "Alright...",
        ],
        "checking": [
            "Let me see...",
            "One second...",
            "Let me check that...",
        ],
    },
}

DEFAULT_CANNED: dict[str, dict[str, list[str]]] = {
    "greeting": {
        "te": ["హలో అండి, చెప్పండి.", "నమస్కారం అండి, ఎలా హెల్ప్ చేయగలను?"],
        "hi": ["Hello जी, बताइए.", "नमस्ते जी, कैसे help करूँ?"],
        "en": ["Hello, how can I help you today?", "Hi there, tell me how I can help."],
    },
    "affirm": {
        "te": ["సరే అండి.", "అవును అండి, చెప్పండి.", "ఓకే అండి."],
        "hi": ["ठीक है जी.", "हाँ जी, बताइए.", "Okay जी."],
        "en": ["Okay.", "Sure, go ahead.", "Got it."],
    },
    "deny": {
        "te": ["సరే అండి, పర్లేదు.", "ఓకే అండి, ఇంకేమైనా?"],
        "hi": ["ठीक है जी, कोई बात नहीं.", "Okay जी, और कुछ?"],
        "en": ["No problem.", "Okay, anything else?"],
    },
    "thanks": {
        "te": ["నో ప్రాబ్లం అండి, గ్లాడ్ టు హెల్ప్!", "అయ్యో, పర్లేదు అండి, నో ప్రాబ్లం!", "పర్లేదు అండి, రెడీగా ఉంటాను ఎప్పుడైనా!", "నో ప్రాబ్లం అండి, రెడీగా ఉంటాను!"],
        "hi": ["आपका स्वागत है जी.", "कोई बात नहीं जी."],
        "en": ["You're welcome.", "Happy to help."],
    },
    "bye": {
        "te": ["ధన్యవాదాలు అండి, మంచి రోజు.", "సరే అండి, బై."],
        "hi": ["धन्यवाद जी, आपका दिन शुभ हो.", "ठीक है जी, bye."],
        "en": ["Thank you, have a good day.", "Okay, bye."],
    },
    "repeat": {
        "te": ["సారీ అండి, మళ్ళీ చెప్పండి.", "కొంచెం రిపీట్ చేస్తారా అండి?"],
        "hi": ["सॉरी जी, एक बार फिर बोलिए.", "थोड़ा repeat करेंगे जी?"],
        "en": ["Sorry, could you say that again?", "Once more please?"],
    },
}

LANGS = ("te", "hi", "en")


class ContentStore:
    """In-process snapshot of the pools. Starts as defaults; `refresh()`
    overlays whatever the generator wrote to Redis."""

    def __init__(self) -> None:
        self._fillers = {
            lang: {kind: list(pool) for kind, pool in kinds.items()}
            for lang, kinds in DEFAULT_FILLERS.items()
        }
        self._canned = {
            i: {l: list(x) for l, x in d.items()}
            for i, d in DEFAULT_CANNED.items()
        }
        self._loaded = False

    def _map_lang(self, lang: str | None) -> str:
        if not lang:
            return "en"
        if lang.startswith("te"):
            return "te"
        if lang.startswith("hi"):
            return "hi"
        return "en"

    # ─── sync accessors used on the hot path (no awaiting) ───────────
    def fillers(self, lang: str, kind: str | None = None) -> list[str]:
        """Filler pool for a language. kind="ack"|"checking" selects the
        turn-appropriate pool; kind=None returns the combined pool."""
        l = self._map_lang(lang)
        kinds = self._fillers.get(l) or self._fillers["en"]
        if kind:
            return kinds.get(kind) or kinds.get("ack") or []
        return [t for pool in kinds.values() for t in pool]

    def canned(self, intent: str, lang: str) -> list[str] | None:
        l = self._map_lang(lang)
        pool = self._canned.get(intent)
        if not pool:
            return None
        return pool.get(l) or pool.get("en")

    # ─── async refresh from Redis (called once at call/worker start) ─
    async def refresh(self, redis_url: str) -> None:
        """DISABLED ON PURPOSE.

        The Redis content overlay (written by scripts/gen_content.py) has
        NO domain or language guarantee: a pool generated for business A
        gets served verbatim on a call for business B, in whatever
        language the generator happened to emit. A real Telugu dental
        call ended up speaking "I'll give a demo" and "Hi there! Aapka
        din kaisa hai? Let's chat!" — another business's English/Hindi
        chatbot lines, bypassing the persona and the language lock.

        Until gen_content is reworked to be strictly per-call,
        per-language and persona-aware, we use ONLY the curated built-in
        defaults below (short, language-correct, neutral). This is a
        correctness decision: a wrong-domain canned line is far worse
        than the ~100ms a clean default costs.
        """
        self._loaded = True
        logger.info("content overlay disabled — using built-in defaults")


content_store = ContentStore()
