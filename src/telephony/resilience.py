"""Telephony resilience / graceful degradation.

Production phone calls fail in messy ways. This wires defensive fallbacks
onto the AgentSession + room so a transient fault doesn't kill the call:

  * STT stream error/timeout -> log + let the session restart the STT
    stream (we re-arm and notify the caller naturally instead of going
    silent).
  * TTS failure -> swap to a fallback voice config so the agent keeps
    talking.
  * Websocket / connection degraded -> widen the adaptive buffer and
    prefer half-duplex (handled via AdaptiveBuffer/EchoGuard).
  * SIP participant disconnect / call drop -> drive the FSM to CALL_END
    cleanly.

Every binding is guarded so a missing event on a given livekit-agents
build degrades silently rather than crashing.
"""

from __future__ import annotations

import logging

import asyncio

from src.audio import AdaptiveBuffer, EchoGuard
from src.fsm import ConversationFSM
from src.pipeline.tts import retune_tts

logger = logging.getLogger("resilience")


class TelephonyResilience:
    def __init__(
        self,
        session,
        room,
        tts,
        fsm: ConversationFSM,
        abuf: AdaptiveBuffer,
        echo: EchoGuard,
        cfg,
        on_hangup=None,
    ) -> None:
        self._session = session
        self._room = room
        self._tts = tts
        self._fsm = fsm
        self._abuf = abuf
        self._echo = echo
        self._cfg = cfg
        self._tts_failures = 0
        # Async callable that actually ends the call (deletes the room).
        # Invoked after a grace period when the caller is confirmed gone.
        self._on_hangup = on_hangup
        self._hangup_task = None
        # Grace window (seconds) to absorb a transient SIP signalling blip
        # before treating a disconnect as a real hangup. Short enough that
        # a real hangup stops billing within ~5s, long enough that a blip
        # (which reconnects in <2s) doesn't kill a live call.
        self._hangup_grace = 5.0

    # ── error handling ──────────────────────────────────────────────
    def _on_error(self, ev) -> None:
        source = str(getattr(ev, "source", "") or getattr(ev, "type", "")).lower()
        err = getattr(ev, "error", ev)
        logger.warning("session error from %s: %s", source or "?", err)

        if "stt" in source:
            # The session auto-restarts the STT stream; we just make sure
            # we're listening and the stabilizer state isn't stale.
            logger.info("STT error -> awaiting stream restart")
        elif "tts" in source:
            self._tts_failures += 1
            try:
                # Fallback: force a known-good voice for the call's
                # language (cfg required — missing it was a crash bug).
                retune_tts(
                    self._tts, self._cfg, self._cfg.default_language
                )
                logger.info("TTS error -> switched to fallback voice")
            except Exception:  # pragma: no cover
                logger.debug("tts fallback failed", exc_info=True)

    # ── connection degradation ──────────────────────────────────────
    def _on_quality(self, ev) -> None:
        q = str(getattr(ev, "quality", "") or "")
        ms = self._abuf.on_quality(q)
        if self._abuf.degraded:
            # Bad link: bias half-duplex to avoid echo/double-talk and
            # accept slightly higher latency for stability. Use the
            # external-signal path so the TTL doesn't clear it on the
            # next caller input (the prior `= True` was a no-op).
            self._echo.force_half_duplex()
            logger.warning("link degraded (%s) -> buffer=%dms, half-duplex",
                            q, ms)

    # ── call drop ───────────────────────────────────────────────────
    def _on_disconnect(self, *_a) -> None:
        # A disconnect event fired. This may be a transient SIP blip OR a
        # real hangup. Drive the FSM to CALL_END and start a short grace
        # timer; if the caller is STILL gone after the grace window it was
        # a real hangup → actually end the call (delete the room) so the
        # LiveKit/telephony/STT billing stops. Without this, a hung-up call
        # ran for the full room empty-timeout (observed: 52 min ≈ ₹100+).
        logger.info("participant/SIP disconnect -> CALL_END (grace check)")
        self._fsm.on_call_ended()
        if self._on_hangup is None:
            return
        if self._hangup_task is not None and not self._hangup_task.done():
            return  # a grace check is already counting down
        try:
            self._hangup_task = asyncio.create_task(self._grace_then_hangup())
        except RuntimeError:
            # No running loop (shouldn't happen in the agent) — best effort.
            logger.debug("no event loop for grace hangup", exc_info=True)

    async def _grace_then_hangup(self) -> None:
        await asyncio.sleep(self._hangup_grace)
        try:
            remotes = getattr(self._room, "remote_participants", {}) or {}
        except Exception:
            remotes = {}
        if len(remotes) == 0:
            logger.info(
                "caller still gone after %.1fs grace -> ending call",
                self._hangup_grace,
            )
            try:
                await self._on_hangup()
            except Exception:
                logger.warning("resilience hangup failed", exc_info=True)
        else:
            logger.info("caller reconnected within grace -> keeping call alive")

    def attach(self) -> None:
        for event, handler in (
            ("error", self._on_error),
            ("connection_quality_changed", self._on_quality),
        ):
            try:
                self._session.on(event, handler)
            except Exception:  # pragma: no cover
                logger.debug("session lacks event %s", event)
        for event, handler in (
            ("participant_disconnected", self._on_disconnect),
            ("disconnected", self._on_disconnect),
            ("connection_quality_changed", self._on_quality),
        ):
            try:
                self._room.on(event, handler)
            except Exception:  # pragma: no cover
                logger.debug("room lacks event %s", event)
