"""Canned/rule responses — the ~100ms, no-LLM fast path.

Greetings, yes/no, thanks, bye, "hmm", repeat-requests don't need a model.
Answering them with a rotating set of short, language-matched lines is
both faster and more human than a round-trip to OpenAI. Responses rotate
so the agent never repeats the same line back-to-back (human-imperfection
model from the plan).
"""

from __future__ import annotations

from src.content import content_store
from src.router.classifier import Classification

# Anti-repeat memory per (intent,lang) — last index served. Pools come
# from the dynamic content store (LLM-generated offline -> Redis, with
# built-in defaults as fallback).
_last_idx: dict[tuple[str, str], int] = {}

# Greetings/affirm/deny are DELIBERATELY NOT canned: a generic
# "Hello sir, how can I help?" overrides the call's script/persona and
# the agent stops following its goal (real failure seen in production —
# a dental booking call answered "Let's chat!"). Only conversation-
# ending / clarification intents are safe to shortcut; everything else
# goes to the persona-driven LLM so it stays on-script and in-language.
_SAFE_CANNED_INTENTS = {"thanks", "bye", "repeat"}


def _lang_key(language: str | None) -> str:
    if not language:
        return "en"
    if language.startswith("te"):
        return "te"
    if language.startswith("hi"):
        return "hi"
    return "en"


def canned_response(
    cls: Classification, call_language: str | None = None
) -> str | None:
    """Return a short reply for SAFE trivial intents, else None (fall
    through to the LLM).

    `call_language` is the dashboard/campaign-configured language for
    this call — authoritative over the fragile keyword classifier, which
    mis-reads Tenglish and made Telugu calls reply in Hindi/English.
    """
    if not cls.is_trivial or cls.intent not in _SAFE_CANNED_INTENTS:
        return None
    lang = _lang_key(call_language or cls.language)
    options = content_store.canned(cls.intent, lang)
    if not options:
        return None
    if len(options) == 1:
        return options[0]

    # Deterministic sequential rotation: same intent twice in a row gets
    # the NEXT line, never a random pick (and never the same line twice).
    key = (cls.intent, lang)
    idx = (_last_idx.get(key, -1) + 1) % len(options)
    _last_idx[key] = idx
    return options[idx]
