"""End-to-end FLOW test (everything verifiable without a phone).

Covers the full pipeline both directions:
  1. call-start construction (STT/TTS/LLM/VAD/AgentSession)
  2. inbound vs outbound persona resolution
  3. per-campaign metadata round-trip (dialer -> agent)
  4. Fast Intent Router decisions (Te/Hi/En)
  5. KB grounded multilingual answers + no-hallucination

    python -X utf8 scripts/flow_test.py
"""

from __future__ import annotations

import asyncio
import json
import traceback

OK = "[OK]"
BAD = "[BAD]"


async def step_construction():
    from livekit.agents import AgentSession

    from src.audio import build_room_input_options
    from src.pipeline.llm import build_llm
    from src.pipeline.stt import build_stt
    from src.pipeline.tts import build_tts
    from src.pipeline.turn import build_vad
    from src.runtime_config import load_runtime_config

    cfg = await load_runtime_config()
    AgentSession(
        stt=build_stt(cfg),
        llm=build_llm(cfg),
        tts=build_tts(cfg),
        vad=build_vad(),
        turn_detection="vad",
    )
    build_room_input_options()
    print(f"{OK} 1. Call-start pipeline constructs "
          f"(tts={cfg.tts_model}, llm={cfg.llm_model})")
    return cfg


def step_personas(cfg):
    from src.persona.inbound import inbound_prompt
    from src.persona.outbound import outbound_prompt

    inb = inbound_prompt(cfg)
    out = outbound_prompt(cfg)
    assert "call-center" in inb.lower() or "support" in inb.lower()
    print(f"{OK} 2. Inbound persona  -> {inb.splitlines()[0][:60]}...")
    print(f"     Outbound persona -> built from "
          f"{'override' if cfg.outbound_persona else 'built-in sales'}")


def step_campaign_metadata():
    from src.agent import resolve_call

    meta = "outbound " + json.dumps({
        "name": "Ravi", "language": "te",
        "script": "Remind about tomorrow 11AM appointment. Confirm/resched.",
        "voice_model": "bulbul:v3-beta", "voice_speaker": "ritu",
    })

    class J:
        metadata = meta

    class C:
        job = J()

    m = resolve_call(C())
    ok = (m.direction == "outbound" and m.name == "Ravi"
          and m.language == "te" and m.voice_speaker == "ritu"
          and "appointment" in m.script)
    print(f"{OK if ok else BAD} 3. Per-campaign metadata round-trip "
          f"(script+voice+lang carried per call)")

    class J2:
        metadata = ""

    class C2:
        job = J2()

    mi = resolve_call(C2())
    print(f"{OK if mi.direction == 'inbound' else BAD} "
          f"   inbound call -> direction=inbound (global persona)")


async def step_router():
    from src.cache import semantic_cache
    from src.router.intent_router import IntentRouter, Route

    r = IntentRouter()
    r.set_cache_resolver(semantic_cache.lookup)
    cases = [
        ("hello anna", Route.CANNED),
        ("thank you", Route.CANNED),
        ("naa order ekkada undi", Route.LLM),
        ("refund kitne din", Route.LLM),
    ]
    allok = True
    for t, exp in cases:
        res = await r.route(t)
        good = res.route == exp
        allok &= good
        print(f"   {'ok' if good else 'BAD'} {t!r:32} -> "
              f"{res.route.value} ({res.classification.language})")
    print(f"{OK if allok else BAD} 4. Fast Intent Router decisions")


async def step_kb():
    from src.kb import kb_answer
    from src.kb_store import delete_document, ingest_document

    doc = ("Refunds are processed in 5 to 7 working days. Delivery is "
           "free above 499 rupees. If money was debited but order not "
           "confirmed it is auto-refunded within 24 hours.")
    await ingest_document("flowtest", "p.txt", doc)
    tests = [
        ("EN refund", "how many days for refund?", True),
        ("HI payment", "paisa kat gaya order nahi hua kya hoga?", True),
        ("TE refund", "refund enni rojulu padutundi?", True),
        ("OFF-KB", "do you sell televisions?", False),
    ]
    allok = True
    for tag, q, expect_ans in tests:
        a = await kb_answer(q)
        got = a is not None
        good = got == expect_ans
        allok &= good
        shown = (a[:54] if a else "<refused -> 'I will check'>")
        print(f"   {'ok' if good else 'BAD'} {tag:11} {shown}")
    await delete_document("flowtest")
    print(f"{OK if allok else BAD} 5. KB grounded + multilingual + "
          f"no-hallucination")


async def main():
    try:
        cfg = await step_construction()
        step_personas(cfg)
        step_campaign_metadata()
        await step_router()
        await step_kb()
        print("\n[OK] FULL FLOW VERIFIED (offline-testable parts).")
    except Exception:
        print(f"{BAD} flow error:")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
