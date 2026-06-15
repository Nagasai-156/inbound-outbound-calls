"""Outbound dialer.

Places a call through the Vobiz outbound trunk and attaches our agent so
it talks the moment the callee answers. The job is tagged
`metadata="outbound"` so the agent picks the SALES persona (see
resolve_direction in src/agent.py).

CLI:
    python -m src.telephony.outbound +9198XXXXXXXX

Programmatic:
    await place_call("+9198XXXXXXXX")
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import uuid

from livekit import api

from src.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("outbound")


class OutboundCallError(Exception):
    """SIP-side or LiveKit-side failure placing an outbound call.

    Carries a short, caller-facing reason ("invalid number", "trunk
    rejected", "no answer", …) extracted from the LiveKit/Vobiz error
    so the control API can surface a clean JSON error instead of a raw
    stack trace, and the campaign runner can record a useful failure
    reason on the contact row.
    """

    def __init__(self, reason: str, room: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.room = room


def _sip_reason(exc: Exception) -> str:
    """Extract a short human reason from a LiveKit/SIP exception.

    LiveKit twirp errors carry the status as `code` + a `msg`. Falls
    back to `str(exc)` truncated. Used for both the control API JSON
    error and the campaign-run failure column.
    """
    for attr in ("msg", "message", "details"):
        v = getattr(exc, attr, None)
        if isinstance(v, str) and v:
            return v[:200]
    return str(exc)[:200] or exc.__class__.__name__


async def place_call(
    phone_number: str,
    trunk_id: str | None = None,
    *,
    name: str = "",
    language: str = "",
    script: str = "",
    voice_model: str = "",
    voice_speaker: str = "",
    use_case: str = "",
    business_description: str = "",
    style_examples: str = "",
    kb_vector_store_id: str = "",
    caller_id: str = "",
    room_name: str | None = None,
) -> str:
    """Dial `phone_number`, dispatch the agent, return the room name.

    Per-campaign context (`script`, `voice_model`, `voice_speaker`,
    `language`, `name`) is passed in the job metadata after the
    "outbound" tag, so each campaign's calls communicate to their own
    goal/voice — independently of the global persona and of other
    campaigns running at the same time.
    """
    if not settings.livekit_configured:
        raise SystemExit("LIVEKIT_URL/API_KEY/API_SECRET not set in .env")
    trunk_id = trunk_id or settings.outbound_trunk_id
    if not trunk_id:
        raise SystemExit("OUTBOUND_TRUNK_ID not set (run sip_setup first)")

    room_name = room_name or f"out-{uuid.uuid4().hex[:10]}"
    meta = "outbound " + json.dumps(
        {
            "name": name,
            "language": language,
            "script": script,
            "voice_model": voice_model,
            "voice_speaker": voice_speaker,
            "use_case": use_case,
            "business_description": business_description,
            "style_examples": style_examples,
            "kb_vector_store_id": kb_vector_store_id,
            "phone": phone_number,   # so a call booking has a contact #
        }
    )
    lk = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    agent_dispatched = False
    try:
        # Dispatch the agent into the room first (tagged outbound so it
        # uses the sales persona and greets on answer).
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=settings.agent_name,
                room=room_name,
                metadata=meta,
            )
        )
        agent_dispatched = True
        # Then ring the callee and bridge them into the same room.
        try:
            # Caller-ID (from-number) override: the dashboard can pick the
            # number shown to the callee. Only set `sip_number` when a
            # caller_id was provided — empty = trunk's default number
            # (unchanged behaviour). The trunk must be authorized to
            # present this number or the provider may reject/replace it.
            sip_req_kwargs = dict(
                sip_trunk_id=trunk_id,
                sip_call_to=phone_number,
                room_name=room_name,
                participant_identity=f"callee-{phone_number}",
                wait_until_answered=True,
            )
            if caller_id:
                sip_req_kwargs["sip_number"] = caller_id
            await lk.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(**sip_req_kwargs)
            )
        except Exception as sip_err:
            reason = _sip_reason(sip_err)
            logger.warning(
                "outbound SIP failed to=%s trunk=%s reason=%s",
                phone_number, trunk_id, reason,
            )
            # The agent was dispatched into an empty room — clean it up
            # so we don't accumulate orphan rooms that the watchdog can't
            # see and the dashboard shows as "live" forever.
            if agent_dispatched:
                try:
                    await lk.room.delete_room(
                        api.DeleteRoomRequest(room=room_name)
                    )
                except Exception:
                    logger.debug(
                        "cleanup delete_room failed for %s",
                        room_name, exc_info=True,
                    )
            raise OutboundCallError(reason, room=room_name) from sip_err
        logger.info("outbound call connected: %s -> room %s",
                    phone_number, room_name)
        return room_name
    finally:
        await lk.aclose()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m src.telephony.outbound <e164-number>")
    asyncio.run(place_call(sys.argv[1]))
