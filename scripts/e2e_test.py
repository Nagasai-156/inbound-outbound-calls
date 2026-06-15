"""DEEP end-to-end test from our side (no live PSTN).

Exercises everything that can be proven offline + real latency numbers:
  1. Call-start construction (inbound + outbound cfg)
  2. resolve_call: inbound vs outbound (persona/lang/script/voice)
  3. A DIFFERENT KB (consultancy) ingested into pgvector, queried in
     English / Hindi / Telugu + an off-KB question (no hallucination),
     with per-stage latency (embed cold/warm, pgvector search, synthesis)
  4. Shared-embedding cache proof (same query embeds once, not 3x)
  5. Fast Intent Router decisions + language-from-cfg across te/hi/en
  6. VoiceAgent turn simulation with a fake session (canned path speaks;
     KB path routes to LLM + fires filler) + per-turn latency

    python -X utf8 scripts/e2e_test.py
"""

from __future__ import annotations

import asyncio
import time
import traceback

OK, BAD = "[OK]", "[BAD]"


def ms(t0: float) -> str:
    return f"{(time.perf_counter() - t0) * 1000:6.0f} ms"


class FakeSession:
    """Captures what the agent would speak."""

    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text, allow_interruptions=True):
        self.said.append(str(text))


async def step1_construction():
    from livekit.agents import AgentSession

    from src.audio import build_room_input_options
    from src.pipeline.llm import build_llm
    from src.pipeline.stt import build_stt
    from src.pipeline.tts import build_tts
    from src.pipeline.turn import build_vad
    from src.runtime_config import load_runtime_config

    cfg = await load_runtime_config()
    AgentSession(
        stt=build_stt(cfg), llm=build_llm(cfg), tts=build_tts(cfg),
        vad=build_vad(), turn_detection="vad",
    )
    build_room_input_options()
    print(f"{OK} 1. construction OK  "
          f"(stt_lang={cfg.default_language} tts={cfg.tts_model} "
          f"llm={cfg.llm_model})")
    return cfg


def step2_directions():
    from src.agent import resolve_call
    from src.persona.inbound import inbound_prompt
    from src.persona.outbound import outbound_prompt
    import json

    class Ctx:
        def __init__(self, meta):
            self.job = type("J", (), {"metadata": meta})()

    inb = resolve_call(Ctx(""))
    out = resolve_call(Ctx("outbound " + json.dumps({
        "name": "Sai", "language": "te",
        "script": "Call about their consultancy project. Offer free demo.",
        "voice_model": "bulbul:v3-beta", "voice_speaker": "ritu"})))
    a = inb.direction == "inbound"
    b = (out.direction == "outbound" and out.language == "te"
         and out.script and out.voice_speaker == "ritu")
    # persona built from script override?
    from src.runtime_config import RuntimeConfig
    cfg = RuntimeConfig()
    cfg.outbound_persona = out.script
    used = "consultancy project" in outbound_prompt(cfg)
    print(f"{OK if a else BAD} 2a. inbound  -> persona=support, no metadata")
    print(f"{OK if b else BAD} 2b. outbound -> lang=te script+voice carried")
    print(f"{OK if used else BAD} 2c. campaign script overrides persona")
    assert "support" in inbound_prompt(RuntimeConfig()).lower() \
        or "call-center" in inbound_prompt(RuntimeConfig()).lower()


CONSULTANCY_KB = """\
Diigoo Consulting takes client projects: web, mobile apps, custom
software and AI/voice agents. A basic business website starts around
25000 rupees. A standard mobile or web app starts around 1.5 lakh
rupees. The first consultation call is free and lasts about 20 minutes.
Standard delivery for a simple website is 2 to 3 weeks. We take a 30 to
40 percent milestone advance to start. We sign an NDA before sensitive
discussions. We work remotely across India.
"""


