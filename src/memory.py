"""Structured per-call memory + rolling summary + per-phone profile.

Raw chat history is slow and expensive to carry. Instead we keep a tiny
structured record — language, emotion, intent, caller name, and arbitrary
slots (order id, etc.) — plus a one/two line rolling summary. That, not
the full transcript, is what gets injected into the LLM prompt. It is
faster, cheaper, and more reliable.

Round 7 — PER-PHONE PROFILE (cross-call memory):
  At call END we also snapshot a tiny profile keyed by the CALLER's
  phone number (independent of call_id). On the NEXT call from the
  same phone the agent loads this profile and opens with a personalized
  line ("మరోసారి call chesaru, last time payment ki call chesaru,
  solve aindaa?") instead of starting cold. This is the biggest
  "is-this-really-AI?" defeater available without any architecture
  change — pure Redis, no schema migration.

Backed by Redis (per call id + per phone) so it survives a worker
hiccup, but degrades to in-process memory if Redis is unavailable —
never an error.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field

from src.config import settings

logger = logging.getLogger("memory")

_KEY = "callmem:"
_PHONE_KEY = "callerprofile:"        # Round 7 — cross-call memory by phone
_PHONE_TTL_SEC = 60 * 60 * 24 * 90   # 90 days; long enough to remember repeat callers

# Very small emotion heuristic. Real ML can replace this later; the
# rhythm engine + persona only need a coarse label.
_EMOTION_CUES = {
    "angry": {"worst", "useless", "ridiculous", "scam", "cheat", "bekar",
              "bakwas", "chetha", "waste", "angry", "complaint", "fed up"},
    "frustrated": {"again", "still", "already", "kab tak", "enni sarlu",
                   "phir se", "marokkasari", "not working", "problem"},
    "urgent": {"urgent", "asap", "immediately", "right now", "fast",
               "jaldi", "thwaraga", "emergency"},
    "confused": {"samajh nahi", "ardham kaledu", "confused", "what do you mean",
                 "matlab kya", "ela", "kaise"},
    "happy": {"thanks", "thank you", "great", "good", "super", "chala bagundi",
              "badhiya", "perfect", "awesome"},
}


def detect_emotion(text: str) -> str:
    t = (text or "").lower()
    for emotion, cues in _EMOTION_CUES.items():
        if any(cue in t for cue in cues):
            return emotion
    return "neutral"


# Cheap name capture: ONLY explicit "name is" patterns. "i am X" and
# "main X" were here too, but they fire on "I am suffering" / "I am here"
# / "main problem" and overwrite the real caller name (e.g. campaign-seeded
# "Nagasai" became "Suffering"). Self-introductions in practice always use
# an explicit name-marker — keep the noisy verb-fragment patterns out.
_NAME_RE = re.compile(
    r"(?:my name is|naa peru|naa peeru|mera naam hai|mera naam)\s+([a-z]{2,20})",
    re.IGNORECASE,
)


def extract_name(text: str) -> str | None:
    m = _NAME_RE.search(text or "")
    return m.group(1).strip().title() if m else None


@dataclass
class CallMemory:
    call_id: str
    language: str = "en"
    emotion: str = "neutral"
    intent: str = "unknown"
    name: str | None = None
    slots: dict = field(default_factory=dict)
    summary: str = ""

    def update_from_turn(self, text: str, language: str, intent: str) -> None:
        self.language = language or self.language
        self.intent = intent or self.intent
        emo = detect_emotion(text)
        if emo != "neutral":
            self.emotion = emo
        # Defensive: never overwrite an already-known name (campaign/dialer
        # seeds memory.name from the outbound metadata before turn 1; the
        # regex must not clobber that with a mid-call false positive).
        if not self.name:
            name = extract_name(text)
            if name:
                self.name = name
        # Rolling summary: keep it to the last user gist (1 line).
        self.summary = (text or "")[:160]

    def as_prompt(self) -> str:
        """Compact block injected as a system message before the LLM.

        Intentionally STABLE across turns: language/emotion/intent/name
        change rarely (only on real shifts), so OpenAI's prompt cache
        prefix holds → no TTFT compounding. The earlier "Last said:
        ..." line was REMOVED because it changed every single turn,
        churned the cache prefix, and pushed TTFT from ~1s to ~11s on
        long calls.
        """
        parts = [f"language={self.language}", f"emotion={self.emotion}",
                 f"intent={self.intent}"]
        if self.name:
            parts.append(f"caller_name={self.name}")
        if self.slots:
            parts.append(f"slots={json.dumps(self.slots, ensure_ascii=False)}")
        ctx = ", ".join(parts)
        return f"[CALL CONTEXT] {ctx}."


class MemoryStore:
    """Persists CallMemory to Redis with a safe in-memory fallback."""

    def __init__(self) -> None:
        self._redis = None
        self._local: dict[str, CallMemory] = {}

    async def _r(self):
        if self._redis is None:
            import redis.asyncio as redis

            self._redis = redis.from_url(
                settings.redis_url, decode_responses=True
            )
        return self._redis

    async def load(self, call_id: str) -> CallMemory:
        try:
            r = await self._r()
            blob = await r.get(_KEY + call_id)
            if blob:
                return CallMemory(**json.loads(blob))
        except Exception:
            logger.debug("memory load fell back to local", exc_info=True)
        return self._local.get(call_id) or CallMemory(call_id=call_id)

    async def save(self, mem: CallMemory) -> None:
        self._local[mem.call_id] = mem
        try:
            r = await self._r()
            await r.set(
                _KEY + mem.call_id,
                json.dumps(asdict(mem), ensure_ascii=False),
                ex=settings.semantic_cache_ttl_seconds,
            )
        except Exception:
            logger.debug("memory save fell back to local", exc_info=True)


# ─── Round 7: per-phone cross-call profile ──────────────────────────


@dataclass
class CallerProfile:
    """Minimal cross-call memory for a phone number.

    Intentionally tiny — only stable, useful facts. The full transcript
    of every prior call is NOT stored here (that would balloon Redis +
    explode prompt size + raise privacy questions); we keep the kind
    of detail a real human agent would actually remember between calls:
    last intent + last topic + name + language preference + last call
    timestamp + total call count.
    """

    phone: str
    name: str = ""
    language: str = ""
    last_intent: str = ""
    last_summary: str = ""
    last_call_at: float = 0.0
    call_count: int = 0

    def as_opener_hint(self) -> str:
        """Compact line injected into the persona instructions BEFORE
        the call begins. The LLM uses it to open warmly with continuity
        instead of a cold-start opener. Returns "" for new callers."""
        if self.call_count <= 0:
            return ""
        bits = [f"call_count={self.call_count}"]
        if self.name:
            bits.append(f"name={self.name}")
        if self.language:
            bits.append(f"preferred_language={self.language}")
        if self.last_intent and self.last_intent != "unknown":
            bits.append(f"last_intent={self.last_intent}")
        if self.last_summary:
            bits.append(f"last_topic={self.last_summary[:120]!r}")
        return (
            "RETURNING CALLER (recognized by phone). Open with continuity, "
            "not a cold-start intro. Briefly acknowledge they've called "
            "before and reference the LAST TOPIC naturally if it's still "
            "relevant. Stay in their preferred_language. DETAILS: "
            + ", ".join(bits)
        )


class PhoneProfileStore:
    """Persists CallerProfile to Redis keyed by phone number.

    Lifetime is 90 days so we recognize callers across weeks of
    inactivity. Redis failure degrades to local dict (which dies with
    the worker but at least keeps the current process correct)."""

    def __init__(self) -> None:
        self._redis = None
        self._local: dict[str, CallerProfile] = {}

    async def _r(self):
        if self._redis is None:
            import redis.asyncio as redis
            self._redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._redis

    @staticmethod
    def _norm_phone(phone: str) -> str:
        """Strip whitespace and a trailing '+', keep digits.
        Different campaigns may pass numbers as '+91987...' or
        '91987...' — normalize so the same caller maps to one profile."""
        if not phone:
            return ""
        return "".join(c for c in phone.strip() if c.isdigit())

    async def load(self, phone: str) -> CallerProfile:
        key = self._norm_phone(phone)
        if not key:
            return CallerProfile(phone="")
        try:
            r = await self._r()
            blob = await r.get(_PHONE_KEY + key)
            if blob:
                return CallerProfile(**json.loads(blob))
        except Exception:
            logger.debug("phone profile load fell back to local", exc_info=True)
        return self._local.get(key) or CallerProfile(phone=key)

    async def save_from_memory(
        self, phone: str, mem: CallMemory
    ) -> None:
        """Snapshot a CallMemory into the phone-keyed profile at call end."""
        key = self._norm_phone(phone)
        if not key:
            return
        existing = await self.load(phone)
        prof = CallerProfile(
            phone=key,
            name=mem.name or existing.name or "",
            language=mem.language or existing.language or "",
            last_intent=mem.intent or existing.last_intent or "",
            last_summary=mem.summary or existing.last_summary or "",
            last_call_at=time.time(),
            call_count=existing.call_count + 1,
        )
        self._local[key] = prof
        try:
            r = await self._r()
            await r.set(
                _PHONE_KEY + key,
                json.dumps(asdict(prof), ensure_ascii=False),
                ex=_PHONE_TTL_SEC,
            )
        except Exception:
            logger.debug("phone profile save fell back to local", exc_info=True)

    async def save_suggestion_from_memory(
        self, call_id: str, phone: str, mem: CallMemory
    ) -> None:
        """Snapshot a CallMemory into a suggested caller profile for review on the dashboard."""
        key = self._norm_phone(phone)
        if not key:
            return
        existing = await self.load(phone)
        prof = CallerProfile(
            phone=key,
            name=mem.name or existing.name or "",
            language=mem.language or existing.language or "",
            last_intent=mem.intent or existing.last_intent or "",
            last_summary=mem.summary or existing.last_summary or "",
            last_call_at=time.time(),
            call_count=existing.call_count + 1,
        )
        try:
            r = await self._r()
            await r.set(
                f"callerprofile:suggested:{call_id}",
                json.dumps(asdict(prof), ensure_ascii=False),
                ex=60 * 60 * 24 * 7,  # 7 days expiration
            )
            logger.info("Saved pending self-learning profile suggestion for call %s", call_id)
        except Exception:
            logger.debug("phone profile suggestion save failed", exc_info=True)


memory_store = MemoryStore()
phone_profile_store = PhoneProfileStore()
