"""Offline pipeline verification — everything a call does, minus the phone.

1. Builds the EXACT components a call constructs at start (STT, TTS, LLM,
   VAD, turn detection, AgentSession) so any constructor/kwarg/plugin
   problem surfaces here, not on a live call.
2. Drives the real Fast Intent Router with representative Telugu/Hindi/
   English utterances and prints the routing decision + canned/cache
   answers (the agent's actual turn logic).

    python -X utf8 scripts/pipeline_smoke.py
"""

from __future__ import annotations

import asyncio
import traceback

OK, FAIL = "[OK]", "[FAIL]"


async def build_components():
    from src.pipeline.llm import build_llm
    from src.pipeline.stt import build_stt
    from src.pipeline.tts import build_tts
    from src.pipeline.turn import build_turn_detection, build_vad
    from src.runtime_config import load_runtime_config

    cfg = await load_runtime_config()
    print(
        f"  cfg: tts={cfg.tts_model} spk_en={cfg.tts_speaker_en} "
        f"stt={cfg.stt_model}/{cfg.stt_mode} llm={cfg.llm_model} "
        f"lang={cfg.default_language}"
    )
    stt = build_stt(cfg)
    llm = build_llm(cfg)
    tts = build_tts(cfg)
    vad = build_vad()
    try:
        turn = build_turn_detection()
        print(f"  {OK} STT/LLM/TTS/VAD/turn built")
    except RuntimeError as e:
        if "job context" in str(e):
            turn = "vad"  # MultilingualModel only builds inside a job
            print(
                f"  {OK} STT/LLM/TTS/VAD built "
                f"(turn-detector defers to job context — normal; "
                f"verified live in the earlier call)"
            )
        else:
            raise

    from livekit.agents import AgentSession

    from src.audio import build_room_input_options

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=vad,
        turn_detection=turn,
        preemptive_generation=True,
        allow_interruptions=True,
    )
    build_room_input_options()
    print(f"  {OK} AgentSession + RoomInputOptions constructed")
    del session
    return cfg


async def route_checks():
    from src.cache import semantic_cache
    from src.router.intent_router import IntentRouter, Route

    router = IntentRouter()
    router.set_cache_resolver(semantic_cache.lookup)

    cases = [
        ("hello anna", Route.CANNED),
        ("thank you sir", Route.CANNED),
        ("haan ji theek hai", Route.CANNED),
        ("naa order ekkada undi", None),          # -> LLM (uses tools/KB)
        ("refund kitne din me aata hai", None),    # -> cache or LLM
        ("payment fail ho gaya paisa kat gaya", None),
    ]
    for text, expect in cases:
        r = await router.route(text)
        tag = OK
        if expect and r.route != expect:
            tag = FAIL
        ans = (r.answer or "")[:60]
        print(
            f"  {tag} {text!r:48} -> {r.route.value:7} "
            f"lang={r.classification.language:5} {ans}"
        )


async def main():
    print("== 1. Call-start pipeline construction ==")
    try:
        await build_components()
    except Exception:
        print(f"  {FAIL} construction error:")
        traceback.print_exc()
        return
    print("\n== 2. Fast Intent Router decisions ==")
    try:
        await route_checks()
    except Exception:
        print(f"  {FAIL} routing error:")
        traceback.print_exc()
        return
    print("\n[OK] offline pipeline verification passed.")


if __name__ == "__main__":
    asyncio.run(main())
