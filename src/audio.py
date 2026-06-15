"""Audio: echo / duplex handling + adaptive buffering.

Real SIP calls fail in classic ways: the agent hears its own TTS
(echo), echo loops, or both sides talk at once (double speech). And a
fixed jitter buffer either adds latency on a good network or stutters on
a bad one. This module addresses all three:

  * `build_room_input_options()` — turn on noise cancellation / AEC at
    the LiveKit input edge.
  * `EchoGuard` — detect the agent transcribing its own speech and fall
    back to half-duplex (ignore input while the agent is speaking).
  * `AdaptiveBuffer` — watch connection quality and recommend a
    larger/smaller buffer (logged + used to bias half-duplex on bad
    links).
"""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field

from livekit.agents import RoomInputOptions

# Strip punctuation / quotes / extra whitespace so an echo match isn't
# defeated by a comma or period that STT dropped from the agent's TTS.
_NORM_PUNCT = re.compile(r"[^\w\sఀ-౿ऀ-ॿ]+", re.UNICODE)


def _norm(text: str) -> str:
    """Lowercase + drop punctuation + collapse whitespace. Used so an
    STT transcript without commas/periods still matches a TTS phrase
    that contained them ('Sorry sir, malli cheppandi.' ↔ 'sorry sir
    malli cheppandi')."""
    if not text:
        return ""
    t = _NORM_PUNCT.sub(" ", text.lower())
    return " ".join(t.split())

logger = logging.getLogger("audio")


def build_room_input_options() -> RoomInputOptions:
    """LiveKit input-edge config for telephony.

    IMPORTANT: we do NOT enable the BVC noise-cancellation filter here.
    On real SIP/PSTN calls it is 8 kHz narrowband audio; BVC is built
    for wideband mic input and fails to initialize ("failed to
    initialize the audio filter"), which silently breaks the caller's
    inbound audio path — STT receives nothing and the agent never
    responds. Telephony already provides reasonable audio; echo is
    handled by EchoGuard. Keep the input path clean.

    close_on_disconnect=False: on SIP/PSTN (esp. a loaded host or flaky
    trunk) a brief signalling blip emits a spurious
    `participant_disconnected` right after the opener — default True
    then KILLS the live session instantly (caller still on the line =
    "agent said one line then went dead, turns=0"). False lets the
    session survive a transient blip; a REAL sustained hangup is still
    ended by the resilience disconnect handler + the agent's own
    end_call / room-delete path. The livekit log explicitly recommends
    this exact toggle for this symptom.
    """
    return RoomInputOptions(close_on_disconnect=False)


