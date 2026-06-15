"""Vobiz <-> LiveKit Cloud SIP trunk setup / verification.

Your project already has trunks provisioned (LIVEKIT_SIP_TRUNK_ID and
LIVEKIT_OUTBOUND_TRUNK_ID in .env), so the normal path here is just to
*verify* them and ensure an inbound dispatch rule points at the agent.
Trunks are only created if the ids are absent.

    python -m src.telephony.sip_setup
"""

from __future__ import annotations

import asyncio
import logging

from livekit import api

from src.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("sip_setup")


async def _setup() -> None:
    if not settings.livekit_configured:
        raise SystemExit("LIVEKIT_URL/API_KEY/API_SECRET not set in .env")

    lk = api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        # ── Inbound trunk ──────────────────────────────────────────
        if settings.livekit_sip_trunk_id:
            inbound_id = settings.livekit_sip_trunk_id
            logger.info("using existing inbound trunk %s", inbound_id)
        else:
            inbound = await lk.sip.create_sip_inbound_trunk(
                api.CreateSIPInboundTrunkRequest(
                    trunk=api.SIPInboundTrunkInfo(
                        name="vobiz-inbound",
                        numbers=[settings.vobiz_inbound_did or "*"],
                    )
                )
            )
            inbound_id = inbound.sip_trunk_id
            logger.info("created inbound trunk %s", inbound_id)

        # ── Dispatch rule: each inbound call -> room + our agent ───
        # Idempotent: skip if a rule already targets this trunk.
        existing = []
        try:
            lst = await lk.sip.list_sip_dispatch_rule(
                api.ListSIPDispatchRuleRequest()
            )
            existing = list(getattr(lst, "items", []) or [])
        except Exception:
            logger.debug("could not list dispatch rules", exc_info=True)

        already = any(
            inbound_id in (getattr(r, "trunk_ids", []) or [])
            for r in existing
        )
        if already:
            logger.info("dispatch rule already exists for %s", inbound_id)
        else:
            rule = await lk.sip.create_sip_dispatch_rule(
                api.CreateSIPDispatchRuleRequest(
                    rule=api.SIPDispatchRule(
                        dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                            room_prefix="call-",
                        )
                    ),
                    trunk_ids=[inbound_id],
                    room_config=api.RoomConfiguration(
                        agents=[
                            api.RoomAgentDispatch(
                                agent_name=settings.agent_name
                            )
                        ]
                    ),
                )
            )
            logger.info(
                "created dispatch rule: %s", rule.sip_dispatch_rule_id
            )

        # ── Outbound trunk ─────────────────────────────────────────
        if settings.outbound_trunk_id:
            logger.info(
                "using existing outbound trunk %s",
                settings.outbound_trunk_id,
            )
            out_id = settings.outbound_trunk_id
        else:
            outbound = await lk.sip.create_sip_outbound_trunk(
                api.CreateSIPOutboundTrunkRequest(
                    trunk=api.SIPOutboundTrunkInfo(
                        name="vobiz-outbound",
                        address=settings.vobiz_sip_domain,
                        numbers=[settings.vobiz_inbound_did or ""],
                        auth_username=settings.vobiz_auth_id,
                        auth_password=settings.vobiz_sip_password,
                    )
                )
            )
            out_id = outbound.sip_trunk_id
            logger.info("created outbound trunk %s", out_id)

        print("\nReady.")
        print(f"INBOUND_TRUNK_ID={inbound_id}")
        print(f"LIVEKIT_OUTBOUND_TRUNK_ID={out_id}")
    finally:
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(_setup())
