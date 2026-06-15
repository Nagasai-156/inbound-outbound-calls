"""Agent worker entrypoint (Phase 2 baseline).

Wires the streaming pipeline into a LiveKit AgentSession so it can be
talked to in the console (no telephony yet). Later phases extend the
entrypoint with the FSM, Fast Intent Router, fillers/rhythm, KB, memory,
cancellation, audio hardening, and SIP dispatch — the extension points
are marked with `# PHASE n:` comments.

Run:
    python -m src.agent console     # talk locally, no phone
    python -m src.agent dev         # dev worker (LiveKit playground)
    python -m src.agent start       # production worker
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
)

try:
    from livekit.agents import StopResponse
except Exception:  # pragma: no cover - name varies across builds
    class StopResponse(Exception):  # type: ignore[no-redef]
        ...

from src.audio import AdaptiveBuffer, EchoGuard, build_room_input_options
from src.cache import semantic_cache
from src.cancellation import CancellationRegistry
from src.content import content_store
from src.config import settings
from src.cost import CallMeter
from src.backchannel import Backchanneler, pick_backchannel
from src.filler import filler_kind, pick_filler, should_filler
from src.fsm import ConversationFSM, State
from src.memory import CallMemory, memory_store
from src.pipeline.stabilizer import TranscriptStabilizer
from src.predictive import PredictivePrefetch
from src.persona.inbound import inbound_prompt
from src.persona.outbound import outbound_prompt
from src.pipeline.llm import build_llm
from src.pipeline.stt import build_stt
from src.pipeline.tts import build_tts, retune_tts
from src.pipeline.turn import (
    build_turn_detection,
    build_vad,
    endpointing_delay_for,
)
from src.rhythm import ResponseRhythm
from src.router.intent_router import IntentRouter
from src.router.intent_router import Route
from src.runtime_config import RuntimeConfig, load_runtime_config
from src.telemetry import CallTelemetry
from src.telephony.resilience import TelephonyResilience
from src.tools import tools_for

# Per-call call_id stamping: every record this process emits carries
# `%(call_id)s`. Outside a call it's `-`. The format is widened ONCE here
# so `grep call=<room>` reconstructs a clean per-call timeline across
# all named loggers (agent / tools / tts / db / …) without per-module
# wiring.
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s call=%(call_id)s %(message)s",
)
from src.log_context import install_call_id_logging, set_call_id  # noqa: E402
install_call_id_logging()
logger = logging.getLogger("agent")


def _message_text(new_message) -> str:
    """Extract plain text from a ChatMessage across plugin versions."""
    txt = getattr(new_message, "text_content", None)
    if isinstance(txt, str) and txt:
        return txt
    content = getattr(new_message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return " ".join(c for c in content if isinstance(c, str))
    return str(content or "")


# Short, normal-conversation acks the agent must NEVER treat as garbage.
# Carefully scoped: these are exactly the words a caller says back at the
# start of a yes/no flow; anything else <= 2 chars is suspicious.
_SHORT_ACK_ALLOW = {
    # Telugu
    "ఆ", "హా", "హ", "ఏ",
    # Hindi
    "हाँ", "ही", "ज",
    # Roman / English
    "ok", "no", "ha", "ja", "ya", "ya.", "ok.",
}

# Common English words a real caller might say standalone. Anything not
# in here AND not an Indic word AND short → suspected STT mishear.
_COMMON_ENGLISH = {
    "okay", "yes", "no", "sure", "hi", "hey", "hello", "hmm", "uhh",
    "haan", "ledhu", "vaddu", "thanks", "thank", "bye", "wait", "stop",
    "ok", "k", "fine", "good", "right", "true", "false", "maybe",
    # Days
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    # Times
    "am", "pm", "morning", "evening", "afternoon", "night", "today", "tomorrow",
    # Yes/no in other forms
    "okies", "okk", "kk", "ya", "yep", "yup", "nope",
}

_HAS_INDIC = re.compile(r"[ఀ-౿ऀ-ॿ]")
_HAS_ALPHA = re.compile(r"[A-Za-zఀ-౿ऀ-ॿ]")
_ROMAN_TOKEN = re.compile(r"\b[A-Za-z]+\b")


def _looks_garbled(text: str) -> bool:
    """Heuristic for STT garbage / mishears that should NOT reach the LLM.

    Catches the bad patterns observed on real calls (`'ఆ Oppo'`, `'mm'`,
    `'sugar'`, random brand-like English tokens mid-Telugu) without
    flagging legitimate short acks (`'ఆ'`, `'okay'`, `'hello'`, etc.).
    """
    t = (text or "").strip()
    if not t:
        return True
    n = len(t)
    if n <= 2:
        return t.lower() not in _SHORT_ACK_ALLOW and t not in _SHORT_ACK_ALLOW
    # No alphabetic character at all (pure punctuation / digits / emoji)
    if not _HAS_ALPHA.search(t):
        return True
    has_indic = bool(_HAS_INDIC.search(t))
    words = t.split()
    # Single short Roman-only token that isn't a common English word
    # — typical of a one-shot STT mishear like "Oppo" / "mm" / "ssr".
    if not has_indic and len(words) == 1 and n <= 6:
        if t.lower() not in _COMMON_ENGLISH:
            return True
    # Mixed-script short utterance where ALL Roman token(s) are unknown
    # — catches "ఆ Oppo" (1 Indic short + 1 weird Roman). If even ONE
    # Roman token is a common English word (skin/doctor/consultation),
    # the whole utterance is likely legitimate Tenglish — accept it.
    if has_indic and len(words) <= 4:
        roman_tokens = _ROMAN_TOKEN.findall(t)
        if roman_tokens:
            known_present = any(
                r.lower() in _COMMON_ENGLISH for r in roman_tokens
            )
            if not known_present:
                return True
    return False


def _detect_conversational_variety(text: str, call_lang: str | None) -> str:
    """Classify the exact language variety:
       te (pure Telugu), te-mix (Tenglish), hi (pure Hindi), hi-mix (Hinglish), or en (English).
    """
    t = (text or "").strip()
    if not t:
        return call_lang or "en"

    # High-stability bypass: if the turn consists ONLY of short greetings or one-word acks,
    # do NOT switch languages. Keep the currently active conversational language.
    clean_words = [w.lower() for w in re.findall(r"[A-Za-z0-9ఀ-౿ऀ-ॿ]+", t)]
    if clean_words and all(w in {
        "ok", "okay", "yes", "no", "bye", "ha", "haa", "ji", "sir", "madam", "maam",
        "ఆ", "haan", "అవును", "సరే", "theek", "thik", "achha", "hello", "hi", "hey",
        "namaste", "namaskaram", "sure", "alright",
    } for w in clean_words):
        return call_lang or "en"

    has_telugu = bool(re.search(r"[ఀ-౿]", t))
    has_hindi = bool(re.search(r"[ऀ-ॿ]", t))

    # Extract romanized words
    roman_words = [w.lower() for w in re.findall(r"\b[A-Za-z]+\b", t)]

    # Romanized Telugu/Hindi cues. Expanded with high-confidence
    # conversational words that Sarvam STT codemix mode emits in Roman
    # script for spoken Indian languages. Each word picked to be
    # unambiguous (very unlikely to appear in English speech), so the
    # detector classifies real Telugu/Hindi turns correctly even when
    # the original 14-word list missed them and the system mis-fired
    # to "en" → wrong-language reply.
    te_cues = {
        # Originals
        "cheppandi", "cheppu", "ekkada", "undi", "unnaru", "kavali",
        "ela", "enti", "avunu", "ledu", "sari", "repu", "nenu",
        "meeru", "miru", "meeku", "naaku", "vaariki", "vaaru",
        "anna", "andi", "bhayya", "garu", "gaaru",
        # Common verbs / states
        "chesthunna", "chestha", "cheyali", "cheyochu", "chesina",
        "cheyandi", "cheyandhi", "chesaru", "chesinaru", "chesthamu",
        "chestharu", "kaavali", "kavalisindi", "kavalisina",
        "vasthe", "vastha", "vasthunna", "vellali", "velthe", "vellandi",
        "chudali", "chudandi", "chusinanu", "vinnanu",
        "telusu", "theliyaledu", "adagandi", "ardhamu", "ardhamundi",
        # Conversational glue
        "konchem", "baga", "baagundi", "bagunnaru", "ipudu", "appudu",
        "eppudu", "antha", "evaru", "edi", "eedi", "ila", "ipuduu",
        "twaraga", "venatane", "tappakunda", "endhuku", "elaa",
        "evarainaa", "ostundi", "ostundhi", "ledhu", "ledu",
        "avtundi", "avthundi", "vacchindi", "vachindi", "vacchaaru",
        "kalusukundam", "kalvali", "kalisi", "ayipoindi", "ayipoyindi",
        # Time words (high freq in voice calls)
        "ganta", "gantaki", "gantalu", "neddu", "monna", "remmaala",
        # Exclamations (very Telugu)
        "ayyo", "ammo", "abba", "arey", "appudaa", "ledhu",
        # Family / address (very Telugu)
        "amma", "nanna", "akka", "thammudu", "annayya", "vadina",
        # Greetings (Telugu-specific)
        "namaskaram", "vandanam", "vandanamulu", "dhanyavadalu",
    }
    hi_cues = {
        # Originals
        "haan", "nahi", "nahin", "kya", "kaha", "kahan", "hai",
        "boliye", "thik", "theek", "acha", "accha", "bhai", "bhaiya",
        "mera", "mujhe", "kaise", "ji",
        # Common verbs / states
        "karna", "karenge", "karte", "kartey", "kiya", "kar",
        "hoga", "hogi", "hota", "hota", "raha", "rahi", "rahe",
        "hain", "hua", "huye", "huyi", "milega", "milegi",
        "diya", "diye", "gaya", "gayi", "gaye", "samjha", "samjhi",
        "chahiye", "chahta", "chahti", "rahna", "lena", "dena",
        # Pronouns / determiners (very Hindi)
        "yeh", "woh", "kuch", "kucch", "sirf", "bas", "ya",
        "abhi", "kabhi", "phir", "sab", "namaste",
        # Time / amounts
        "kal", "aaj", "jaroor", "zaroor", "thoda", "jyada", "zyada",
        "jaldi", "abhi", "kabhi", "phir", "tab", "jab", "wapas",
        # Polite forms
        "dijiye", "kijiye", "bataiye", "sahi", "achha", "thik",
        # Family / honorifics
        "saab", "didi", "bhaiyya", "uncle", "aunty",
    }

    # English business or non-cue words
    en_words = [w for w in roman_words if w not in te_cues and w not in hi_cues and w not in {"ok", "okay", "ha", "yes", "no", "bye", "sir", "madam", "maam"}]

    # Count of English/Roman business words
    en_count = len(en_words)

    # 1. Indic scripts present.
    # A leading spoken ack ("ఆ", "హా", "సరే") on an otherwise English
    # question must NOT drag the reply into Telugu — live bug: caller
    # said "ఆ what is the treatment procedure?" and got a Telugu reply.
    # Mirror the language of the CONTENT, not the ack.
    _TE_ACKS = {"ఆ", "హా", "హాఁ", "సరే", "అవును", "ఓకే", "ఊ", "ఆఁ", "ఓ"}
    _HI_ACKS = {"हाँ", "हा", "जी", "अच्छा", "ठीक", "हम्म"}
    if has_telugu:
        te_tokens = re.findall(r"[ఀ-౿]+", t)
        if en_count >= 2 and all(tok in _TE_ACKS for tok in te_tokens):
            return "en"
        if en_count >= 1:
            return "te-mix"
        return "te"

    if has_hindi:
        hi_tokens = re.findall(r"[ऀ-ॿ]+", t)
        if en_count >= 2 and all(tok in _HI_ACKS for tok in hi_tokens):
            return "en"
        if en_count >= 1:
            return "hi-mix"
        return "hi"

    # 2. Roman script only
    if roman_words:
        # Check matching Indic cues
        te_match = len(set(roman_words) & te_cues)
        hi_match = len(set(roman_words) & hi_cues)

        # Pure English check (has English words and absolutely no Indic cues)
        if en_count >= 2 and te_match == 0 and hi_match == 0:
            return "en"

        # Determine Indic base language
        if te_match >= hi_match and (te_match > 0 or call_lang == "te"):
            if en_count >= 1:
                return "te-mix"
            return "te"
        elif hi_match > te_match or (hi_match > 0 or call_lang == "hi"):
            if en_count >= 1:
                return "hi-mix"
            return "hi"

    return call_lang or "en"


class VoiceAgent(Agent):
    """The conversational agent.

    The Fast Intent Router runs in `on_user_turn_completed`: trivial and
    cached turns are answered WITHOUT the LLM (StopResponse skips it); the
    rest fall through to the LLM, with a conditional filler covering the
    real latency. Rhythm adds small human pacing variability.
    """

    def __init__(
        self,
        instructions: str,
        router: IntentRouter,
        meter: CallMeter,
        memory: CallMemory,
        predictive: PredictivePrefetch,
        echo: EchoGuard,
        telemetry: CallTelemetry,
        cfg: RuntimeConfig,
        stabilizer: TranscriptStabilizer | None = None,
    ) -> None:
        # Tool-gating: expose ONLY the tools this use-case needs. A
        # survey/sales/custom call is never handed booking tools, so it
        # structurally cannot hallucinate/call them.
        super().__init__(
            instructions=instructions,
            tools=tools_for(
                getattr(cfg, "use_case_type", "custom"),
                getattr(cfg, "enabled_tools", ""),
            ),
        )
        self._router = router
        self._rhythm = ResponseRhythm()
        self._meter = meter
        self._memory = memory
        self._predictive = predictive
        self._echo = echo
        self._tel = telemetry
        self._cfg = cfg
        # Lazily-built fallback LLM (Azure gpt-4o-mini). Used ONLY when the
        # dashboard-selected primary LLM (e.g. Groq free tier) fails a turn
        # with a rate-limit/connection error BEFORE producing any token —
        # so the call never goes silent. Dashboard choice stays primary.
        self._fallback_llm = None
        # Optional: lets the mishear gate read stabilizer.last_final_avg_confidence
        # to force a "please repeat" path on low-confidence transcripts.
        self._stabilizer = stabilizer
        # Per-turn live Appointment-table snapshot cache. The structural
        # anti-hallucination guarantee: every LLM turn for an appointment
        # use-case sees a FRESHLY-READ snapshot of the table physically
        # in its chat context (see `llm_node` override below) — the
        # model cannot fabricate availability/bookings because the truth
        # is right there in its window. Refreshed at most every 18s
        # (rapid micro-turns share one read), and invalidated on demand
        # (a booking change forces a re-read). The 5-query snapshot read
        # sat INSIDE llm_node on every cache-miss turn, adding ~50-150ms to
        # that turn's TTFT; a 6s TTL meant ~2-3 such slow turns per call.
        # 18s (still invalidated on book/reschedule/cancel) cuts those
        # DB-read latency spikes to ~1 per call with zero staleness risk.
        self._appt_snap_text: str = ""
        self._appt_snap_ts: float = 0.0
        self._APPT_SNAP_TTL = 18.0
        # Per-stage latency instrumentation (last LLM turn) — exposed so the
        # dashboard can show the micro-breakdown hidden inside "LLM TTFT".
        self._last_assembly_ms: float = 0.0
        self._last_snapshot_ms: float = 0.0
        self._last_prompt_tokens: int = 0
        # Phase 5: detected language of the most-recent caller turn,
        # injected into chat_ctx via llm_node so Rule A (instant
        # language switch) has a per-turn anchor and the LLM cannot
        # drift on short/mixed input.
        self._last_turn_lang: str | None = None
        # Continuity tracking: only inject the language marker when the
        # language ACTUALLY changes vs the previous turn. Saves ~50-100ms
        # TTFT + ~50 tokens on continuity turns (most turns in practice).
        self._prev_turn_lang: str | None = None
        # Filler-text tracking: fillers ("hmm okay sir", "sare oka second")
        # are UX latency covers, NOT conversation turns. They MUST NOT be
        # written to the Transcript table. _say() correctly skips telemetry
        # for fillers, but LiveKit's conversation_item_added event ALSO
        # fires for fillers and the global _on_item_added handler writes
        # them. We tag every filler text here before session.say() emits
        # the event, then _on_item_added consults this deque and skips
        # the DB write for matching texts. Bounded to the last 30 fillers
        # so memory stays tiny.
        from collections import deque as _deque
        self._recent_filler_texts: _deque = _deque(maxlen=30)
        # Caller-turn counter used by the garbage-detection guard so the
        # FIRST caller utterance (opener acks like "హా / okay") never
        # gets flagged as garbage. The heuristic is anti-mishear, not
        # anti-shortness — it should only activate from turn 2 onward.
        self._caller_turns_seen: int = 0
        # Consecutive mishear-gate fires. Real-call evidence showed the
        # gate firing 4× back-to-back with no caller turn between them
        # (each fire's "Sorry sir, malli cheppandi" leaked back via STT
        # → triggered the next fire). EchoGuard's new post-stop window
        # should catch most of these, but as a final guard: 3 mishears
        # in a row without a successful caller turn → close the call
        # politely instead of looping forever.
        self._mishear_streak: int = 0
        self._MISHEAR_STREAK_LIMIT: int = 3
        # Pending filler task — tracked so we can cancel it if the LLM
        # answers before it plays (avoids filler leaking after real reply).
        self._pending_filler: asyncio.Task | None = None
        # Caller-turn index of the last filler we actually spoke. Used to
        # keep fillers HUMAN: a real person doesn't say "hmm" before every
        # single answer — backchannels are occasional. Firing a filler on
        # every LLM turn (while the reply ALSO opens with its own nod)
        # stacks two acknowledgements per turn = the #1 robotic tell
        # callers reported. The cadence gate below uses this to (a) never
        # fire two turns in a row and (b) otherwise fire only part of the
        # time, so most turns lead with just the LLM's natural nod.
        self._last_filler_turn: int = -10

    async def _say(
        self,
        text: str,
        *,
        skip_rhythm: bool = False,
        is_filler: bool = False,
        cacheable: bool = False,
    ) -> None:
        """Speak + tell the EchoGuard what we said (so it can recognise
        the echo of our own voice) + log it to telemetry.

        Telemetry is a Redis + Postgres round-trip — it MUST NOT sit in
        front of the audio. Fire-and-forget it so the very first sound
        starts immediately; the transcript line lands a few ms later.

        skip_rhythm: filler audio is meant to cover LLM latency, so it
        must start IMMEDIATELY. The natural ~50–180ms emotion beat is
        kept for canned/warm/cache turns (intentional anti-robotic feel),
        but filler skips it so it actually beats the LLM first token.

        is_filler: fillers are UX latency covers, NOT conversation turns.
        They must NOT be added to the LLM's chat context (prevents the
        model seeing "Hmm okay sir..." as an agent turn and getting
        confused). Also skips telemetry logging for the same reason.
        """
        # Fillers cancelled by the next turn should not speak at all.
        if is_filler and self._pending_filler:
            current = asyncio.current_task()
            if current and current is not self._pending_filler:
                return
        # Strip markdown/formatting tokens before ANY downstream use (echo
        # guard, cache key, telemetry, TTS). Some models (e.g. Bedrock
        # Ministral) emit **bold** / *italic* / `code` / ~strike which TTS
        # would otherwise read aloud as "asterisk asterisk confirmed". The
        # class matches ONLY * _ ` ~ so Indic scripts + Roman business terms
        # are untouched.
        if text:
            text = re.sub(r"\*\*|__|[*_`~]", "", text)
        self._echo.on_agent_started(text)
        # Tag filler text BEFORE session.say emits conversation_item_added
        # so the global _on_item_added handler can skip the Transcript
        # write for fillers (they are UX latency covers, not turns).
        if is_filler and text:
            self._recent_filler_texts.append(text)
        if not is_filler:
            self._tel.spawn(self._tel.turn("agent", text))
        if not skip_rhythm:
            await self._rhythm.think_pause()
        # TTS AUDIO CACHE (multimodal cache): for fixed repeated phrases
        # (fillers / canned / warm answers) replay cached audio instead
        # of paying the full TTS first-byte latency (~270-460ms) again.
        # Off by default (cfg.tts_audio_cache) — see src/tts_cache.py.
        # Falls back to normal streaming synth on any error.
        if cacheable and getattr(self._cfg, "tts_audio_cache", False) and text:
            try:
                from src.tts_cache import say_cached

                lang = self._memory.language or self._cfg.default_language
                await say_cached(
                    self.session,
                    self.session.tts,
                    text,
                    model=self._cfg.tts_model,
                    speaker=self._cfg.speaker_for(lang),
                    language=lang,
                    allow_interruptions=True,
                    add_to_chat_ctx=not is_filler,
                )
                return
            except Exception:
                logger.debug(
                    "tts audio cache path failed; using live synth",
                    exc_info=True,
                )
        await self.session.say(
            text,
            allow_interruptions=True,
            add_to_chat_ctx=not is_filler,
        )

    async def _appt_live_snapshot(self) -> str:
        """Read the Appointment table LIVE and produce a short snapshot
        block the LLM sees in its context every turn. This is the
        structural guarantee that "table lo undi vs agent says different"
        cannot happen — the truth physically sits in the LLM's window.

        Coverage:
          - This caller's existing upcoming bookings (id/date/time).
          - Today + tomorrow free-slot counts and which slots are taken.
        Cached for `_APPT_SNAP_TTL` seconds so 5 micro-turns within one
        breath share a single DB read.
        """
        now = time.monotonic()
        if (
            self._appt_snap_text
            and (now - self._appt_snap_ts) < self._APPT_SNAP_TTL
        ):
            return self._appt_snap_text
        try:
            from datetime import timedelta
            from src import db
            from src.clock import today_tz
            from src.tools import caller_phone_var

            phone = caller_phone_var.get() or ""
            today = today_tz().isoformat()
            tomorrow = (today_tz() + timedelta(days=1)).isoformat()
            
            # Fetch all details in parallel using asyncio.gather to avoid 5 sequential round-trips (reducing latency by ~80%)
            tasks = []
            if phone:
                tasks.append(db.appt_find_by_phone(phone))
            else:
                async def _empty_list():
                    return []
                tasks.append(_empty_list())
            
            tasks.extend([
                db.appt_booked_times(today, fresh=True),
                db.appt_booked_times(tomorrow, fresh=True),
                db.appt_available_slots(today, fresh=True),
                db.appt_available_slots(tomorrow, fresh=True),
            ])
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Unpack results with safe fallbacks
            caller_appts = results[0] if not isinstance(results[0], Exception) else []
            today_taken = sorted(results[1]) if not isinstance(results[1], Exception) else []
            tomo_taken = sorted(results[2]) if not isinstance(results[2], Exception) else []
            today_free = results[3] if not isinstance(results[3], Exception) else []
            tomo_free = results[4] if not isinstance(results[4], Exception) else []

            # All times shown to the model must be 12h AM/PM — it misread
            # raw '15:00' as Telugu 'ఉదయం మూడు' on a live call.
            from src.tools import ampm12 as _ampm12, ampm12_list as _ampm12_list

            if caller_appts:
                # Compact inline form so ids stay silent reference data
                # the model uses but never reads aloud (the earlier
                # numbered list was being parroted back verbatim).
                book_inline = "; ".join(
                    f"{a['date']} {_ampm12(a['time'])} ({a['reason'] or 'visit'}) id={a['id']}"
                    for a in caller_appts
                )
                callers = (
                    f"CALLER HAS {len(caller_appts)} BOOKING(S): {book_inline}. "
                    "Acknowledge in ONE short sentence before any new "
                    "booking. NEVER add a duplicate on a date/time they "
                    "already have — use reschedule_appointment(id) or "
                    "ask which to change. NEVER read ids aloud."
                )
            else:
                callers = "caller has no existing bookings."

            # SNAPSHOT compacted ~70% (was ~600 tokens, now ~180) while
            # keeping ALL behavioral guarantees: (1) anti-hallucination
            # READ-ONLY rule, (2) tool-must-fire-after-verbal-filler rule
            # (the dead-air root cause this session fixed), (3) compact
            # availability data. Real call evidence (call out-9e617e48b6)
            # showed each turn requesting 8300+ tokens, hitting org TPM
            # cap; this trim is a structural cost-of-doing-business cut.
            snap = (
                "INTERNAL CONTEXT (silent reference — don't recite verbatim). "
                f"LIVE APPT TABLE: {callers} "
                f"today={today} free={len(today_free)} "
                f"taken=[{_ampm12_list(today_taken)}]; "
                f"tomorrow={tomorrow} free={len(tomo_free)} "
                f"taken=[{_ampm12_list(tomo_taken)}]. "
                "Other dates → call check_appointment_slots. "
                "DOCTOR NAME: the appointment's doctor is ONLY whoever "
                "your script/booking names — NEVER switch to a different "
                "staff member mid-call (live bug: agent drifted from "
                "Dr. Anjali to Dr. Lakshmi Prasad on topic change). "
                "Mention other doctors only if the caller asks about them. "
                "READ-ONLY: to book/reschedule/cancel you MUST call the "
                "tool and wait for 'TOOL CONFIRMED' this turn — NEVER say "
                "'booked/rescheduled/cancelled' (any language) without it. "
                "ANSWER-FIRST (most important): if the caller asks ANYTHING "
                "(where are you calling from / what services / fee / how / "
                "what is X), ANSWER it directly in 1-2 short sentences "
                "FIRST. Do NOT push a time/slot unless the caller asks to "
                "book or agrees to a time. If you already offered slots, "
                "just wait for their reply — NEVER repeat the same 'which "
                "time' sentence again. NEVER say a tool name, the word "
                "'checking', or any system-status line (e.g. 'system slow') "
                "out loud — silently call the tool or answer naturally."
            )
            self._appt_snap_text = snap
            self._appt_snap_ts = now
            return snap
        except Exception:
            logger.debug("appt live snapshot failed", exc_info=True)
            return self._appt_snap_text  # last good (possibly empty)

    def _invalidate_appt_snapshot(self) -> None:
        """Force the next LLM turn to re-read the table — call this
        whenever a booking changes (book/reschedule/cancel) so the agent
        cannot keep referring to stale 'free' counts."""
        self._appt_snap_ts = 0.0
        self._appt_snap_text = ""

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Inject per-turn structured context into the LLM:
          - Appointment-family use-cases: LIVE Appointment-table snapshot
            (anti-hallucination — model SEES the table).
          - Phase 5: per-turn detected language (anchors Rule A so the
            model cannot drift on short/mixed input).
          - Phase 8: structured CallMemory (emotion/intent/name/last-said)
            so the model reacts to evolving caller mood without explicit
            prompt cues.

        All injections live on a `.copy()` of chat_ctx so they affect only
        THIS LLM call — no persistent pollution.
        """
        uc = (getattr(self._cfg, "use_case_type", "custom") or "").lower()
        # ── PER-STAGE LATENCY INSTRUMENTATION ───────────────────────
        # The measured "LLM TTFT" is really (prompt-assembly + snapshot DB
        # read + the real model call). These two sub-stages were invisible;
        # stopwatch them so every micro-component is detectable.
        _asm_t0 = time.monotonic()
        _snap_ms = 0.0
        forked = False
        if uc in ("appointment", "reminder", "reschedule"):
            _snap_t0 = time.monotonic()
            snap = await self._appt_live_snapshot()
            _snap_ms = (time.monotonic() - _snap_t0) * 1000.0
            if snap:
                if not forked:
                    chat_ctx = chat_ctx.copy()
                    forked = True
                chat_ctx.add_message(role="system", content=snap)
        # Phase 5: per-turn language marker for Rule A anchoring.
        # APPENDED system messages were consistently IGNORED by
        # gpt-4o-mini — OpenAI weights mid-conversation system msgs
        # lower than the initial persona. Fix: INSERT at position 1
        # (right after the persona system message) so it has the same
        # high-priority position as the persona itself. Caller's 1-word
        # Telugu ack ("అవును") no longer flips agent to English.
        # Latency optimisation: SKIP injection when the language is the
        # same as the previous turn — saves ~50-100ms TTFT + ~50 tokens
        # per continuity turn (which is the majority of real calls).
        # FIRST-TURN RACE FIX: preemptive_generation fires llm_node BEFORE
        # on_user_turn_completed sets _last_turn_lang. On turn 1 the lang
        # was therefore None → no LANGUAGE-OVERRIDE marker → LLM defaulted
        # to the English persona prompt and replied in English even when
        # the caller (and the campaign) was Telugu. Fall back to the
        # call's configured default language so the FIRST preemptive draft
        # is already pinned to the right script.
        # LANGUAGE for THIS reply — detect from the CURRENT user turn in
        # chat_ctx, NOT the stale self._last_turn_lang. Preemptive
        # generation runs llm_node BEFORE on_user_turn_completed updates
        # _last_turn_lang, so the old code lagged by one turn: a caller
        # switching to Hindi/English got the reply in the PREVIOUS
        # language (real bug seen on call out-024ade9caa — caller asked
        # in Hindi, got Telugu, and gave up). Detecting off the live
        # message honours the switch on the SAME reply (Rule A).
        _cur_user_text = ""
        try:
            for _it in reversed(chat_ctx.items):
                if getattr(_it, "role", None) == "user":
                    _cur_user_text = _message_text(_it) or ""
                    break
        except Exception:
            _cur_user_text = ""
        _call_lang = (
            self._cfg.default_language
            if self._cfg.default_language in ("te", "hi", "en")
            else "en"
        )
        if _cur_user_text.strip():
            lang = _detect_conversational_variety(
                _cur_user_text, self._last_turn_lang or _call_lang
            )
        else:
            lang = self._last_turn_lang or (
                self._cfg.default_language
                if self._cfg.default_language in ("te", "hi", "en")
                else None
            )
        # PRODUCT RULE: the dashboard's "te"/"hi" options ARE Tenglish/
        # Hinglish (LANGUAGES in dashboard/lib/options.ts say "Telugu +
        # English" / "Hindi + English"). A PURE-script reply
        # transliterates English business words ("advanced" ->
        # "అడ్వాన్స్‌డ్", "Botox" -> "బోటాక్స్") which sounds foreign and
        # bookish — exactly what operators DON'T want. So even when the
        # caller speaks plain Telugu/Hindi, the agent still replies in
        # natural code-mix (English business terms stay in English
        # script). Collapse pure te/hi -> te-mix/hi-mix. English ("en")
        # callers are untouched.
        if lang == "te":
            lang = "te-mix"
        elif lang == "hi":
            lang = "hi-mix"
        # ALWAYS inject the language lock marker on every single turn!
        # Skipping it allowed gpt-4o-mini to drift to English on subsequent
        # turns because its system prompt is written in English. Reminding
        # it on every turn keeps the language 100% stable.
        if lang:
            self._prev_turn_lang = lang
        if lang:
            if not forked:
                chat_ctx = chat_ctx.copy()
                forked = True
            if lang == "en":
                marker = (
                    "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: en. "
                    "The caller spoke English. Reply 100% English. "
                    "ZERO Telugu/Hindi/Indic words. ZERO Indic script. "
                    "This overrides Rule A and the campaign default."
                )
            elif lang == "te":
                # HOUSE STYLE (user direction 2026-06-14): even a pure-
                # Telugu caller gets natural conversational TENGLISH, not
                # stiff pure-Telugu-script — real Hyderabad speech mixes
                # English nouns. Pure formal Telugu read as a news-reader
                # monologue and was the #1 "robotic" tell.
                marker = (
                    "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: te (natural Tenglish). "
                    "Reply in warm, natural spoken Telugu the way a real Hyderabad person talks — Telugu script base with English business words mixed in (Roman script): appointment, slot, confirm, book, reschedule, cancel, checkup, doctor, details, free, time. Do NOT translate these into stiff Telugu. "
                    "Keep a light, natural ~25-30% code-mix — mostly Telugu, English only for the business/tech nouns a real person would say in English. "
                    "NUMBERS/TIMES — SPEAK AS WORDS, NEVER DIGITS: ✗ '10:30 AM' / '2 PM'  ✓ 'ఉదయం పదిన్నరకి' / 'మధ్యాహ్నం రెండు గంటలకి'. Dates: tomorrow -> రేపు. "
                    "BANNED bookish words: 'మరియు' (say 'and' or just pause), 'పునఃషెడ్యూల్' (use 'reschedule'), 'ధృవీకరించడం' (use 'confirm'), 'రద్దు' (use 'cancel'), long formal titles. "
                    "Max 1-2 short sentences. NEVER list 3+ items in one breath — mention one or two, then ask a question. "
                    "'అండి' AT MOST ONCE per reply — repeating it every clause sounds robotic. "
                    "NEVER start a reply with 'ఆ అండి' / 'హా అండి' and never open two replies with the same word — vary your openers like a real person."
                )
            elif lang == "te-mix":
                marker = (
                    "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: te-mix. "
                    "The caller spoke Tenglish (a combination of Telugu and English). Reply in natural, completely code-mixed Tenglish. "
                    "You MUST use English script (Roman characters) for all core business terms, nouns, and action verbs (e.g., 'appointment', 'confirm', 'reschedule', 'cancel', 'booking', 'help', 'details', 'slots', 'free'). "
                    "NUMBERS/TIMES — SPEAK AS WORDS, NEVER DIGITS: write every time as natural spoken Telugu words, NEVER raw digits / colons / AM / PM. "
                    "✗ '10:00 AM' / '10:30 AM' / '2 PM'  ✓ 'ఉదయం పది గంటలకి' / 'ఉదయం పదిన్నరకి' / 'మధ్యాహ్నం రెండు గంటలకి'. "
                    "Use Telugu script for dates (tomorrow -> రేపు), connectors (or -> లేదా), pronouns, and conversational glue. "
                    "Speak with a fluent, natural 40-50% code-mix. Banned are stiff bookish Telugu words like 'పునఃషెడ్యూల్' or 'ధృవీకరించడం'. "
                    "NEVER dump a numbered / bulleted list — offer at most ONE or TWO times in a short sentence. "
                    "'అండి' AT MOST ONCE per reply — repeating it on every clause sounds robotic. "
                    "NEVER start a reply with 'ఆ అండి' / 'హా అండి' and never open two replies with the same word — vary your openers like a real person."
                )
            elif lang == "hi":
                marker = (
                    "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: hi. "
                    "The caller spoke pure, complete Hindi. Reply completely in Hindi/Devanagari script (देवनागरी). "
                    "CRITICAL: Use absolutely ZERO English script/Roman characters (A-Z). Everything you write MUST be in Devanagari script. "
                    "If you use English loan words, write them phonetically in Devanagari script (e.g. 'अपॉइंटमेंट' / 'बुकिंग', 'कन्फर्म', 'रीशेड्यूल', 'कैंसिल', 'डेट', 'टाइम'). "
                    "You MUST translate dates (e.g., tomorrow -> कल), times (e.g., 10:30 AM -> साढ़े दस बजे / 10:30 बजे), and connectors (or -> या) into Devanagari script. "
                    "Banned are stiff, bookish native words like 'पुष्टि' (use 'कन्फर्म'), 'रद्द' (use 'कैंसिल'). "
                    "Speak with absolute, natural, complete Hindi script flow. Use 'जी' politely."
                )
            elif lang == "hi-mix":
                marker = (
                    "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: hi-mix. "
                    "The caller spoke Hinglish (a combination of Hindi and English). Reply in natural, completely code-mixed Hinglish. "
                    "You MUST use English script (Roman characters) for all core business terms, nouns, and action verbs (e.g., 'appointment', 'confirm', 'reschedule', 'cancel', 'booking', 'help', 'details', 'slots', 'free'). "
                    "You MUST use Devanagari script for dates (tomorrow -> कल), connectors (or -> या), pronouns, and conversational glue. "
                    "NUMBERS/TIMES - SPEAK AS WORDS, NEVER DIGITS: write times as natural spoken Hindi words (सुबह दस बजे, साढ़े दस बजे), NEVER raw digits / colons / AM / PM (NOT '10:00 AM'). "
                    "NEVER dump a numbered / bulleted list - offer at most ONE or TWO times in a short sentence. "
                    "Speak with a fluent, natural 40-50% code-mix."
                )
            else:
                marker = (
                    f"LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: {lang}. "
                    f"Reply in the matching {lang} mode. "
                    "This overrides Rule A and the campaign default."
                )
            try:
                from livekit.agents.llm import ChatMessage as _ChatMsg
                # Insert AFTER the persona (item 0). If the structure
                # changes upstream we fall back to append.
                chat_ctx.items.insert(
                    1, _ChatMsg(role="system", content=[marker])
                )
            except Exception:
                chat_ctx.add_message(role="system", content=marker)
        # Gender-aware honorifics + verb agreement + pronouns — once F0
        # detection lands (~2s into the caller's first utterance), the
        # directive is injected so the agent stops defaulting to "sir"
        # for female callers and vice-versa, in EVERY language they
        # might speak. Detection is language-independent (pitch) and the
        # directive covers Telugu, Hindi, English, Tenglish and Hinglish
        # — caller switching languages mid-call stays correctly addressed.
        # "unknown" → no injection, neutral honorifics fall through.
        # GENDER markers — compacted to ~60 tokens each (was ~300+).
        # Real evidence (call out-9e617e48b6) showed gpt-4o burning ~8300
        # tokens per turn, hitting org TPM cap (30k/min) after 3-4 calls
        # → 429 retry storms → 14s dead-air. Honorifics + Hindi-verb
        # agreement preserved; redundant multi-format examples removed.
        # Same behavioral bar (correct address never drifts), lower TPM
        # footprint per turn, works on any model.
        g = getattr(self._cfg, "caller_gender", "unknown")
        # Telugu address is ALWAYS గారు — it is gender-neutral and
        # correct for everyone. Voice-pitch gender detect misfired on a
        # live call (male caller, f0=258Hz from background audio) and
        # the agent said "Sai మేడం" — never let a pitch guess pick a
        # gendered Telugu honorific.
        if g == "female":
            gmark = (
                "GENDER=female (voice-pitch guess, may be wrong). "
                "తెలుగు: ALWAYS గారు/అండి — NEVER మేడం, NEVER సర్. "
                "Hindi जी, English ma'am or no honorific. "
                "Hindi verbs feminine: कैसी हैं?, चाहती हैं?, अच्छी है."
            )
        elif g == "male":
            gmark = (
                "GENDER=male (voice-pitch guess, may be wrong). "
                "తెలుగు: ALWAYS గారు/అండి — NEVER సర్, NEVER మేడం. "
                "Hindi जी, English sir or no honorific. "
                "Hindi verbs masculine: कैसे हैं?, चाहते हैं?, अच्छा है."
            )
        else:
            # F0 detect not yet landed. Default to neutral honorifics +
            # masculine verbs (statistically safer for unknown).
            gmark = (
                "GENDER=unknown. Use neutral: తెలుగు గారు/అండి, "
                "Hindi जी, English drop honorifics. "
                "NEVER మేడం/मैडम/madam until detected. "
                "Hindi verbs masculine fallback: कैसे हैं?, चाहते हैं?."
            )
        if not forked:
            chat_ctx = chat_ctx.copy()
            forked = True
        chat_ctx.add_message(role="system", content=gmark)
        # Round 5: emotion-reactive behavioral directive — only when an
        # informative emotion is detected. Pairs with the per-turn TTS
        # pace tune (Round 2): R2 controls how the AI SOUNDS, R5 controls
        # what the AI SAYS. Together they make the agent feel like a
        # real human matching the caller's mood instead of monotone.
        # Skipped on neutral so token cost is zero in the common case.
        # Emotion markers — compacted ~70% (real evidence: 8300-token
        # prompts were hitting org TPM cap). Behavioral directive
        # preserved per emotion; redundant multi-language examples and
        # negative-framing removed since persona base already encodes
        # tone rules. Same SAYS-WHAT bar with lower TPM.
        _emo = (self._memory.emotion or "").lower() if self._memory else ""
        if _emo in ("frustrated", "angry", "confused", "urgent", "happy"):
            emap = {
                "frustrated": (
                    "EMOTION=frustrated. Lead with brief ack. "
                    "Empathetic + concrete. NO 'I'll check' loops. "
                    "Say WHAT happens + BY WHEN in one sentence."
                ),
                "angry": (
                    "EMOTION=angry. Ack in 3-4 words. NO defending/explaining. "
                    "State the FIX you're doing NOW. Match anger with CALM."
                ),
                "confused": (
                    "EMOTION=confused. Slow. ONE point per turn. Repeat key "
                    "fact in their language. End with comprehension check."
                ),
                "urgent": (
                    "EMOTION=urgent. Cut preamble. Answer actionable bit "
                    "FIRST in one sentence. Concrete next step + time."
                ),
                "happy": (
                    "EMOTION=happy. Match energy lightly. Brief warmth ack "
                    "once, then back to task. Not over-the-top."
                ),
            }
            if not forked:
                chat_ctx = chat_ctx.copy()
                forked = True
            chat_ctx.add_message(role="system", content=emap[_emo])
        # Phase 8: structured memory line (emotion/intent/name/last-said).
        # Latency optimisation: SKIP injection on default/uninformative
        # state (no emotion signal, no specific intent, no name) — saves
        # ~30-50ms TTFT + ~150 tokens per turn with zero info loss.
        m = self._memory
        info_useful = (
            m.emotion not in ("", "neutral")
            or m.intent not in ("", "unknown")
            or bool(m.name)
        )
        if info_useful:
            mem_line = m.as_prompt()
            if mem_line:
                if not forked:
                    chat_ctx = chat_ctx.copy()
                    forked = True
                chat_ctx.add_message(role="system", content=mem_line)
        # Absolute language-lock reinforcement: append a crisp, authoritative reminder at the very end (index -1)
        # of chat_ctx so gpt-4o-mini sees it immediately before generating and cannot ignore it.
        if lang:
            if not forked:
                chat_ctx = chat_ctx.copy()
                forked = True
            remap = {
                "en": "You MUST reply in 100% English. ZERO Telugu/Hindi words.",
                "te": "You MUST reply in 100% complete Telugu script (తెలుగు లిపి). CRITICAL: Use ZERO English script / Roman characters (A-Z). All loan words MUST be written phonetically in Telugu script (e.g., అపాయింట్‌మెంట్, కన్ఫర్మ్, రీషెడ్యూల్, కాన్సిల్).",
                "te-mix": "You MUST reply in Tenglish. Combine Telugu script and English script. Use English script (Roman characters) for business terms (e.g., appointment, confirm, reschedule, cancel, booking), and Telugu script for connectors (e.g., లేదా, రేపు).",
                "hi": "You MUST reply in 100% complete Hindi script (देवनागरी). CRITICAL: Use ZERO English script / Roman characters (A-Z). All loan words MUST be written phonetically in Devanagari script (e.g., अपॉइंटमेंट, कन्फर्म, रीशेड्यूल, कैंसिल).",
                "hi-mix": "You MUST reply in Hinglish. Combine Devanagari script and English script. Use English script (Roman characters) for business terms (e.g., appointment, confirm, reschedule, cancel, booking), and Devanagari script for connectors (e.g., या, कल)."
            }
            rem = remap.get(lang, f"You MUST reply in the matching {lang} variety.")
            chat_ctx.add_message(role="system", content=f"REMINDER-FOR-NEXT-REPLY: {rem}")
            # BREVITY (anti-lecture): real calls showed the agent dumping
            # 4-6 sentence paragraphs on info questions (services, "what
            # is acne") → caller got bored/annoyed and hung up. Force the
            # human bite-sized shape every turn — answer the core in 1-2
            # short sentences, then a brief invite. No lists/paragraphs.
            chat_ctx.add_message(
                role="system",
                content=(
                    "LENGTH-FOR-NEXT-REPLY: Keep it to 1-2 SHORT spoken "
                    "sentences (~max 30 words), like a real phone chat. "
                    "Answer the core point, then a short follow-up question. "
                    "NEVER a paragraph, list, or lecture — if there's more, "
                    "say one line and ask if they want details."
                ),
            )

        # ── HARD PROMPT TOKEN BUDGET ────────────────────────────────
        # Bound the assembled prompt so it can NEVER grow past the
        # model/tier limit. Real calls showed the prompt climbing
        # 7.6k→12.9k tokens across one call (unbounded chat history) →
        # Groq free-tier 12k 413 → dead air. This trims the OLDEST raw
        # turns only (system markers + recent turns are always kept;
        # CallMemory carries the durable gist), keeping TTFT flat and
        # the call alive on a long conversation. chat_ctx is already a
        # fork here (markers above forced the copy), so mutation is safe.
        try:
            budget = int(getattr(self._cfg, "llm_prompt_max_tokens", 0) or 0)
            if budget > 0:
                from src.prompt_budget import enforce_prompt_budget

                enforce_prompt_budget(
                    chat_ctx, budget, model=self._cfg.llm_model
                )
        except Exception:
            logger.debug("prompt budget enforcement skipped", exc_info=True)

        # ── TOOLS-ON-DEMAND (prefill cut) ───────────────────────────
        # The 6 appointment tools (~1.5k tokens of schema) ride on EVERY
        # request — even pure Q&A turns ("what is acne", "where are you")
        # where booking is irrelevant. They inflate the prompt AND make
        # the model spend time evaluating irrelevant tools → higher TTFT.
        # Drop them when THIS turn shows no booking signal. CONSERVATIVE:
        # keep ALL tools whenever the current text OR the call's running
        # intent hints booking, so a real booking turn never loses them.
        try:
            _BOOK_TOOLS = {
                "check_appointment_slots", "book_appointment",
                "my_appointment", "reschedule_appointment",
                "cancel_appointment", "cancel_all_appointments",
            }
            _bk = (_cur_user_text or "").lower()
            _book_cues = (
                "appointment", "appoint", "booking", "book", "slot",
                "schedule", "reschedule", "cancel", "confirm", "available",
                "timing", "time", "repu", "kal", "tomorrow", "today",
                "అపాయింట్", "బుక్", "టైమ్", "టైం", "రద్దు", "షెడ్యూల్",
                "గంట", "రేపు", "ఈరోజు", "కన్ఫర్మ్", "slot",
            )
            _intent = (
                (self._memory.intent or "").lower() if self._memory else ""
            )
            _booking_ctx = any(c in _bk for c in _book_cues) or any(
                k in _intent
                for k in ("appoint", "book", "resched", "cancel",
                          "remind", "slot")
            )
            if tools and not _booking_ctx:
                _filtered = [
                    t for t in tools
                    if getattr(t, "name", "") not in _BOOK_TOOLS
                ]
                if _filtered:
                    tools = _filtered
        except Exception:
            logger.debug("tools-on-demand filter skipped", exc_info=True)

        # ── DETERMINISTIC BOOKING TOOL SELECTION ────────────────────
        # Booking is a DETERMINISTIC flow (check slots → pick a time → book),
        # but weak models (Mistral Small) can't track that state: they
        # under-call, pick the WRONG tool, re-offer slots in a loop, or
        # hallucinate "already booked". So the AGENT — not the model —
        # decides WHICH tool fires this turn, from the turn content, and
        # forces that EXACT tool via tool_choice:
        #   • cancel cue              → cancel_appointment
        #   • reschedule cue          → reschedule_appointment
        #   • a concrete TIME present → book_appointment (caller chose a slot)
        #   • availability / no time  → check_appointment_slots
        #   • generic booking cue     → "required" (any tool)
        # Verified: forcing the exact tool makes a small/fast model book as
        # reliably as a big one. Non-booking turns stay on "auto" (untouched);
        # this whole block only runs when booking tools are on the table
        # (the tools-on-demand filter already gates that to booking context).
        try:
            _has_book_tool = bool(tools) and any(
                getattr(t, "name", "") in _BOOK_TOOLS for t in tools
            )

            def _force_tool(_name):
                if model_settings is not None and tools and any(
                    getattr(t, "name", "") == _name for t in tools
                ):
                    model_settings.tool_choice = {
                        "type": "function", "function": {"name": _name}
                    }
                    return _name
                return None

            if _has_book_tool and model_settings is not None:
                # Concrete time in the caller's turn: "3pm", "10:30", "10 am",
                # "10 gantalaki", "padinnara gantalaki", "గంటలకి", etc.
                _has_time = bool(re.search(
                    r"\d\s*(?:am|pm|gant|గంట|o'?clock|:\s*\d)"
                    r"|gantal|గంటల|గంటక|nimisha",
                    _bk, re.IGNORECASE,
                ))
                _cancel = any(c in _bk for c in ("cancel", "రద్దు", "క్యాన్సిల్"))
                _resched = any(c in _bk for c in (
                    "resched", "reschedule", "మార్చ", "రీషెడ్యూల్", "marchu"))
                _avail = any(c in _bk for c in (
                    "slot", "available", "free", "khali", "ఖాళీ", "స్లాట్",
                    "dates", "timing", "unnay"))
                _book = any(c in _bk for c in (
                    "book", "fix", "confirm", "బుక్", "కన్ఫర్మ్", "cheyandi",
                    "cheyyi", "చేయండి", "set"))

                # Did a booking ALREADY land THIS call? Scan only TOOL-RESULT
                # items (role == "tool" / FunctionCallOutput) — never the
                # system snapshot (which mentions the caller's EXISTING
                # bookings and would false-positive). If a booking already
                # confirmed this call, a re-stated time ("avunandi 3pm ke")
                # is a CONFIRMATION, not a new request: don't re-force book —
                # that re-books + repeats the same line (the loop the deep
                # test caught). Re-affirmation just gets acknowledged.
                _already_booked = False
                try:
                    for _it in chat_ctx.items:
                        _out = getattr(_it, "output", None)
                        if _out is None and getattr(_it, "role", None) != "tool":
                            continue
                        _tx = (str(_out) if _out is not None
                               else (_message_text(_it) or "")).lower()
                        if "book" in _tx and (
                            "confirm" in _tx or "booked" in _tx or "id=" in _tx
                        ):
                            _already_booked = True
                            break
                except Exception:
                    pass

                forced = None
                if _cancel:
                    forced = _force_tool("cancel_appointment")
                elif _resched:
                    forced = _force_tool("reschedule_appointment")
                elif _has_time and not _already_booked:
                    forced = _force_tool("book_appointment")
                elif (_avail or _book) and not _already_booked:
                    forced = _force_tool("check_appointment_slots")
                # else (already booked + a re-stated time/confirm): leave on
                # "auto" so the agent just acknowledges — never re-books/loops.
                if (forced is None and not _already_booked
                        and (_avail or _book or _has_time)):
                    # Wanted a tool but the exact one isn't exposed → still
                    # force SOME tool so the turn never loops as plain text.
                    model_settings.tool_choice = "required"
                    forced = "required"
                if forced:
                    logger.debug(
                        "deterministic tool_choice=%s (already_booked=%s)",
                        forced, _already_booked,
                    )
        except Exception:
            logger.debug("deterministic tool_choice skipped", exc_info=True)

        # ── EMIT PER-STAGE LATENCY (every micro-component, precise) ──
        # assembly = total time inside llm_node BEFORE the model call
        # (markers + gender + emotion + memory + tool-pick); snapshot_db =
        # the Appointment-table read inside it; prompt_tokens ≈ what the
        # model must prefill. These were hidden inside "LLM TTFT" — now
        # detectable and exposed for the dashboard breakdown.
        _asm_ms = (time.monotonic() - _asm_t0) * 1000.0
        try:
            _ptok = sum(len(_message_text(_it) or "")
                        for _it in chat_ctx.items) // 4
        except Exception:
            _ptok = 0
        logger.info(
            "STAGE-LATENCY assembly=%.0fms snapshot_db=%.0fms prompt_tokens=%d",
            _asm_ms, _snap_ms, _ptok,
        )
        self._last_assembly_ms = _asm_ms
        self._last_snapshot_ms = _snap_ms
        self._last_prompt_tokens = _ptok
        # Feed the two sub-stages into the per-call latency aggregates so
        # the dashboard breakdown shows them alongside EOU/LLM TTFT/TTS.
        try:
            self._tel.record_latency("assembly", _asm_ms / 1000.0)
            if _snap_ms:
                self._tel.record_latency("snapshot_db", _snap_ms / 1000.0)
        except Exception:
            logger.debug("record sub-stage latency failed", exc_info=True)

        # ── PARALLEL LLM RACING (TTFT tail-spike killer) ────────────
        # Fire N identical streams, play the fastest first-token, cancel
        # the rest. Clips the 3-4s variance spikes so turns feel
        # consistent. Fallback-safe: if racing yields nothing (all empty/
        # errored on first token), drop to a single normal stream — and
        # ONLY then, so a winner that errors mid-stream never double-runs.
        try:
            race_n = int(getattr(self._cfg, "llm_race_count", 1) or 1)
        except Exception:
            race_n = 1
        if race_n > 1:
            from src.llm_race import race_async_gens

            gens = [
                Agent.default.llm_node(self, chat_ctx, tools, model_settings)
                for _ in range(race_n)
            ]
            raced = race_async_gens(gens)
            produced = False
            try:
                first = await raced.__anext__()
                produced = True
            except StopAsyncIteration:
                produced = False
            except Exception:
                logger.warning(
                    "llm race init failed; single stream", exc_info=True
                )
                produced = False
                await raced.aclose()
            if produced:
                yield first
                async for chunk in raced:
                    yield chunk
                return
            # else: fall through to a single normal stream below.

        async for chunk in self._guard_truncated_tail(
            self._llm_stream_with_fallback(chat_ctx, tools, model_settings)
        ):
            yield chunk

    async def _guard_truncated_tail(self, source):
        """Never speak a half-sentence. When the provider hard-stops the
        reply at the output-token cap (finish=length), the stream ends
        mid-sentence ("...చేరుకోవచ్చు అండి. మీకు" — live bug 2026-06-12)
        and the agent then sits in silence. Text is passed through
        unchanged sentence-by-sentence; only a TRAILING fragment with no
        sentence terminator is held back, and at stream end it is dropped
        IF the total output is at/near the cap (= truncation), else
        flushed normally. Zero added latency: the TTS sentence chunker
        never consumed unterminated tails mid-stream anyway."""
        import os as _os

        from src.config import settings as _settings

        _TERMS = ".!?।…"
        cap = int(
            _os.environ.get("LLM_MAX_OUTPUT_TOKENS")
            or _settings.llm_max_output_tokens
        )
        held = ""
        total = ""
        last_id = None
        try:
            async for chunk in source:
                delta = getattr(chunk, "delta", None)
                content = getattr(delta, "content", None) if delta else None
                if not content:
                    yield chunk  # tool calls / usage chunks pass through
                    continue
                last_id = getattr(chunk, "id", None) or last_id
                total += content
                merged = held + content
                cut = max(merged.rfind(t) for t in _TERMS)
                if cut >= 0:
                    held = merged[cut + 1:]
                    delta.content = merged[: cut + 1]
                    yield chunk
                else:
                    held = merged
                    # withhold: no complete sentence yet in this tail
        finally:
            if held.strip():
                from src.prompt_budget import count_tokens
                truncated = count_tokens(total) >= cap - 24
                if truncated:
                    logger.info(
                        "tail-guard: dropped truncated fragment %r "
                        "(output at token cap %d)", held.strip()[:60], cap,
                    )
                else:
                    try:
                        from livekit.agents import llm as _llm
                        yield _llm.ChatChunk(
                            id=last_id or "tail-guard",
                            delta=_llm.ChoiceDelta(
                                role="assistant", content=held
                            ),
                        )
                    except Exception:
                        logger.warning(
                            "tail-guard: could not flush tail %r",
                            held.strip()[:60], exc_info=True,
                        )

    def _get_fallback_llm(self):
        """Lazily build a fallback LLM used ONLY when the primary fails a
        turn BEFORE producing any token, so a per-model throttle/cap never
        becomes dead-air. The old code returned None for every gpt-* and
        azure/* primary (no fallback) — that is exactly how a gpt-4o TPM
        cap turned into 14s of silence. Now every primary gets a DIFFERENT
        reliable OpenAI sibling (separate per-model limit). `False` is the
        'tried and failed' sentinel so we don't rebuild it every failing
        turn.

        NOTE: same-provider fallback clears a per-MODEL throttle (the
        gpt-4o TPM case) but NOT an OpenAI-wide outage — true cross-provider
        resilience (paid Groq / a working Azure deployment) is an infra
        decision still open. Azure gpt-4o-mini is deliberately NOT used:
        that deployment 404s on this account (verified in the model audit)."""
        if self._fallback_llm is not None:
            return self._fallback_llm or None
        model = (getattr(self._cfg, "llm_model", "") or "").lower()
        # Cross-PROVIDER, India-fast fallback for our two primaries: a
        # Mistral 429 (EU rate-limit) recovers on Bedrock Mumbai (AWS, no
        # 429); a Bedrock blip recovers on Mistral (different provider, no
        # shared limit). Both are ~India-latency, so the catch is ~0.6s
        # instead of the old slow US gpt-4o-mini (which can itself 429).
        if model.startswith("mistral/"):
            fb_model = "bedrock/mistral.ministral-3-14b-instruct"
        elif model.startswith("bedrock/"):
            fb_model = "mistral/mistral-small-latest"
        # Pick a DIFFERENT, reliable OpenAI model than an OpenAI primary.
        elif "nano" in model:
            fb_model = "gpt-4o-mini"
        elif "mini" in model:
            fb_model = "gpt-4.1-nano"
        else:
            fb_model = "gpt-4o-mini"
        try:
            import dataclasses
            fb_cfg = dataclasses.replace(self._cfg, llm_model=fb_model)
            self._fallback_llm = build_llm(fb_cfg)
            logger.info("built fallback LLM %s (primary=%s)", fb_model, model)
        except Exception:
            logger.warning("failed to build fallback LLM", exc_info=True)
            self._fallback_llm = False
        return self._fallback_llm or None

    async def _stream_from_llm(self, llm_obj, chat_ctx, tools, model_settings):
        """Stream a turn from an explicit LLM object, replicating the
        default llm_node's chat() call (used for the fallback path)."""
        activity = self._get_activity_or_raise()
        conn_options = activity.session.conn_options.llm_conn_options
        kwargs = dict(chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        if model_settings is not None:
            kwargs["tool_choice"] = model_settings.tool_choice
        async with llm_obj.chat(**kwargs) as stream:
            async for chunk in stream:
                yield chunk

    async def _llm_stream_with_fallback(self, chat_ctx, tools, model_settings):
        """Stream from the dashboard-selected (primary) LLM. If it fails
        with a rate-limit / connection error BEFORE producing any token —
        the Groq free-tier 429 case — transparently retry the SAME turn on
        the Azure fallback so the call never goes silent. The dashboard
        choice stays PRIMARY; fallback only catches a failed turn.

        Safety: we only fall back if NO chunk was produced yet. Once the
        primary has started streaming we re-raise on error (can't cleanly
        restart a half-spoken answer)."""
        produced = False
        try:
            async for chunk in Agent.default.llm_node(
                self, chat_ctx, tools, model_settings
            ):
                produced = True
                yield chunk
            return
        except Exception as e:
            if produced:
                raise
            fb = self._get_fallback_llm()
            if fb is None:
                raise
            logger.warning(
                "primary LLM failed before first token (%s) — falling back "
                "to OpenAI gpt-4o-mini/gpt-4.1-nano for this turn",
                type(e).__name__,
            )
        # Fallback stream (only reached on pre-token primary failure).
        async for chunk in self._stream_from_llm(
            fb, chat_ctx, tools, model_settings
        ):
            yield chunk

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        text = _message_text(new_message).strip()
        if not text:
            return

        # PHASE 11: drop our own TTS echo instead of treating it as a turn.
        if self._echo.is_echo(text):
            logger.debug("dropped echo input: %r", text[:40])
            raise StopResponse()

        # Narrow noise-token filter — STT occasionally surfaces hold music
        # / ringtones / pure background noise as a literal word ("music",
        # "ringing", etc.). On real transcripts these arrived as caller
        # turns and the agent then asked confusing follow-ups. Strict
        # allowlist of known STT-noise words only (NOT a heuristic — would
        # false-fire on legitimate short replies, as the prior mishear
        # gate did). Caller hears a polite "could you repeat" canned line,
        # transcript still records what STT heard for operator audit.
        _NOISE_WORDS = {
            "music", "ringing", "ringtone", "ring tone", "noise",
            "background", "hold music", "static", "interference",
            "silence", "dial tone", "beep",
        }
        if text.lower().strip(".,!?") in _NOISE_WORDS:
            logger.info("noise-token detected: %r — serving canned repeat", text)
            try:
                from src.content import content_store as _cs
                lang_key = (self._memory.language or "en").lower()
                if lang_key.startswith("te"): lang_key = "te"
                elif lang_key.startswith("hi"): lang_key = "hi"
                else: lang_key = "en"
                options = _cs.canned("repeat", lang_key) or [
                    "Sorry, could you say that again?"
                ]
                import random as _rand
                reply = _rand.choice(options)
                await self.session.say(reply, add_to_chat_ctx=False)
            except Exception:
                logger.debug("noise canned-repeat failed", exc_info=True)
            raise StopResponse()

        # Mishear gate + streak end-call removed at user request
        # (2026-05-22): false-fires were ending calls just before
        # booking confirmation. Caller turns now flow straight to the
        # router; vague/garbled input is handled by the persona's
        # "ask to repeat" rule rather than a code-level gate.
        self._caller_turns_seen += 1
        # NOTE: a hard "wait if incomplete" guard used to live here but it
        # muted the agent on normal short turns ("yes", "haan", "order
        # status"). End-of-turn is handled correctly by LiveKit's turn
        # detection + the per-language endpointing delay (Telugu gets a
        # longer floor via endpointing_delay_for). We always respond once
        # the turn is committed.

        # Cancel any filler from the previous turn that hasn't played yet
        # (happens when LLM answered fast or barge-in cut the old turn short).
        if self._pending_filler and not self._pending_filler.done():
            self._pending_filler.cancel()
        self._pending_filler = None

        t0 = time.monotonic()

        # PHASE 10: if speculative prefetch already warmed this answer,
        # serve it instantly (the fastest possible path).
        _spec_t0 = time.monotonic()
        warm = await self._predictive.take_if_matches(text)
        if warm:
            logger.info(
                "METRIC predictive=HIT waited=%.3fs",
                time.monotonic() - _spec_t0,
            )
        elif self._predictive._predicted_query:
            logger.info(
                "METRIC predictive=MISS pred=%r final=%r",
                self._predictive._predicted_query[:60], text[:60],
            )
        self._predictive.reset()

        # The CALL's configured language (dashboard/campaign) is
        # authoritative — pass it INTO the router so canned/filler never
        # reply in the wrong language. The keyword classifier mis-reads
        # Tenglish and made Telugu calls answer in Hindi/English.
        call_lang = (
            self._cfg.default_language
            if self._cfg.default_language in ("te", "hi", "en")
            else None
        )
        result = await self._router.route(text, call_language=call_lang)
        cls = result.classification
        # Determine exact conversational language variety (pure vs code-mixed)
        # to strictly mirror caller's linguistic behavior on the very next turn.
        # Anchor the fallback on short acks directly to the currently active
        # variety rather than the campaign default, preventing accidental resets.
        # STRICT PER-TURN LANGUAGE MIRROR — user requirement (2026-06-03):
        # agent must reply in the EXACT language the caller spoke on this
        # turn. No hysteresis, no buffering, no 1-turn lag. The expanded
        # te_cues / hi_cues word lists below give the detector enough
        # coverage that Sarvam Roman-script output classifies correctly
        # on the FIRST turn — so the noise-buffer that hysteresis used
        # to provide is no longer needed.
        lang = _detect_conversational_variety(
            text, self._last_turn_lang or call_lang
        )
        self._last_turn_lang = lang
        self._meter.record_route(result.route)
        self._memory.update_from_turn(text, lang, cls.intent)
        self._rhythm.emotion = self._memory.emotion
        logger.info(
            "latency turn->route %.0fms route=%s lang=%s",
            (time.monotonic() - t0) * 1000, result.route.value, lang,
        )

        # Telemetry + memory persistence are Redis/Postgres round-trips —
        # NEVER block the reply on them. Fire-and-forget so the agent
        # responds immediately (this alone was ~3 serial round-trips of
        # dead air before the filler/LLM even started).
        async def _persist():
            await asyncio.gather(
                memory_store.save(self._memory),
                self._tel.turn("user", text),
                self._tel.update_context(self._memory),
                self._tel.update_metrics(self._meter),
                return_exceptions=True,
            )

        self._tel.spawn(_persist())

        if warm:
            # Speculative prefetch hit = answer is ALREADY in hand. Real
            # call-center agents don't pause before saying "sare bhayya"
            # for routine confirmations — they fire. The 50-180ms rhythm
            # beat (designed as anti-robotic flavor) was hurting the
            # "instant" feel on cache/warm/canned paths the system was
            # built to make instant. Skip on the fast paths; emotion-
            # aware pacing lives in TTS pace + the LLM path naturally.
            await self._say(warm, skip_rhythm=True, cacheable=True)
            raise StopResponse()

        if result.resolved_without_llm and result.answer:
            await self._say(result.answer, skip_rhythm=True, cacheable=True)
            # Audit fix #1: canned bye route used to play goodbye and then
            # idle — call hung ~10s before LiveKit timed it out. Now we
            # invoke end_call directly so the line drops within ~1s of
            # the goodbye audio finishing.
            if cls.intent == "bye":
                from src.tools import end_call_var as _ecv
                cb = _ecv.get()
                if cb is not None:
                    asyncio.ensure_future(cb())
            raise StopResponse()

        # LLM path: fire the filler in PARALLEL (do NOT await it) and
        # return immediately so the LLM starts now — the filler audio
        # plays over the LLM's first-token gap instead of before it.
        # skip_rhythm=True: the filler is the cover-up; the rhythm beat
        # would sit AHEAD of it (lose the latency cover) — go straight.
        #
        # FILLER CADENCE — the hard rule (re-broke 2026-06-14, fixed):
        # a filler before EVERY reply is the #1 robotic tell. Fillers
        # exist to cover the ~0.8-1s LLM gap and must stay OCCASIONAL:
        #   * only on slow (LLM-route) turns — canned/cache are instant,
        #   * NEVER 2 within 2 caller turns (no bypass, ever),
        #   * ~50% chance even when eligible — the un-filled turns get a
        #     short natural pause, which together with the filled ones
        #     sounds human (a filler every time does not).
        # filler_kind() only picks WHICH phrase (honest "checking" when
        # we truly look something up, else a soft ack) — it never forces
        # a fire.
        _is_llm = result.route == Route.LLM
        # BALANCED filler (the 85%/gap>=1 instant-feel version fired too
        # often — interjected "ఒక్క నిమిషం" on weak turns like "ఉమ్",
        # choppy/robotic). The real latency win is the endpointing cut
        # (~256ms), so the filler can stay OCCASIONAL: only on a slow LLM
        # turn that has REAL content (not a bare ack/hesitation), never 2
        # within 2 turns, ~50%. Covers genuine gaps, never interjects on
        # "um".
        _has_content = len((text or "").split()) >= 3
        _gap_ok = (self._caller_turns_seen - self._last_filler_turn) >= 2
        _fire = _is_llm and _has_content and _gap_ok and (random.random() < 0.5)
        if should_filler(result.route, cfg=self._cfg) and _fire:
            self._last_filler_turn = self._caller_turns_seen
            self._pending_filler = asyncio.ensure_future(
                self._say(
                    pick_filler(lang, intent=cls.intent, user_text=text),
                    skip_rhythm=True,
                    is_filler=True, cacheable=True,
                )
            )
            # Yield one event-loop tick so the filler task calls
            # session.say() BEFORE on_user_turn_completed returns.
            # Without this, LiveKit queues the LLM response first and
            # the filler plays AFTER the real answer.
            await asyncio.sleep(0)
            logger.info(
                "latency turn->filler %.0fms",
                (time.monotonic() - t0) * 1000,
            )

        # NOTE: we deliberately do NOT mutate turn_ctx here. Injecting a
        # memory message / trimming AFTER on_user_turn_completed makes
        # LiveKit discard the preemptive LLM draft ("chat context changed
        # after on_user_turn_completed") — that adds a full extra
        # round-trip of latency (the gaps you heard). LiveKit already
        # keeps recent conversation context; structured memory still
        # drives rhythm/telemetry. Returning lets the LLM run immediately.


class CallMeta:
    """Per-call context parsed from the dialer's job metadata."""

    def __init__(self) -> None:
        self.direction = "inbound"
        self.name = ""
        self.language = ""
        self.script = ""          # per-campaign goal/persona override
        self.voice_model = ""     # per-campaign TTS model override
        self.voice_speaker = ""   # per-campaign speaker override
        self.phone = ""           # callee number (for appt contact #)
        self.use_case = ""        # per-campaign use-case (tool/prompt gate)
        self.business_description = ""  # per-campaign business override
        self.style_examples = ""        # per-campaign few-shot override
        self.kb_vector_store_id = ""    # per-campaign KB scoping


def resolve_call(ctx: JobContext) -> CallMeta:
    """Parse the job metadata set by the outbound dialer.

    Outbound metadata is `outbound {json}` (see telephony/outbound.py).
    Each campaign embeds its own script/voice/language so simultaneous
    campaigns (e.g. appointment vs sales) each communicate to their own
    goal. Inbound has no metadata → defaults (global persona).
    """
    m = CallMeta()
    raw = getattr(ctx.job, "metadata", "") or ""
    if "outbound" not in raw.lower():
        return m
    m.direction = "outbound"
    brace = raw.find("{")
    if brace != -1:
        try:
            import json as _json

            d = _json.loads(raw[brace:])
            m.name = str(d.get("name", "") or "").strip()
            m.language = str(d.get("language", "") or "").strip()
            m.script = str(d.get("script", "") or "").strip()
            m.voice_model = str(d.get("voice_model", "") or "").strip()
            m.voice_speaker = str(d.get("voice_speaker", "") or "").strip()
            m.phone = str(d.get("phone", "") or "").strip()
            m.use_case = str(d.get("use_case", "") or "").strip()
            m.business_description = str(
                d.get("business_description", "") or "").strip()
            m.style_examples = str(
                d.get("style_examples", "") or "").strip()
            m.kb_vector_store_id = str(
                d.get("kb_vector_store_id", "") or "").strip()
        except Exception:
            pass
    return m


def prewarm(proc: JobProcess) -> None:
    """Load heavy models once per worker process (not per call).

    Latency hygiene: also fires a background OpenAI HTTP/2 pool warmup
    so the FIRST call this subprocess handles doesn't pay a fresh
    ~100-180ms TLS handshake on top of LLM TTFT. Subsequent calls in the
    same subprocess re-use the warm pool (keepalive_expiry=300s in
    pipeline/llm.py). Fire-and-forget — never blocks boot.
    """
    proc.userdata["vad"] = build_vad()
    try:
        from src.pipeline.llm import warm_openai_pool
        warm_openai_pool()
    except Exception:
        logger.debug("warm_openai_pool failed (non-fatal)", exc_info=True)
    # Pre-warm the Bedrock (Mumbai) pool too, so the FIRST (cold) call's
    # LLM TTFT skips the ~180-490ms TLS/HTTP2 handshake when the live model
    # is a bedrock/ one. No-op if no Bedrock key is configured.
    try:
        from src.pipeline.llm import warm_bedrock_pool
        warm_bedrock_pool()
    except Exception:
        logger.debug("warm_bedrock_pool failed (non-fatal)", exc_info=True)


def _safe_session_on(session: AgentSession, event, handler) -> None:
    """Register a session event handler defensively.

    Event names vary slightly across livekit-agents builds, so a missing
    event degrades gracefully rather than crashing the call.
    """
    try:
        session.on(event, handler)
    except Exception:  # pragma: no cover - defensive across versions
        logger.debug("session has no event %s", event)


def _make_fsm(
    session: AgentSession, registry: CancellationRegistry
) -> ConversationFSM:
    """Build the FSM with a transition hook that fires token-level
    cancellation the instant we enter INTERRUPTED (barge-in)."""

    def _on_transition(_prev: State, new: State) -> None:
        if new == State.INTERRUPTED:
            # Cancel our speculative work + flush TTS now (<~200ms).
            registry.spawn(registry.on_interrupt(session))

    return ConversationFSM(on_transition=_on_transition)


def _bind_fsm(
    session: AgentSession,
    fsm: ConversationFSM,
    stabilizer: TranscriptStabilizer,
) -> None:
    """Map AgentSession runtime events onto FSM transitions.

    Also emits per-turn pipeline-stage latency:
      `turn_latency user_stopped->stt_final=Xms stt->agent_speak=Yms total=Zms`
    captured between user-stopped-speaking and agent-starts-speaking, so the
    next "polling slow" / dead-air bug paste has millisecond evidence of
    WHERE the time went (STT? LLM? TTS?). Tied to the call_id-tagged
    logging from Wave 1, every turn is greppable per call.
    """

    # In-closure timers — one set per call instance because _bind_fsm
    # runs inside `entrypoint`. Each call's tracker is independent.
    timers: dict[str, float] = {}

    def _mark(name: str) -> None:
        timers[name] = time.monotonic()

    def _ms_since(name: str) -> float | None:
        t0 = timers.get(name)
        return (time.monotonic() - t0) * 1000 if t0 is not None else None

    def _on_user_state(ev) -> None:
        st = getattr(ev, "new_state", getattr(ev, "state", None))
        if st == "speaking":
            fsm.on_user_started_speaking()
            _mark("user_started")
        elif st == "listening":
            fsm.on_user_turn_committed()
            # Mark the moment the user STOPPED speaking — start of the
            # latency budget the caller perceives as "the wait".
            _mark("user_stopped")
            stabilizer.reset()

    def _on_agent_state(ev) -> None:
        st = getattr(ev, "new_state", getattr(ev, "state", None))
        if st == "speaking":
            fsm.on_agent_started_speaking()
            # End of latency budget: agent's first audio chunk goes out.
            total_ms = _ms_since("user_stopped")
            stt_done_ms = _ms_since("stt_final")
            stt_segment = None
            llm_tts_segment = None
            us = timers.get("user_stopped")
            sf = timers.get("stt_final")
            if us is not None and sf is not None:
                stt_segment = (sf - us) * 1000
                llm_tts_segment = (time.monotonic() - sf) * 1000
            if total_ms is not None:
                logger.info(
                    "turn_latency total_ms=%.0f stt_segment_ms=%s llm_tts_segment_ms=%s",
                    total_ms,
                    f"{stt_segment:.0f}" if stt_segment is not None else "-",
                    f"{llm_tts_segment:.0f}" if llm_tts_segment is not None else "-",
                )
                # Record the END-TO-END perceived latency into telemetry
                # (live dashboard + per-call aggregates). This is the
                # number the 800ms budget is measured against. Telemetry
                # is attached to the session after it's created in
                # entrypoint; guard so this is a no-op until then.
                _tel = getattr(session, "_telemetry", None)
                if _tel is not None:
                    try:
                        _tel.record_latency("response", total_ms / 1000.0)
                    except Exception:
                        logger.debug("response latency record failed",
                                     exc_info=True)
            # Reset for the next turn so the next "user_stopped" wins.
            timers.pop("user_stopped", None)
            timers.pop("stt_final", None)
        elif st in ("listening", "idle"):
            fsm.on_agent_stopped_speaking()

    # Expose the timer-marker so the transcription handler can stamp
    # stt_final without us refactoring its full signature.
    session._turn_latency_mark = _mark  # type: ignore[attr-defined]

    def _on_close(_ev=None) -> None:
        fsm.on_call_ended()

    _safe_session_on(session, "user_state_changed", _on_user_state)
    _safe_session_on(session, "agent_state_changed", _on_agent_state)
    _safe_session_on(session, "close", _on_close)


def _attach_transcription(
    session: AgentSession,
    tts,
    cfg: RuntimeConfig,
    stabilizer: TranscriptStabilizer,
    predictive: PredictivePrefetch,
    registry: CancellationRegistry,
    memory: CallMemory | None = None,
) -> None:
    """Single transcription handler:

      * final  -> retune the Sarvam voice to the caller's language
                  (codemix STT keeps transcribing across languages) and
                  reset the stabilizer for the next turn. If `memory` is
                  provided, the agent's NEXT reply is paced according to
                  the latest detected caller emotion (Round 2 sentiment-
                  aware TTS pace).
      * interim -> feed the stabilizer; on a newly stable prefix kick off
                   speculative KB/cache prefetch (Phase 10).
    """

    def _on_transcribed(ev) -> None:
        text = getattr(ev, "transcript", "") or ""
        is_final = getattr(ev, "is_final", True)
        if is_final:
            # Latency budget: STT just delivered the final transcript.
            # Stamp it so the agent_state=='speaking' handler can split
            # the turn into stt_segment (user_stopped→stt_final) and
            # llm_tts_segment (stt_final→agent_speak).
            try:
                mark = getattr(session, "_turn_latency_mark", None)
                if callable(mark):
                    mark("stt_final")
            except Exception:
                pass
            # Capture final-transcript average confidence so the mishear
            # gate in on_user_turn_completed can force a "please repeat"
            # path on low-confidence transcripts that LOOK grammatical
            # but were guessed by STT. Sarvam may or may not provide
            # `confidences` on final events; if absent, leave at 1.0
            # (no down-gating). Computed BEFORE reset() because reset
            # clears stabilizer state but should NOT clear this field.
            try:
                confs = getattr(ev, "confidences", None)
                if confs:
                    nums = [float(c) for c in confs if c is not None]
                    if nums:
                        stabilizer.last_final_avg_confidence = sum(nums) / len(nums)
                else:
                    # No confidence info from STT — treat as fully
                    # confident so the gate doesn't false-trigger.
                    stabilizer.last_final_avg_confidence = 1.0
            except Exception:
                stabilizer.last_final_avg_confidence = 1.0
            # Retune TTS to the caller's DETECTED language. If Indic script
            # is present in the transcript, use that language; Roman-only
            # turns (short acks etc.) stay on the configured language so a
            # Tenglish call doesn't flip voice to English on every "okay".
            try:
                from src.router.classifier import classify as _clf
                detected = _clf(text).language if text else None
                retune_lang = (
                    detected if detected in ("te", "hi", "en")
                    else cfg.default_language
                )
            except Exception:
                retune_lang = cfg.default_language
            if retune_lang in ("te", "hi", "en"):
                # Pass the LATEST detected emotion so the agent's NEXT
                # reply uses pace matched to caller mood (slower for
                # confused/elderly, calmer for angry, energetic for
                # happy). Falls back to neutral if memory hasn't tagged
                # yet — same behavior as before this feature landed.
                try:
                    _emo = memory.emotion if memory else None
                except Exception:
                    _emo = None
                retune_tts(tts, cfg, retune_lang, emotion=_emo)
            stabilizer.reset()
            return
        # Interim: stabilize, then speculatively prefetch on stable prefix.
        confidences = getattr(ev, "confidences", None)
        stabilizer.push(text, confidences)
        predictive.maybe_prefetch(stabilizer.stable_text, registry)

    _safe_session_on(session, "user_input_transcribed", _on_transcribed)


def _attach_backchannel(
    session: AgentSession,
    tts,
    cfg: RuntimeConfig,
    echo,
    memory: CallMemory | None = None,
) -> None:
    """Real-time active-listening acks (near-human turn-taking).

    Emits ONE short cached ack ("హా అండి…") mid-way through a LONG caller
    utterance, so the caller feels heard while still talking — instead of
    walkie-talkie silence until they finish. No-op unless
    `settings.backchannel_enabled` is True (default OFF: it speaks while
    the caller holds the floor, so validate on one live call first).

    Optimised:
      * cached audio replay (~instant, synthesis-free after first use),
      * fired off the live interim-transcript stream (no extra polling),
      * suppressed while the agent itself is speaking,
      * fed to the echo guard so it's never mis-heard as caller speech,
      * add_to_chat_ctx=False so the LLM never sees acks as turns.
    """
    if not getattr(settings, "backchannel_enabled", False):
        return

    bc = Backchanneler()
    # Track agent speaking state so we never backchannel over our own voice.
    st = {"agent_speaking": False}

    def _on_agent_state(ev) -> None:
        new = getattr(ev, "new_state", None) or getattr(ev, "state", None)
        st["agent_speaking"] = (new == "speaking")

    _safe_session_on(session, "agent_state_changed", _on_agent_state)

    def _emit(phrase: str, lang: str) -> None:
        async def _go() -> None:
            try:
                # Feed the echo guard FIRST so the ack coming back through
                # STT (open-duplex telephony) is dropped, not treated as a
                # new caller turn.
                try:
                    echo.on_agent_started(phrase)
                except Exception:
                    pass
                from src.tts_cache import say_cached

                await say_cached(
                    session,
                    session.tts,
                    phrase,
                    model=cfg.tts_model,
                    speaker=cfg.speaker_for(lang),
                    language=lang,
                    allow_interruptions=True,
                    add_to_chat_ctx=False,
                )
            except Exception:
                logger.debug("backchannel emit failed", exc_info=True)

        asyncio.ensure_future(_go())

    def _on_tx(ev) -> None:
        try:
            is_final = getattr(ev, "is_final", True)
            if is_final:
                bc.reset_utterance()
                return
            if st["agent_speaking"]:
                return
            text = getattr(ev, "transcript", "") or ""
            now = time.monotonic()
            if not bc.should_ack(text, now):
                return
            lang = (memory.language if memory else None) or cfg.default_language
            lang = lang if lang in ("te", "hi", "en") else "en"
            _emit(pick_backchannel(lang), lang)
        except Exception:
            logger.debug("backchannel handler error", exc_info=True)

    _safe_session_on(session, "user_input_transcribed", _on_tx)
    logger.info("backchannel: real-time active-listening acks ENABLED")


def _extract_business_name(desc: str) -> str:
    if not desc:
        return "our company"
    clean = desc.strip()
    # Look for " is a " or " is " or " follows " or " provides "
    for indicator in (" is a ", " is ", " follows ", " provides "):
        idx = clean.lower().find(indicator)
        if idx != -1:
            name = clean[:idx].strip()
            if 0 < len(name) < 50:
                return name
    # Fallback to first line/sentence
    first_line = clean.split("\n")[0].split(".")[0].strip()
    if 0 < len(first_line) < 50:
        return first_line
    return "our company"


def _extract_custom_greeting(text: str, language: str) -> str | None:
    if not text:
        return None
    lang_upper = language.upper()
    markers = (
        f"welcome greeting ({lang_upper}):",
        f"welcome greeting {lang_upper}:",
        "welcome greeting:",
        f"opener ({lang_upper}):",
        f"opener {lang_upper}:",
        "opener:",
        f"greeting ({lang_upper}):",
        f"greeting {lang_upper}:",
        "greeting:",
    )
    for line in text.split("\n"):
        line_lower = line.lower().strip()
        for marker in markers:
            if line_lower.startswith(marker):
                val = line[line_lower.find(marker) + len(marker):].strip()
                val = val.strip('"\'')
                if val:
                    return val
    return None


def _local_opener_for(cfg: RuntimeConfig, direction: str, caller_name: str | None) -> str | None:
    """Warm, completely natural, hand-written openers that speak IMMEDIATELY
    with zero LLM call. This completely eliminates the 5.3s live LLM
    dead-air at start, and guarantees top-notch natural human flow for ANY business.
    
    Supports dynamic customization! If the user writes a custom welcome greeting
    in their inbound/outbound persona prompt (e.g. 'WELCOME GREETING (TE): ...'),
    it will be extracted and spoken instantly, replacing the default template.
    """
    # 1. Look for custom greeting in the campaign persona/script
    persona = cfg.outbound_persona if direction == "outbound" else cfg.inbound_persona
    custom = _extract_custom_greeting(persona, cfg.default_language)
    if custom:
        if caller_name:
            custom = custom.replace("{name}", f"{caller_name}").replace("{caller_name}", f"{caller_name}")
        else:
            custom = custom.replace("{name} గారు", "").replace("{name} जी", "").replace("{name}", "").replace("{caller_name}", "")
        return custom.strip()

    # 2. Fallback to dynamic business-aware default template.
    # Business name + agent name come from config (no hardcoded clinic).
    desc = cfg.business_description or ""
    biz_name = _extract_business_name(desc)
    an = (cfg.agent_name or "Zari").strip()
    is_medical = any(w in desc.lower() for w in (
        "clinic", "hospital", "doctor", "health", "medical", "dental",
        "skin", "care", "trichology", "aesthetics",
    ))

    if direction == "outbound":
        if cfg.default_language == "te":
            name_greet = f"హలో {caller_name} గారు! " if caller_name else "హలో అండి! "
            if is_medical:
                return f"{name_greet}{biz_name} నుంచి {an} మాట్లాడుతున్నాను అండి. మీ అపాయింట్‌మెంట్ కన్ఫర్మ్ చేయడానికి కాల్ చేశాను అండి, ఒక్క నిమిషం మాట్లాడొచ్చా అండి?"
            else:
                return f"{name_greet}{biz_name} నుంచి {an} మాట్లాడుతున్నాను అండి. ఒక చిన్న విషయం మాట్లాడటానికి కాల్ చేశాను అండి, ఒక్క నిమిషం టైమ్ ఉంటుందా అండి?"
        elif cfg.default_language == "hi":
            name_greet = f"नमस्ते {caller_name} जी! " if caller_name else "नमस्ते जी! "
            if is_medical:
                return f"{name_greet}मैं {biz_name} से {an} बोल रही हूँ जी। आपकी बुकिंग कन्फर्म करने के लिए कॉल किया है जी, क्या आपके पास एक मिनट है बात करने के लिए?"
            else:
                return f"{name_greet}मैं {biz_name} से {an} बोल रही हूँ जी। एक छोटी सी बात करने के लिए कॉल किया है जी, क्या आपके पास एक मिनट का समय होगा?"
        else:
            name_greet = f"Hello {caller_name}! " if caller_name else "Hello! "
            if is_medical:
                return f"{name_greet}{an} here from {biz_name}. Calling to confirm your booking. Do you have a minute?"
            else:
                return f"{name_greet}{an} here from {biz_name}. Just calling to speak with you for a quick moment. Do you have a minute?"
    else:
        if cfg.default_language == "te":
            if is_medical:
                return f"హలో అండి! {biz_name} కి స్వాగతం. నేను {an}ని, మీ కేర్ concierge. ఈరోజు మీకు ఎలా హెల్ప్ చేయగలను అండి?"
            else:
                return f"హలో అండి! {biz_name} కి స్వాగతం. నేను {an}ని, మీ డిజిటల్ అసిస్టెంట్. ఈరోజు నేను మీకు ఎలా హెల్ప్ చేయగలను అండి?"
        elif cfg.default_language == "hi":
            if is_medical:
                return f"नमस्ते जी! {biz_name} में आपका स्वागत है। मैं {an} हूँ, आपकी केयर concierge। आज मैं आपकी क्या हेल्प कर सकती हूँ जी?"
            else:
                return f"नमस्ते जी! {biz_name} में आपका स्वागत है। मैं {an} हूँ, आपकी डिजिटल असिस्टेंट। आज मैं आपकी क्या हेल्प कर सकती हूँ जी?"
        else:
            if is_medical:
                return f"Hello and welcome to {biz_name}! I'm {an}, your digital care concierge. How can I help you today?"
            else:
                return f"Hello and welcome to {biz_name}! I'm {an}, your digital assistant. How can I help you today?"


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    # DB POOL PREWARM (fire-and-forget): kick off Supabase asyncpg pool
    # creation IMMEDIATELY on the call's main event loop, in parallel
    # with the rest of the setup (cfg load, content refresh, phone
    # profile load, instructions build, tts.prewarm). On a cold worker,
    # asyncpg.create_pool() takes 2-3 sec (DNS + TLS + first conn auth);
    # without this pre-fire, that cost lands inside session.start() and
    # delays the FIRST call's opener by ~3 sec. With this pre-fire, the
    # pool is typically already warm by the time session.start awaits a
    # DB call. Subsequent calls reuse the module-global _pool (no cost).
    # Failure is silent: degrades to the existing lazy _get_pool() retry.
    from src import db as _db
    _db_warm_task = asyncio.ensure_future(_db._get_pool())
    # Stamp THIS call's id on every subsequent log line in this async
    # context (and any task it spawns). Concurrent calls running in
    # sibling worker subprocesses each have their own contextvar so
    # their log lines never cross-contaminate.
    set_call_id(ctx.room.name)
    call = resolve_call(ctx)
    direction, caller_name, forced_lang = (
        call.direction, call.name, call.language,
    )
    # Normalize dialer-supplied name capitalisation. Dialers often pass
    # "NAGASAI" or "nAGASAI" (Excel uppercase / OCR artifacts) — agent
    # then reads "nAGASAI గారు" literally. .title() gives "Nagasai".
    if caller_name:
        caller_name = caller_name.strip().title()
    logger.info(
        "connected to room %s (%s name=%r lang=%r script=%s)",
        ctx.room.name, direction, caller_name, forced_lang,
        bool(call.script),
    )

    # Make the caller's number available to the booking tools, and give
    # the agent a real "hang up" — delete the room (kicks the PSTN leg)
    # a few seconds after the goodbye so the final line finishes.
    from src.tools import caller_phone_var, end_call_var

    caller_phone_var.set(call.phone)

    # Idempotent: both the end_call tool AND the goodbye-phrase guard
    # (below in _on_item_added) call this — flag prevents double-fire.
    _end_fired = [False]

    async def _hangup() -> None:
        if _end_fired[0]:
            return
        _end_fired[0] = True
        await asyncio.sleep(4)  # let the goodbye line play out
        try:
            from livekit import api as _lkapi

            lk = _lkapi.LiveKitAPI(
                settings.livekit_url,
                settings.livekit_api_key,
                settings.livekit_api_secret,
            )
            await lk.room.delete_room(
                _lkapi.DeleteRoomRequest(room=ctx.room.name)
            )
            await lk.aclose()
        except Exception:
            logger.debug("hangup/delete_room failed", exc_info=True)

    end_call_var.set(_hangup)

    # Code-level goodbye guard: catch the bug where the LLM emits a
    # goodbye line ("మంచి రోజు అండి", "धन्यवाद जी", "bye") but never calls
    # the end_call tool — the call would hang forever waiting. Same class
    # as the VERBAL-CHECK-COMMITMENT bug, fixed at FSM layer not persona.
    # Patterns are TERMINAL goodbye markers (not "thank you" alone, which
    # is mid-conversation gratitude). Single source of truth, fires
    # _hangup which is idempotent so the persona-driven path still works.
    _GOODBYE_RE = re.compile(
        r"(?:^|[\s,.!?])(?:"
        # ── Group A: UNAMBIGUOUS terminal closers. Loose trailing
        # boundary — a following word is fine (these are closers
        # regardless of trailing tokens).
        r"(?:bye|good\s*bye|good\s*day|nice\s*day|good\s*night|"
        r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*day|"
        r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*evening|"
        r"have\s*a\s*(?:great|nice|wonderful|lovely|good)\s*night|"
        r"farewell|"
        # Telugu (Indic script + common Romanised variants)
        r"మంచి\s*రోజు|మంచి\s*రాత్రి|మంచి\s*సాయంత్రం|"
        r"ధన్యవాదాలు\s*అండి|మీ\s*సమయానికి\s*ధన్యవాదాలు|"
        r"మళ్ళీ\s*కలుద్దాం|జాగ్రత్తగా\s*ఉండండి|"
        r"బై\s*అండి|"
        r"manchi\s*roju|malli\s*kaludaam|bye\s*andi|"
        # Hindi/Urdu (Devanagari + Romanised)
        r"धन्यवाद\s*जी|शुभ\s*दिन|शुभ\s*रात्रि|शुभ\s*रात्री|शुभ\s*संध्या|"
        r"अलविदा|खुदा\s*हाफ़िज़|ख़ुदा\s*हाफ़िज़|"
        r"फिर\s*मिलेंगे|फिर\s*बात\s*करेंगे|अपना\s*ख्याल\s*रखिए|"
        r"alvida|khuda\s*hafiz|phir\s*milenge|apna\s*khayal\s*rakhiye)"
        r"(?:[\s,.!?]|$)"
        # ── Group B: AMBIGUOUS phrases that double as mid-sentence
        # speech ("I'll TAKE CARE of that", "SEE YOU tomorrow at the
        # clinic", "ALL THE BEST for your exam", "CHEERS to that").
        # Only treat as a goodbye when followed by a SENTENCE END or
        # end-of-string — a continuing word must NOT fire the hangup.
        # Telugu first-person verbs moved here from Group A: they double
        # as mid-sentence speech ("ముందుకు వెళ్తున్నాను" = proceeding,
        # "అందుబాటులో ఉంటాను అండి" = I'll be available) — only a
        # sentence-final use is a goodbye, else the agent hangs up on
        # its own progress statement.
        r"|(?:take\s*care|see\s*you|see\s*ya|all\s*the\s*best|cheers|"
        r"talk\s*(?:to\s*you\s*)?soon|catch\s*you\s*later|"
        r"వెళ్తున్నాను|ఉంటాను\s*అండి|veltunna|untanu\s*andi)"
        r"(?:\s*[.!?]|\s*$)"
        r")",
        re.IGNORECASE,
    )

    # v5: load the dashboard-editable RuntimeConfig (Redis -> Supabase ->
    # env defaults). Everything below is built from it, so dashboard
    # changes apply to the next call with no redeploy.
    cfg = await load_runtime_config()
    # Outbound campaigns can force a language → drives the opening voice.
    if forced_lang in ("te", "hi", "en"):
        cfg.default_language = forced_lang
    # PER-CAMPAIGN OVERRIDES: this campaign's own script/voice take
    # precedence over the global persona/voice for THIS call only, so
    # appointment & sales campaigns can run at the same time.
    if call.script:
        cfg.outbound_persona = call.script
    if call.voice_model:
        cfg.tts_model = call.voice_model
    if call.voice_speaker:
        cfg.tts_speaker_te = call.voice_speaker
        cfg.tts_speaker_hi = call.voice_speaker
        cfg.tts_speaker_en = call.voice_speaker
    # Use-case + content overrides: this campaign's own use-case/business/
    # style/KB take precedence over the global config for THIS call only,
    # so different-domain campaigns run isolated & correctly-scoped.
    if call.use_case:
        cfg.use_case_type = call.use_case
    if call.business_description:
        cfg.business_description = call.business_description
    if call.style_examples:
        cfg.style_examples = call.style_examples
    if call.kb_vector_store_id:
        cfg.kb_vector_store_id = call.kb_vector_store_id

    # Apply the dashboard-edited appointment grid (open/close/slot/days)
    # so persona _hours_facts(), tool messages, and _all_slots() all see
    # THIS business's hours for THIS call's prompt build.
    from src import db as _db_for_grid
    _db_for_grid._refresh_appt_grid(cfg)

    # NOTE: an earlier "invariant clamp" forced min_interruption_duration
    # below endpointing_delay based on a wrong mental model — those two
    # thresholds measure DIFFERENT events (interruption = caller speech
    # WHILE agent is talking; endpointing = silence AFTER caller stops),
    # they aren't comparable. The clamp dropped a working "0.7s — agent
    # rarely interrupted" setting to 0.55s and made the agent easy to
    # barge in on. The user's dashboard value is now passed through
    # untouched.

    # STARTUP LATENCY FIX: fire the 2 independent Redis loads (content
    # pool refresh, cross-call phone profile) IN PARALLEL instead of
    # sequentially. Each is a ~300-500ms round-trip; running them
    # together cuts ~500ms-1s off the pre-opener dead-air the caller
    # hears at the very start of every call. Both gracefully fall back
    # on failure — same behavior as the old sequential code.
    from src.memory import phone_profile_store as _phone_store
    _content_refresh_task = asyncio.ensure_future(
        content_store.refresh(settings.redis_url)
    )
    _phone_load_task = asyncio.ensure_future(
        _phone_store.load(call.phone or "")
    )

    instructions = (
        outbound_prompt(cfg) if direction == "outbound"
        else inbound_prompt(cfg)
    )
    if caller_name:
        instructions += (
            f"\n\nCALLER INFO: This caller's name is {caller_name}. "
            "You already know their name — do NOT ask for it again during this call."
        )
    # Round 7: cross-call memory. If we've spoken to this phone number
    # before, inject the prior-call hint so the opener naturally references
    # the previous topic instead of starting cold. Failure to load is silent
    # (any caller falls back to the standard cold-start opener — same as today).
    try:
        _prior_profile = await _phone_load_task
        _hint = _prior_profile.as_opener_hint()
        if _hint:
            instructions += f"\n\n{_hint}"
            logger.info(
                "round7 phone_profile loaded: phone=%s call_count=%d "
                "last_intent=%s",
                _prior_profile.phone[-4:] if _prior_profile.phone else "-",
                _prior_profile.call_count, _prior_profile.last_intent,
            )
    except Exception:
        logger.debug("round7 phone_profile load failed (non-fatal)", exc_info=True)
    # Wait for the content pool refresh to complete before session.start
    # (filler/canned pools must be loaded before the first turn). It has
    # been running in parallel since the start of this block so by now
    # it's almost always already done.
    try:
        await _content_refresh_task
    except Exception:
        logger.debug("content refresh failed (non-fatal)", exc_info=True)
    # Isolate the semantic cache PER BUSINESS: a cached answer from one
    # campaign/persona must never be served on a different one (the same
    # cross-business poison that hit the content pools). Same persona ->
    # shared cache; different script -> separate namespace.
    from src.cache import ns_for

    semantic_cache.namespace = ns_for(instructions)
    logger.info("semantic cache namespace=%s", semantic_cache.namespace)

    tts = build_tts(cfg)
    # Pre-warm Sarvam TTS WebSocket pool BEFORE session.start() so the
    # first turn's TTS doesn't pay TLS+WS handshake (~150-300ms) on top
    # of synthesis latency. Sarvam plugin's prewarm() warms the pool
    # synchronously (blocks ~500ms-1s). Run it in a thread executor so
    # it overlaps with the remaining setup (semantic-cache namespacing,
    # opener prep) instead of blocking on the call's main coroutine.
    # Awaited just before session.start() to guarantee the pool is hot
    # when the first TTS call fires.
    _prewarm_task = asyncio.create_task(asyncio.to_thread(tts.prewarm))

    turn_handling = {
        "turn_detection": build_turn_detection(),
        "endpointing": {
            "mode": "fixed",
            "min_delay": endpointing_delay_for(cfg.default_language, cfg),
            "max_delay": cfg.max_endpointing_delay,
        },
        "interruption": {
            "enabled": True,
            # MUST be "vad" not "adaptive" — Sarvam STT declares
            # aligned_transcript=False (verified in plugin source), and
            # LiveKit's adaptive interruption REQUIRES aligned transcripts.
            # With "adaptive" set, LiveKit silently disabled interruption
            # detection entirely with the warning:
            #   "interruption_detection is provided, but it's not
            #    compatible with the current configuration and will be
            #    disabled"
            # — meaning barge-in was effectively broken on every call.
            "mode": "vad",
            "min_duration": cfg.min_interruption_duration,
            # Backchannels must NOT cut the agent: live call 2026-06-12
            # (out-27691b1ea2) — caller acks "అవును" / "ఆ ఇది" barged in
            # mid-sentence on every long answer. A human keeps talking
            # through a listener's "haan". <3 transcribed words = ack,
            # not an interruption; the words still land as a queued turn.
            "min_words": 3,
            "resume_false_interruption": True,
            "false_interruption_timeout": 2.0,
        },
        "preemptive_generation": {
            "enabled": True,
        }
    }

    session = AgentSession(
        stt=build_stt(cfg),
        llm=build_llm(cfg),
        tts=tts,
        vad=ctx.proc.userdata["vad"],
        turn_handling=turn_handling,
    )

    # PHASE 10: per-call cancellation registry + speculative prefetch +
    # transcript stabilizer.
    registry = CancellationRegistry(call_id=ctx.room.name)
    stabilizer = TranscriptStabilizer()
    predictive = PredictivePrefetch()

    # PHASE 3/10: FSM whose INTERRUPTED transition fires token-level
    # cancellation; bound to session lifecycle events.
    fsm = _make_fsm(session, registry)
    _bind_fsm(session, fsm, stabilizer)

    # PHASE 9: structured per-call memory (Redis-backed, local fallback).
    # Loaded BEFORE the transcription handler so the handler can capture
    # `memory` in its closure and feed the latest emotion into the
    # per-turn TTS pace retune (Round 2: sentiment-aware pacing).
    memory = await memory_store.load(ctx.room.name)
    # Seed known caller name (from the campaign/dialer) so the agent can
    # greet by name and the persona/memory carry it from turn one.
    if caller_name:
        memory.name = caller_name
        if forced_lang in ("te", "hi", "en"):
            memory.language = forced_lang

    # PHASE 6/10: language-aware TTS retune + stabilizer/predictive feed.
    _attach_transcription(
        session, tts, cfg, stabilizer, predictive, registry, memory
    )

    # PHASE 5/7/8: Fast Intent Router with the Redis semantic-cache
    # resolver injected (similarity threshold from the dashboard config).
    # Action resolver stays None — order/payment intents use the LLM +
    # function tools so we can collect ids conversationally.
    router = IntentRouter()
    router.set_cache_resolver(
        lambda q: semantic_cache.lookup(q, cfg.cache_min_similarity)
    )

    # PHASE 8: per-call cost metering; logged at end of call.
    meter = CallMeter()
    _safe_session_on(session, "close", lambda _ev=None: meter.log())

    # PHASE 11: echo/duplex guard + adaptive buffering.
    echo = EchoGuard()
    abuf = AdaptiveBuffer()

    # Real-time backchanneling (active-listening acks). No-op unless
    # settings.backchannel_enabled. Wired here (after echo exists) so the
    # ack is fed to the echo guard and never mis-heard as caller speech.
    _attach_backchannel(session, tts, cfg, echo, memory)

    def _on_agent_state_echo(ev) -> None:
        st = getattr(ev, "new_state", getattr(ev, "state", None))
        if st == "speaking":
            echo.on_agent_started()
        elif st in ("listening", "idle"):
            echo.on_agent_stopped()

    _safe_session_on(session, "agent_state_changed", _on_agent_state_echo)

    # PHASE 12: telephony resilience (STT restart, TTS fallback, link
    # degradation, call-drop -> CALL_END).
    TelephonyResilience(
        session, ctx.room, tts, fsm, abuf, echo, cfg,
        on_hangup=_hangup,
    ).attach()

    # Caller gender detection via F0 (pitch). Runs on the caller's audio
    # track in a background task — never blocks the opener or critical
    # path. Result (~2s after caller starts speaking) flips cfg.caller_gender
    # from "unknown" to "male"/"female", which llm_node then picks up
    # to inject gender-aware honorifics for every subsequent turn.
    from src.gender import detect_caller_gender as _detect_gender
    from livekit import rtc as _rtc

    _gender_spawned: set[str] = set()

    def _spawn_gender_for(track, participant) -> None:
        # Only the caller's mic track (audio + remote). Skip the agent's
        # own published audio and any data/video tracks. Run once per call.
        if track.kind != _rtc.TrackKind.KIND_AUDIO:
            return
        if not isinstance(track, _rtc.RemoteAudioTrack):
            return
        if _gender_spawned:
            return
        _gender_spawned.add(participant.identity)
        logger.info(
            "gender_detect: ATTACHED to caller=%s sid=%s room=%s",
            participant.identity, getattr(track, "sid", "?"), ctx.room.name,
        )

        def _on_gender_done(gender: str, median_f0: float) -> None:
            cfg.caller_gender = gender
            logger.info(
                "caller_gender=%s f0=%.1fHz room=%s",
                gender, median_f0, ctx.room.name,
            )

        asyncio.create_task(_detect_gender(track, _on_gender_done))

    # Catch tracks subscribed BEFORE this handler attaches (typical for
    # inbound — caller is already in the room by the time entrypoint runs).
    for p in ctx.room.remote_participants.values():
        for pub in p.track_publications.values():
            if pub.track is not None:
                _spawn_gender_for(pub.track, p)

    # And tracks that subscribe AFTER (typical for outbound — SIP leg
    # joins the room a few seconds after the agent dials out).
    def _on_track_subscribed(track, _publication, participant) -> None:
        _spawn_gender_for(track, participant)

    try:
        ctx.room.on("track_subscribed", _on_track_subscribed)
    except Exception:
        logger.debug("gender: track_subscribed hook failed", exc_info=True)

    # v4: per-call telemetry -> Redis (powers the admin dashboard).
    # The Call row INSERT is awaited synchronously — small fast write
    # (~50-100ms direct INSERT) and the ONLY way to guarantee that a
    # call which CONNECTED at SIP but then died (worker restart, crash,
    # SIGKILL) still leaves a durable record in Supabase. Previously
    # this was fire-and-forget inside tel.start(); if the worker process
    # was killed before that spawned task ran, the Call row was never
    # written even though the SIP leg connected and rang the callee —
    # the call effectively vanished from the dashboard ("had a call but
    # not stored" bug). Redis writes / pub-sub stay fire-and-forget
    # below, so the slow path (Supabase SSL blip) still doesn't block
    # the opener.
    telemetry = CallTelemetry(ctx.room.name, ctx.room.name, direction)
    # Expose telemetry on the session so the FSM's agent_state handler
    # can record the end-to-end perceived latency (caller stops -> agent
    # first audio) per turn. Set here, read defensively there.
    try:
        session._telemetry = telemetry  # type: ignore[attr-defined]
    except Exception:
        pass
    from src import db as _db
    try:
        ok = await _db.upsert_call(
            ctx.room.name, room=ctx.room.name, direction=direction,
            status="live",
        )
        # Mark telemetry's _call_ready so subsequent _ensure_call()
        # invocations skip the redundant retry — they'd succeed anyway,
        # but skipping saves a per-turn DB round-trip on the hot path.
        if ok:
            telemetry._call_ready = True
    except Exception:
        # Fail open: the lazy _ensure_call() retry inside telemetry.turn()
        # still has the safety net. We only LOG so a recurring Supabase
        # outage is visible instead of silent.
        logger.warning(
            "initial upsert_call FAILED room=%s — lazy _ensure_call will "
            "retry on first turn", ctx.room.name, exc_info=True,
        )
    # Redis writes + pub-sub remain fire-and-forget so a slow/flaky
    # Redis cannot delay the opener by up to 4s (the "late response"
    # complaint that motivated this split).
    telemetry.spawn(telemetry.start())

    # Real per-stage latency — so the "5-6s" is MEASURED, not guessed.
    # eou_delay  = time from caller stopping -> end-of-turn detected
    #              (VAD/endpointing/CPU part)
    # llm_ttft   = time to the LLM's first token (model + network)
    # tts_ttfb   = time to the first audio byte (Sarvam + network)
    # prompt cached tokens proves whether OpenAI prompt-caching hits.
    from livekit.agents import metrics as _m

    def _on_metrics(ev) -> None:
        mx = getattr(ev, "metrics", ev)
        try:
            if isinstance(mx, _m.EOUMetrics):
                logger.info(
                    "METRIC eou_delay=%.2fs transcription_delay=%.2fs",
                    mx.end_of_utterance_delay, mx.transcription_delay,
                )
                telemetry.record_latency("eou", mx.end_of_utterance_delay)
            elif isinstance(mx, _m.LLMMetrics):
                logger.info(
                    "METRIC llm_ttft=%.2fs dur=%.2fs prompt=%d cached=%d "
                    "out=%d", mx.ttft, mx.duration, mx.prompt_tokens,
                    mx.prompt_cached_tokens, mx.completion_tokens,
                )
                telemetry.record_latency("llm_ttft", mx.ttft)
            elif isinstance(mx, _m.TTSMetrics):
                logger.info(
                    "METRIC tts_ttfb=%.2fs dur=%.2fs chars=%d",
                    mx.ttfb, mx.duration, mx.characters_count,
                )
                telemetry.record_latency("tts_ttfb", mx.ttfb)
        except Exception:
            logger.debug("metrics log failed", exc_info=True)

    _safe_session_on(session, "metrics_collected", _on_metrics)

    def _on_item_added(ev) -> None:
        item = getattr(ev, "item", ev)
        role = getattr(item, "role", None)
        if role == "assistant":
            txt = _message_text(item)
            # CRITICAL: feed the echo guard EVERY agent utterance. It
            # used to only see canned/filler (via _say); the LLM reply
            # and the opener bypassed it, so the agent's own voice came
            # back through STT and was treated as a caller turn -> the
            # repeating-nonsense loop.
            if txt:
                echo.on_agent_started(txt)
            # Fillers ARE now recorded in the Transcript table (operator
            # request: full call audit / consistency check needs every
            # spoken word visible, not hidden as "UX cover").
            telemetry.spawn(telemetry.turn("agent", txt))
            # Goodbye-guard: if the agent emitted a terminal goodbye
            # phrase but the LLM never invoked end_call, schedule the
            # hangup ourselves so the call doesn't dangle forever.
            # _hangup is idempotent — if the tool DOES fire, this is a
            # no-op; if it doesn't, this catches the leak.
            if txt and not _end_fired[0] and _GOODBYE_RE.search(txt):
                logger.info(
                    "end_call guard: terminal goodbye detected without "
                    "tool call, scheduling fallback hangup"
                )
                asyncio.ensure_future(_hangup())

    _safe_session_on(session, "conversation_item_added", _on_item_added)
    # Call-end persistence MUST finish before the job process exits. The
    # old `session.on("close", ensure_future(telemetry.end()))` was
    # fire-and-forget — the room-delete/job teardown killed that task
    # before the Supabase UPDATE ran, so calls stayed status="live" with
    # endedAt=NULL (the "history not storing" bug). add_shutdown_callback
    # is AWAITED by livekit-agents during shutdown -> the write lands.
    async def _final_flush_and_end():
        # One last metrics flush so the LAST turn's llm_ttft / tts_ttfb
        # (which fire AFTER the final on_user_turn_completed _persist())
        # land in the Call row before the call goes ended. Without this,
        # the dashboard's per-call latency would miss the closing turn.
        try:
            await telemetry.update_metrics(meter)
        except Exception:
            logger.debug("final update_metrics failed", exc_info=True)
        await telemetry.end()
    ctx.add_shutdown_callback(_final_flush_and_end)
    # Round 7: snapshot the in-memory CallMemory into the suggested
    # CallerProfile at call end so the dashboard operator can approve it
    # before it is applied to the active CallerProfile. Awaited via
    # add_shutdown_callback so the Redis write actually lands before
    # the job process exits. Non-fatal on Redis failure.
    async def _save_phone_profile():
        try:
            from src.memory import phone_profile_store as _pps
            await _pps.save_suggestion_from_memory(ctx.room.name, call.phone or "", memory)
        except Exception:
            logger.debug("round7 phone_profile suggestion save failed", exc_info=True)
    ctx.add_shutdown_callback(_save_phone_profile)

    voice_agent = VoiceAgent(
        instructions, router, meter, memory, predictive, echo,
        telemetry, cfg, stabilizer,
    )
    # Let the booking tools force a fresh table-snapshot read on the
    # very next turn after they write — without this the agent's cached
    # snapshot could be up to 6s stale immediately after a successful
    # book/reschedule.
    from src.tools import appt_snapshot_invalidate_var, kb_id_var
    appt_snapshot_invalidate_var.set(voice_agent._invalidate_appt_snapshot)
    kb_id_var.set(cfg.kb_vector_store_id)

    # Build the opener prompt now so the LLM call can start in parallel
    # with session.start() — saves 2-4s of dead air before first word.
    _LN = {"te": "Telugu", "hi": "Hindi", "en": "English"}
    lang_name = _LN.get(cfg.default_language, "the caller's language")
    by_name = f" Greet them by name ({caller_name})." if caller_name else ""
    opener = (
        f"Speak ONLY in {lang_name}. One short sentence: warm intro "
        "(your name + the business). Then ONE short sentence giving the "
        "concrete REASON for the call from your persona/BUSINESS CONTEXT "
        "(never vague — they must know why you called). Then ask if they "
        f"have a minute. 2 short sentences, simple words.{by_name}"
        if direction == "outbound"
        else f"Speak ONLY in {lang_name}. Greet the caller in one short "
        "sentence as a human support executive and ask how you can help. "
        "Under 10 words."
    )

    # Round 9-lite: opener TEXT cache per (campaign-instructions, language).
    # Stores up to _OPENER_CACHE_MAX variants in Redis with a long TTL; on
    # call start we randomly pick one already-baked variant — skipping the
    # LLM call entirely on a hit. Variation across calls is preserved
    # because we keep multiple variants per campaign/language, not one.
    # Falls through cleanly to live LLM generation if cache is cold/Redis
    # is unreachable (same behavior as before this feature landed).
    _OPENER_CACHE_PREFIX = "opener_cache:"
    _OPENER_CACHE_MAX = 5
    _OPENER_CACHE_TTL = 60 * 60 * 24 * 30  # 30 days

    def _opener_cache_key() -> str:
        import hashlib
        sig = hashlib.sha1(
            (instructions + "|" + (forced_lang or cfg.default_language)).encode(
                "utf-8", errors="replace"
            )
        ).hexdigest()[:24]
        return f"{_OPENER_CACHE_PREFIX}{sig}"

    async def _cached_opener_pick() -> str:
        """Pick a random cached opener if at least one variant exists.
        Empty string on cache miss or Redis failure."""
        try:
            import redis.asyncio as redis
            r = redis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
            )
            blob = await r.get(_opener_cache_key())
            if not blob:
                return ""
            import json, random
            variants = json.loads(blob)
            if isinstance(variants, list) and variants:
                return random.choice(variants)
        except Exception:
            logger.debug("round9 opener cache read failed", exc_info=True)
        return ""

    async def _cached_opener_append(text: str) -> None:
        """Append a freshly generated opener to the cache (LRU-bounded)."""
        if not text:
            return
        try:
            import redis.asyncio as redis
            import json
            r = redis.from_url(
                settings.redis_url, decode_responses=True,
                socket_connect_timeout=2, socket_timeout=2,
            )
            key = _opener_cache_key()
            blob = await r.get(key)
            variants = json.loads(blob) if blob else []
            if not isinstance(variants, list):
                variants = []
            if text in variants:
                return  # de-dup exact repeats
            variants.append(text)
            if len(variants) > _OPENER_CACHE_MAX:
                variants = variants[-_OPENER_CACHE_MAX:]
            await r.set(
                key,
                json.dumps(variants, ensure_ascii=False),
                ex=_OPENER_CACHE_TTL,
            )
        except Exception:
            logger.debug("round9 opener cache write failed", exc_info=True)

    async def _prebake_opener(prompt: str) -> str:
        # Round 9-lite: try the variant cache first — skip the live LLM
        # call on a hit. ~1 LLM call saved per call for repeat campaigns.
        cached = await _cached_opener_pick()
        if cached:
            logger.info("round9 opener served from cache")
            return cached
        try:
            import openai as _oai
            c = _oai.AsyncOpenAI(api_key=settings.openai_api_key)
            r = await c.chat.completions.create(
                model=cfg.llm_model or "gpt-4o-mini",
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=80,
                temperature=0.4,
            )
            text = (r.choices[0].message.content or "").strip()
            # Persist new variant for the next caller in this campaign.
            if text:
                await _cached_opener_append(text)
            return text
        except Exception:
            logger.debug("opener prebake failed", exc_info=True)
            return ""

    # Hook up the instant local opener to bypass the slow LLM call
    local_txt = _local_opener_for(cfg, direction, caller_name)
    if local_txt:
        logger.info("Serving instant local opener: %r", local_txt)
        # Wrap in a future that resolves immediately to maintain FSM compatibility
        fut = asyncio.Future()
        fut.set_result(local_txt)
        _opener_task = fut
    else:
        _opener_task = asyncio.ensure_future(_prebake_opener(opener))

    # Ensure the TTS WebSocket pool is warmed BEFORE session.start fires
    # the first synth call. By now the prewarm task (kicked off right
    # after build_tts) has been running in parallel for ~hundreds of ms;
    # this await is typically a no-op cost on the warm path.
    try:
        await _prewarm_task
    except Exception:
        logger.debug("tts.prewarm failed (non-fatal)", exc_info=True)

    # NOTE: Telugu-aware sentence streaming was previously wired by passing
    # `sentence_tokenizer=` to session.start(). The installed LiveKit
    # version (AgentSession.start) does NOT accept that argument and it
    # raised TypeError on every call — the agent connected, played the
    # opener, then crashed (silent call / no transcript). Sentence
    # streaming must be configured on the TTS/Agent node for this SDK
    # version, not here. Removed the unsupported kwarg so calls work.
    await session.start(
        room=ctx.room,
        agent=voice_agent,
        room_input_options=build_room_input_options(),
    )

    if direction == "outbound":
        # Wait for the callee to actually answer the phone and join the room
        # before speaking the opener — otherwise the agent speaks to an empty
        # room while the phone is still ringing and the callee hears only silence!
        if not ctx.room.remote_participants:
            logger.info("Outbound call: waiting for callee to join the room...")
            event = asyncio.Event()

            def _on_participant_connected(participant):
                logger.info("Callee joined (event-driven)! Setting event.")
                event.set()

            ctx.room.on("participant_connected", _on_participant_connected)

            # Double check in case they connected while we registered the listener
            if ctx.room.remote_participants:
                event.set()

            try:
                await asyncio.wait_for(event.wait(), timeout=30.0)
                logger.info("Callee joined! Proceeding to speak opener.")
            except asyncio.TimeoutError:
                logger.warning("Outbound call: callee did not join within 30 seconds. Proceeding anyway.")
            finally:
                try:
                    ctx.room.off("participant_connected", _on_participant_connected)
                except Exception:
                    pass
        else:
            logger.info("Outbound call: callee already in room. Proceeding to speak opener.")

    _prebaked = await _opener_task
    if _prebaked:
        await session.say(_prebaked)
    else:
        await session.generate_reply(instructions=opener)