@dataclass
class EchoGuard:
    """Heuristic playback-suppression / half-duplex fallback.

    If a 'user' transcript arrives that closely matches what the agent
    just said while it was speaking, that's echo. Repeated echo flips a
    half-duplex mode (suppress input while the agent speaks) — but that
    mode is now TIME-BOXED: it used to latch forever, so after two echo
    hits the caller could never be heard again and the agent just
    monologued. It now auto-clears after a quiet stretch so the caller
    always gets their voice back.

    Tracks the LAST 5 TTS phrases (deque) AND a post-stop window so
    delayed echoes of mishear-acks / canned phrases don't slip through
    just because `_agent_speaking` already flipped to False. This is the
    fix for the real-call feedback loop where the agent's own
    "Sorry sir, malli cheppandi" returned via mic leakage and triggered
    another round of the mishear gate — 4 acks back-to-back.
    """

    # Half-duplex auto-recovers this many seconds after the last echo.
    _HALF_DUPLEX_TTL = 6.0
    # How long AFTER the agent stops to keep matching candidate echoes
    # of recent TTS phrases. PSTN lag + STT buffering can deliver the
    # echo transcript up to ~2s after the actual TTS playback ended.
    _POST_STOP_ECHO_WINDOW = 2.0
    # How many recent TTS phrases to remember (covers a typical bursty
    # turn — opener + filler + main reply + ack).
    _RECENT_TTS_LIMIT = 5

    _agent_speaking: bool = False
    _last_tts: str = ""
    _recent_tts: deque = field(default_factory=lambda: deque(maxlen=5))
    _stopped_at: float = 0.0
    _echo_hits: int = 0
    half_duplex: bool = False
    _last_echo_ts: float = 0.0

    def on_agent_started(self, text: str = "") -> None:
        self._agent_speaking = True
        if text:
            # Store the normalised form so echo matching survives the
            # punctuation drift between TTS text and STT transcript.
            norm = _norm(text)
            self._last_tts = norm
            self._recent_tts.append(norm)

    def on_agent_stopped(self) -> None:
        self._agent_speaking = False
        self._stopped_at = time.monotonic()

    def force_half_duplex(self) -> None:
        """Force half-duplex from an EXTERNAL signal (e.g. link
        degradation), not an echo hit. We stamp `_last_echo_ts = now` so
        the TTL-based `_maybe_recover` keeps it active for the normal
        window instead of clearing it on the very next caller input
        (the old bug: link-forced half-duplex had _last_echo_ts=0, so
        now-0 > TTL was always true → the protection was a no-op). While
        the link stays bad, repeated quality events refresh the stamp;
        once it recovers, half-duplex auto-clears after the TTL."""
        now = time.monotonic()
        self._last_echo_ts = now
        if not self.half_duplex:
            self.half_duplex = True
            logger.warning(
                "link degraded -> half-duplex (auto-clears %.0fs after "
                "link recovers)", self._HALF_DUPLEX_TTL,
            )

    def _maybe_recover(self, now: float) -> None:
        """Drop half-duplex once echo has been quiet for a while so a
        real caller turn is never suppressed indefinitely."""
        if (
            self.half_duplex
            and now - self._last_echo_ts > self._HALF_DUPLEX_TTL
        ):
            self.half_duplex = False
            self._echo_hits = 0
            logger.info("echo quiet -> half-duplex cleared, caller audible")

    def _matches_recent_tts(self, ut: str) -> bool:
        """True if user_text overlaps any of the last 5 TTS phrases.
        Matching is intentionally lenient (`ut in tts` OR `tts[:20] in ut`)
        because STT often renders agent echo with minor distortion. Both
        sides are punctuation-normalised so commas/periods don't defeat
        the substring check."""
        ut_n = _norm(ut)
        if not ut_n:
            return False
        for tts in self._recent_tts:
            if not tts:
                continue
            if ut_n in tts or tts[:20] in ut_n:
                return True
        # Backward-compat: also check _last_tts in case it wasn't in deque.
        if self._last_tts and (
            ut_n in self._last_tts or self._last_tts[:20] in ut_n
        ):
            return True
        return False

    def is_echo(self, user_text: str) -> bool:
        """True if this 'user' input should be dropped as our own echo.

        Also drops TRIVIAL caller acks ("okay / ఆ / haan") that arrive
        WHILE the agent is mid-sentence. LiveKit's interruption layer
        will have already cut our TTS — we can't un-cancel that — but
        dropping the ack-turn here prevents it from entering chat
        history, which kept causing the LLM to "respond" to the ack and
        cascade into restarting the greeting / repeating the question.
        Result: faster recovery, smoother conversation."""
        now = time.monotonic()
        self._maybe_recover(now)
        ut = (user_text or "").strip().lower()
        if not ut:
            return False

        # POST-STOP window: if agent stopped speaking <= 2s ago AND the
        # transcript matches any of the last 5 TTS phrases, treat as
        # echo. Kills the mishear-ack feedback loop where TTS echo lands
        # AFTER on_agent_stopped() — without this guard the loop fires
        # the gate again. Independent of half-duplex state.
        in_post_stop = (
            not self._agent_speaking
            and self._stopped_at > 0
            and (now - self._stopped_at) <= self._POST_STOP_ECHO_WINDOW
        )
        if in_post_stop and self._matches_recent_tts(ut):
            self._echo_hits += 1
            self._last_echo_ts = now
            logger.debug(
                "dropped post-stop echo of recent TTS: %r", ut[:40],
            )
            return True

        if not self._agent_speaking:
            return False

        if self._matches_recent_tts(ut):
            self._echo_hits += 1
            self._last_echo_ts = now
            if self._echo_hits >= 2 and not self.half_duplex:
                self.half_duplex = True
                logger.warning(
                    "echo detected -> half-duplex (auto-clears in %.0fs)",
                    self._HALF_DUPLEX_TTL,
                )
            return True
        # Trivial caller ack while agent is mid-utterance: deliberately
        # drop. The classifier is lazy-imported here so audio.py stays
        # importable in unit tests with no router deps. Native-script
        # one-char Indic acks ("ఆ", "హా") aren't caught by the Roman-only
        # classifier, so they're matched against a small explicit set first.
        # Drop ONLY known tiny acks during agent speech — never a bare
        # number or a legit short answer ("no", "5", "10"), which an
        # appointment caller really says. The old blanket `len(ut) <= 2`
        # swallowed digits + short answers → dropped caller turns → the
        # "caller spoke, agent went silent" dead-air we are fixing.
        _TINY_ACKS = {
            "ఆ", "హా", "హ", "ఏ", "ఓకే", "haan", "हाँ", "हा",
            "ha", "haa", "hmm", "mm", "ok", "okay",
        }
        if ut in _TINY_ACKS and not ut.isdigit():
            logger.debug("dropped trivial-ack during agent speech: %r", ut[:30])
            return True
        try:
            from src.router.classifier import classify
            cls = classify(user_text)
            if cls.is_trivial and cls.intent in {"affirm", "deny", "repeat"}:
                logger.debug("dropped trivial-ack during agent speech: %r", ut[:30])
                return True
        except Exception:
            pass
        # In half-duplex we suppress input that arrives WHILE we speak,
        # but only until the TTL recovery above frees it — never forever.
        if self.half_duplex:
            return True
        return False


@dataclass
class AdaptiveBuffer:
    """Bias buffering by live connection quality.

    LiveKit manages the low-level jitter buffer; we can't resize it
    per-packet, but we CAN react to sustained degradation: widen our
    endpointing tolerance and prefer half-duplex on poor links, and
    return a recommended buffer (ms) for logging/telemetry.
    """

    min_ms: int = 40
    max_ms: int = 200
    current_ms: int = 60
    _bad_since: float | None = field(default=None)

    def on_quality(self, quality: str) -> int:
        """quality in {"excellent","good","poor","lost"} (LiveKit)."""
        q = (quality or "").lower()
        if q in ("poor", "lost"):
            self._bad_since = self._bad_since or time.monotonic()
            self.current_ms = min(self.max_ms, int(self.current_ms * 1.5))
        else:
            self._bad_since = None
            self.current_ms = max(self.min_ms, int(self.current_ms * 0.9))
        return self.current_ms

    @property
    def degraded(self) -> bool:
        return self._bad_since is not None
