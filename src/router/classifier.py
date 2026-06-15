"""Lightweight local language + intent classifier.

Zero network, sub-millisecond. It does two jobs:

  * detect the caller's language (te / hi / en / mixed) so replies and
    fillers mirror it, and
  * label a coarse intent so the router can bypass the LLM for trivial
    turns and so structured memory gets an `intent` slot.

This is intentionally a fast heuristic, NOT an ML model — it is the
"don't overuse GPT" guardrail. Ambiguous cases fall through to the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Unicode blocks: Telugu U+0C00–U+0C7F, Devanagari (Hindi) U+0900–U+097F.
_TELUGU_RE = re.compile(r"[ఀ-౿]")
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")

# Romanized cue words (Sarvam codemix often returns Latin script).
_TE_CUES = {
    "anna", "andi", "cheppandi", "cheppu", "ekkada", "undi", "unnaru",
    "naa", "nenu", "meeru", "miru", "kavali", "ela", "emi", "enti",
    "avunu", "ledu", "sari", "chesthunnanu", "order", "dabbulu",
}
_HI_CUES = {
    "haan", "nahi", "nahin", "kya", "kaha", "kahan", "hai", "ho", "gaya",
    "bhai", "mera", "mujhe", "kaise", "karo", "karta", "boliye", "ek",
    "bhaiya", "thik", "theek", "acha", "accha", "paisa", "kyun",
    # Expanded — common everyday Hindi STT outputs that previously
    # detected as English (real gap surfaced by classifier-matrix tests):
    "thoda", "abhi", "chahiye", "kar", "raha", "rahi", "hu", "hun",
    "tha", "thi", "aap", "main", "yeh", "woh", "milegi", "milega",
    "batayein", "bata", "achha", "bilkul", "samajh", "matlab",
    "phir", "abhi", "pehle", "baad", "sirf", "saath", "wala", "wali",
}
_EN_CUES = {
    "the", "please", "help", "can", "you", "i", "need", "want", "what",
    "where", "how", "my", "is", "with", "issue", "problem", "thanks",
}

# Coarse intents. Keyword sets are multilingual (romanized + English).
_INTENT_KEYWORDS: dict[str, set[str]] = {
    "greeting": {"hello", "hi", "hey", "namaste", "namaskaram", "vanakkam"},
    "affirm": {"yes", "yeah", "ok", "okay", "haan", "ha", "avunu", "sari", "right", "hmm"},
    "deny": {"no", "nope", "nahi", "nahin", "ledu", "kaadu", "vaddu"},
    "thanks": {"thanks", "thank", "thankyou", "dhanyavaad", "dhanyavadalu", "shukriya"},
    "bye": {"bye", "goodbye", "ok bye", "alvida", "velthanu", "rakhta", "rakhti"},
    "repeat": {"repeat", "again", "marokkasari", "malli"},
    "order_status": {"order", "tracking", "track", "delivery", "deliver", "parcel",
                     "shipment", "dispatch", "ekkada"},
    "payment_issue": {"payment", "pay", "paid", "paisa", "dabbulu", "transaction",
                      "debited", "fail", "failed", "charge"},
    "refund": {"refund", "return", "cancel", "money", "wapas", "tirigi"},
}

_GREETING_INTENTS = {"greeting", "affirm", "deny", "thanks", "bye", "repeat"}


@dataclass
class Classification:
    language: str        # te | hi | en | mixed
    intent: str          # see _INTENT_KEYWORDS keys + "unknown"
    is_trivial: bool     # true -> safe to answer without the LLM
    confidence: float    # heuristic 0..1


def detect_language(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "en"
    if _TELUGU_RE.search(t):
        return "te"
    if _DEVANAGARI_RE.search(t):
        return "hi"

    words = set(re.findall(r"[a-z]+", t.lower()))
    te = len(words & _TE_CUES)
    hi = len(words & _HI_CUES)
    en = len(words & _EN_CUES)
    scores = {"te": te, "hi": hi, "en": en}
    top = max(scores.values())
    if top == 0:
        return "en"
    leaders = [k for k, v in scores.items() if v == top]
    if len(leaders) > 1:
        return "mixed"
    # Strong secondary signal -> code-mixed.
    # Threshold raised from `second >= 1` to `>= 2` because a single
    # secondary keyword on short Tenglish/Hinglish acks ("haan ok",
    # "sari okay") was returning "mixed" → downstream collapsed to
    # English-led mix → TTS speaker flipped off-language per ack.
    # Requiring 2 secondary cues stabilises detection on 1-2 word turns.
    second = sorted(scores.values(), reverse=True)[1]
    if second >= 2 and top - second <= 1:
        return "mixed"
    return leaders[0]


def classify(text: str) -> Classification:
    lang = detect_language(text)
    words = set(re.findall(r"[a-z]+", (text or "").lower()))

    best_intent, best_hits = "unknown", 0
    for intent, kws in _INTENT_KEYWORDS.items():
        hits = len(words & kws)
        if hits > best_hits:
            best_intent, best_hits = intent, hits

    # Explicit-bye priority: "Okay fine bye." would tie affirm (okay) and
    # bye (bye) at 1 hit each; loop picked the FIRST tying intent
    # (affirm), so the agent missed the explicit bye signal and CTA-
    # pitched instead of closing. Force `bye` whenever an unambiguous
    # bye keyword appears — closing intent is not script-breaking the
    # way affirm/greeting/deny are (canned bye = warm goodbye).
    if words & _INTENT_KEYWORDS["bye"]:
        best_intent, best_hits = "bye", max(best_hits, 1)

    short = len(words) <= 3
    # Must be BOTH short AND have a keyword hit. The previous `or` fired
    # "repeat" canned ("malli cheppandi") on any long English sentence
    # containing the word "again", drowning out real questions like
    # "Can you check again what slots are available?". A real "repeat
    # please" turn is short by nature.
    is_trivial = best_intent in _GREETING_INTENTS and short and best_hits >= 1
    confidence = 0.9 if best_hits >= 2 else (0.7 if best_hits == 1 else 0.3)
    return Classification(
        language=lang,
        intent=best_intent,
        is_trivial=is_trivial,
        confidence=confidence,
    )