def main() -> None:
    # The livekit-agents CLI reads LIVEKIT_* from os.environ and does NOT
    # load our .env, so pass credentials explicitly from our settings.
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            agent_name=settings.agent_name,
            ws_url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            # Keep reconnecting through DNS/network blips instead of
            # exhausting the library's default 16 retries and zombie-ing
            # out (the documented #1 dead-air cause). The watchdog's
            # active /health probe respawns a worker that stays stuck.
            max_retry=settings.worker_max_retry,
            # Pin the built-in health server to a deterministic
            # loopback address:port so the watchdog can probe LiveKit's
            # authoritative registration signal (GET / -> 503 "failed to
            # connect to livekit" the moment it's unregistered) instead
            # of scraping a binary-polluted stderr log.
            host="127.0.0.1",
            port=settings.worker_port,
            # SINGLE-WORKER setup: the default CPU-load threshold (~0.75)
            # was marking this lone worker "unavailable" when the laptop
            # was busy — and with no backup worker, LiveKit then had
            # NOBODY to put in the call -> the caller got dead air (the
            # "client call didn't communicate" failures). Never let the
            # only worker refuse a call: a slightly slow answer beats
            # silence. >1.0 effectively disables load-based eviction.
            load_threshold=10.0,
            # CONCURRENT CALLS: dev mode defaults num_idle_processes=0,
            # so every campaign call spawned a fresh subprocess from
            # scratch — burst dialing meant most jobs queued or were
            # dropped by LiveKit, and only the first call's transcript
            # ever made it to DB (the "only one logs store avtundi" bug).
            # 8 warm processes => 8 truly-concurrent campaign calls on
            # this single worker without cold-start cost.
            num_idle_processes=settings.worker_num_idle_processes,
        )
    )


if __name__ == "__main__":
    main()