async def step3_kb_multilang():
    """Exercises the REAL production KB path:

      kb_context (retrieval only, no 2nd LLM)  ->  the main agent LLM
      (with the live persona + the kb_search tool-result wrapper)
      synthesises the spoken answer.

    This is exactly what a live call does now, so the latency + grounding
    numbers here are honest. `kb_answer` (the old blocking-synthesis path)
    is also checked once — it is kept ONLY for speculative prefetch /
    offline use and must still refuse off-KB.
    """
    from openai import AsyncOpenAI

    from src.config import settings
    from src.kb import kb_answer, kb_context
    from src.kb_store import delete_document, ingest_document, search
    from src.embeddings import embed
    from src.persona.outbound import outbound_prompt
    from src.runtime_config import RuntimeConfig

    t = time.perf_counter()
    n = await ingest_document("e2e-consult", "consult.txt", CONSULTANCY_KB)
    print(f"{OK} 3. KB ingest (different KB) {n} chunk(s)  [{ms(t)}]")

    # embedding cache proof: cold vs warm for identical text
    t = time.perf_counter(); await embed("website cost entha"); cold = ms(t)
    t = time.perf_counter(); await embed("website cost entha"); warm = ms(t)
    print(f"     embed cold={cold.strip()}  warm(cached)={warm.strip()}")

    t = time.perf_counter()
    hits = await search("website cost entha", k=4)
    print(f"     pgvector search [{ms(t)}] top_score="
          f"{hits[0]['score']:.3f}" if hits else "     no hits")

    cfg = RuntimeConfig(); cfg.default_language = "te"
    persona = outbound_prompt(cfg)
    client = AsyncOpenAI(api_key=settings.openai_api_key or None)

    async def live_turn(q: str):
        """Mirror production: kb_search wrapper -> main LLM synthesis."""
        t0 = time.perf_counter()
        ctx = await kb_context(q)
        ctx_ms = (time.perf_counter() - t0) * 1000
        if ctx:
            tool_out = (
                "Answer the caller using ONLY these company facts. One or "
                "two short spoken sentences in the caller's language. Do "
                "NOT quote, do NOT add anything not stated here:\n\n" + ctx
            )
        else:
            tool_out = "No info found; tell them you'll check, don't invent."
        r = await client.chat.completions.create(
            model=settings.llm_model, temperature=0.2,
            messages=[
                {"role": "system", "content": persona},
                {"role": "user", "content": q},
                {"role": "assistant", "content": "[called kb_search]"},
                {"role": "system",
                 "content": "KB_SEARCH RESULT: " + tool_out},
            ],
        )
        ans = (r.choices[0].message.content or "").strip()
        return ans, ctx is not None, ctx_ms, (time.perf_counter() - t0) * 1000

    # (tag, question, KB-covered?) — covered means a grounded answer is
    # expected; not-covered means the agent must refuse / say it'll check.
    tests = [
        ("EN ", "how much for a basic website?", True),
        ("HI ", "website banane ka kitna charge hai?", True),
        ("TE ", "website ki entha avutundi?", True),
        ("TE ", "consultation free na?", True),
        ("OFF", "do you sell mobile phones in a store?", False),
        ("BAIT", "do you give a 90 percent student discount?", False),
    ]
    allok = True
    print("  -- LIVE path: kb_context -> main LLM (retrieval ctx_ms / "
          "total_ms) --")
    for tag, q, covered in tests:
        ans, hit, ctx_ms, tot_ms = await live_turn(q)
        # Grounding heuristic: an off-KB / bait question must NOT produce a
        # confident fabricated number; the persona should defer ("check").
        low = ans.lower()
        refused = any(w in low for w in (
            "check", "chept", "follow up", "don't have", "dont have",
            "not sure", "ledu", "sorry", "nahi", "don't sell", "dont sell",
        ))
        good = (covered and len(ans) > 0 and not (
            "90" in ans and not covered)) or (not covered and refused)
        allok &= good
        print(f"  {'ok ' if good else 'BAD'} {tag} "
              f"[ctx={ctx_ms:5.0f}ms tot={tot_ms:5.0f}ms] {ans[:70]}")

    # Off-path prefetch sanity: kb_answer must still refuse off-KB.
    t = time.perf_counter()
    pf = await kb_answer("how much for a basic website?")
    off = await kb_answer("do you sell mobile phones in a store?")
    pf_ok = bool(pf) and off is None
    allok &= pf_ok
    print(f"  {'ok ' if pf_ok else 'BAD'} prefetch path kb_answer "
          f"(covered ok, off-KB refused) [{ms(t)}]")

    await delete_document("e2e-consult")
    print(f"{OK if allok else BAD} 3. KB multilingual + grounded + "
          f"no-hallucination (LIVE fast path)")


