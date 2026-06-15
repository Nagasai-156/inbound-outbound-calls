"""Voice quality A/B: 5 realistic call scenarios, side-by-side outputs.

For each scenario, both models get the SAME persona-style system prompt and
the SAME user turn. We capture:
  - latency (TTFT + total)
  - the actual Telugu reply (judge warmth/humanness yourself)
  - whether the reply violates anti-hallucination rules

Runs each scenario 2x to smooth network jitter.
"""
from __future__ import annotations

import asyncio
import os
import time
from statistics import mean

import anthropic
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv("d:/diigoo/ai calls/.env", override=True)

ANTH_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OAI_KEY = os.environ.get("OPENAI_API_KEY", "")

# Realistic voice-agent persona — matches what we use in src/persona/.
SYSTEM = (
    "You are a polite voice receptionist for Zannara Clinic in Hyderabad. "
    "Reply in TELUGU using తెలుగు లిపి with natural English code-mix. "
    "Keep replies 1-2 short conversational sentences — voice register, "
    "not chat. Use గారు/అండి honorifics. NEVER promise 'I'll check' or "
    "'we'll confirm immediately' unless you've actually performed the "
    "lookup. Be warm, human, never robotic."
)

# Five real-call scenarios callers actually trigger.
SCENARIOS = [
    ("greet_ack", "హా మాట్లాడొచ్చండి."),
    ("ask_slots", "రేపు మార్నింగ్ time ఏదైనా available ఉందా?"),
    ("ask_price", "మీరు ఏ ఏ services provide చేస్తారు, fee ఎంత?"),
    ("complaint", "నేను 2 sessions అయ్యాయి కానీ నాకు result రాలేదు. ఏమి చేయాలి?"),
    ("close", "ok ok thanks, talk to you later."),
]


def has_telugu(text: str) -> bool:
    return any(0x0C00 <= ord(c) <= 0x0C7F for c in text)


async def claude_reply(scenario_user: str) -> tuple[str, float, float]:
    """Return (text, ttft_ms, total_ms)."""
    client = anthropic.AsyncAnthropic(api_key=ANTH_KEY)
    t0 = time.monotonic()
    ttft = None
    chunks = []
    async with client.messages.stream(
        model="claude-haiku-4-5",
        max_tokens=120,
        system=SYSTEM,
        messages=[{"role": "user", "content": scenario_user}],
        temperature=0.4,
    ) as stream:
        async for delta in stream.text_stream:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            chunks.append(delta)
    total = (time.monotonic() - t0) * 1000
    return "".join(chunks), ttft or 0.0, total


async def openai_reply(scenario_user: str) -> tuple[str, float, float]:
    client = AsyncOpenAI(api_key=OAI_KEY)
    t0 = time.monotonic()
    ttft = None
    chunks: list[str] = []
    stream = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": scenario_user},
        ],
        temperature=0.4, max_tokens=120, stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            chunks.append(chunk.choices[0].delta.content)
    total = (time.monotonic() - t0) * 1000
    return "".join(chunks), ttft or 0.0, total


HALLUCINATION_FLAGS = [
    "ఇప్పుడే check",         # "checking now"
    "ఒక second",
    "ఒక్క నిమిషం",
    "immediately",
    "right away",
    "we'll check",
    "I'll check",
]


def flags(reply: str) -> list[str]:
    return [f for f in HALLUCINATION_FLAGS if f.lower() in reply.lower()]


async def run_scenario(name: str, user_msg: str) -> dict:
    print(f"\n{'='*78}\nSCENARIO: {name}")
    print(f"  USER: {user_msg!r}\n")
    # 2 runs each to smooth jitter
    claude_runs = []
    oai_runs = []
    for _ in range(2):
        claude_runs.append(await claude_reply(user_msg))
        oai_runs.append(await openai_reply(user_msg))

    # Use the second run (warm connection) for latency
    c_text, c_ttft, c_tot = claude_runs[1]
    o_text, o_ttft, o_tot = oai_runs[1]

    print(f"  CLAUDE  ({c_ttft:.0f}/{c_tot:.0f}ms, {len(c_text)} chars):")
    print(f"    {c_text}")
    cf = flags(c_text)
    if cf:
        print(f"    !! flags: {cf}")
    print(f"  OPENAI  ({o_ttft:.0f}/{o_tot:.0f}ms, {len(o_text)} chars):")
    print(f"    {o_text}")
    of = flags(o_text)
    if of:
        print(f"    !! flags: {of}")
    return {
        "name": name,
        "claude_ttft": c_ttft, "claude_total": c_tot, "claude_len": len(c_text),
        "claude_flags": cf, "claude_telugu": has_telugu(c_text),
        "openai_ttft": o_ttft, "openai_total": o_tot, "openai_len": len(o_text),
        "openai_flags": of, "openai_telugu": has_telugu(o_text),
    }


async def main():
    print(f"Anthropic key: {bool(ANTH_KEY)}  OpenAI key: {bool(OAI_KEY)}")
    rows = []
    for name, msg in SCENARIOS:
        rows.append(await run_scenario(name, msg))

    print(f"\n{'='*78}\n=== AGGREGATE (5 scenarios, 2nd run = warm connection) ===\n")
    avg_c_ttft = mean(r["claude_ttft"] for r in rows)
    avg_o_ttft = mean(r["openai_ttft"] for r in rows)
    avg_c_total = mean(r["claude_total"] for r in rows)
    avg_o_total = mean(r["openai_total"] for r in rows)
    avg_c_len = mean(r["claude_len"] for r in rows)
    avg_o_len = mean(r["openai_len"] for r in rows)
    c_flag_total = sum(len(r["claude_flags"]) for r in rows)
    o_flag_total = sum(len(r["openai_flags"]) for r in rows)
    c_te_count = sum(1 for r in rows if r["claude_telugu"])
    o_te_count = sum(1 for r in rows if r["openai_telugu"])

    print(f"avg TTFT:           Claude={avg_c_ttft:.0f}ms  OpenAI={avg_o_ttft:.0f}ms")
    print(f"avg total stream:   Claude={avg_c_total:.0f}ms  OpenAI={avg_o_total:.0f}ms")
    print(f"avg reply length:   Claude={avg_c_len:.0f} chars  OpenAI={avg_o_len:.0f} chars")
    print(f"Telugu script hits: Claude={c_te_count}/5  OpenAI={o_te_count}/5")
    print(f"Hallucination flag fires: Claude={c_flag_total}  OpenAI={o_flag_total}")


if __name__ == "__main__":
    asyncio.run(main())