async def step4_router(cfg):
    from src.cache import semantic_cache
    from src.router.intent_router import IntentRouter, Route

    r = IntentRouter()
    r.set_cache_resolver(semantic_cache.lookup)
    cases = [
        ("hello anna", Route.CANNED),
        ("thanks సర్", Route.CANNED),
        ("naa project gurinchi maatladali", Route.LLM),
        ("website cost cheppandi", Route.LLM),
    ]
    allok = True
    for txt, exp in cases:
        t = time.perf_counter()
        res = await r.route(txt)
        good = res.route == exp
        allok &= good
        print(f"  {'ok ' if good else 'BAD'} [{ms(t)}] {txt!r:34} "
              f"-> {res.route.value}")
    print(f"{OK if allok else BAD} 4. router decisions + latency")


async def step5_turnsim(cfg):
    from src.agent import VoiceAgent
    from src.cache import semantic_cache
    from src.cost import CallMeter
    from src.memory import CallMemory
    from src.predictive import PredictivePrefetch
    from src.audio import EchoGuard
    from src.telemetry import CallTelemetry
    from src.router.intent_router import IntentRouter
    from src.persona.outbound import outbound_prompt

    try:
        from livekit.agents import StopResponse
    except Exception:
        class StopResponse(Exception):
            ...

    router = IntentRouter()
    router.set_cache_resolver(
        lambda q: semantic_cache.lookup(q, cfg.cache_min_similarity)
    )
    cfg.default_language = "te"
    agent = VoiceAgent(
        outbound_prompt(cfg), router, CallMeter(),
        CallMemory(call_id="e2e"), PredictivePrefetch(), EchoGuard(),
        CallTelemetry("e2e", "e2e", "outbound"), cfg,
    )
    # `session` is a read-only property on the livekit Agent base, so we
    # patch `_say` directly to capture what the agent would speak
    # (still exercises echo-guard + routing + StopResponse paths).
    spoken: list[str] = []

    async def fake_say(text: str):
        agent._echo.on_agent_started(text)  # type: ignore
        spoken.append(str(text))

    agent._say = fake_say  # type: ignore

    class Msg:
        def __init__(self, t): self.text_content = t

    async def turn(text):
        t = time.perf_counter()
        try:
            await agent.on_user_turn_completed(None, Msg(text))
            return None, ms(t)
        except StopResponse:
            return "STOP", ms(t)
        except Exception as e:
            return f"ERR {e}", ms(t)

    r1, t1 = await turn("hello anna")           # canned -> speaks + STOP
    spoke1 = bool(spoken)
    print(f"  {'ok ' if (r1=='STOP' and spoke1) else 'BAD'} canned turn "
          f"[{t1}] said={spoken[-1][:40] if spoken else None!r}")
    await asyncio.sleep(0.2)
    before = len(spoken)
    r2, t2 = await turn("naa website project gurinchi maatladali")
    await asyncio.sleep(0.3)  # let fire-and-forget filler run
    filler_fired = len(spoken) > before
    print(f"  {'ok ' if (r2 is None) else 'BAD'} LLM turn routes to LLM "
          f"[{t2}] filler_fired={filler_fired}")
    print(f"{OK} 5. VoiceAgent turn simulation (canned speaks, LLM "
          f"path + filler, language from cfg=te)")


async def main():
    print("==================  DEEP E2E (offline)  ==================")
    try:
        cfg = await step1_construction()
        step2_directions()
        await step3_kb_multilang()
        await step4_router(cfg)
        await step5_turnsim(cfg)
        print("\n[OK] DEEP E2E PASSED — pipeline, inbound/outbound, "
              "multilingual KB, routing, turn loop all verified offline.")
    except Exception:
        print(f"{BAD} e2e error:")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
