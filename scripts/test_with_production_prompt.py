"""Honest re-test: same models, but with the REAL production prompt.

The previous test used a minimal 100-token system prompt. Production uses:
  - base_prompt(cfg): CORE_CONSTRAINTS + _hours_facts + _BUILTIN_STYLE_EXAMPLES
  - outbound_prompt wrapper: + LANGUAGE-MIRROR + persona body + biz context
  - Per-turn injections we DON'T add here (snapshot/lang/gender/emotion)
    — those are minor relative to the base ~5000 tokens.

This gives a fair quality comparison: with all the prompt-engineering
work we've done, what do these models ACTUALLY sound like?
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from statistics import mean

import anthropic
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv("d:/diigoo/ai calls/.env", override=True)

# Import the real production prompt builders
from src.runtime_config import RuntimeConfig, load_runtime_config
from src.persona.outbound import outbound_prompt
from src import db

ANTH_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1"


async def build_production_system_prompt() -> str:
    """Load the LIVE AgentConfig from Supabase and build the actual
    outbound prompt our agent uses on real calls."""
    cfg = await load_runtime_config()
    # Refresh the appt grid so _hours_facts() has the real working hours.
    db._refresh_appt_grid(cfg)
    # Mock caller info that the agent normally has
    cfg.caller_gender = "male"
    prompt = outbound_prompt(cfg)
    return prompt, cfg


SCENARIOS = [
    ("greet_ack",   "హా మాట్లాడొచ్చండి."),
    ("ask_slots",   "రేపు మార్నింగ్ time ఏదైనా available ఉందా?"),
    ("ask_price",   "మీరు ఏ ఏ services provide చేస్తారు, fee ఎంత?"),
    ("complaint",   "నేను 2 sessions అయ్యాయి కానీ result రాలేదు."),
    ("close",       "ok ok thanks, talk to you later."),
]


def has_telugu(t: str) -> bool:
    return any(0x0C00 <= ord(c) <= 0x0C7F for c in t)


async def claude_chat(system: str, user: str) -> dict:
    client = anthropic.AsyncAnthropic(api_key=ANTH_KEY)
    t0 = time.monotonic()
    ttft = None
    chunks: list[str] = []
    async with client.messages.stream(
        model="claude-haiku-4-5", max_tokens=160, system=system,
        messages=[{"role": "user", "content": user}], temperature=0.4,
    ) as stream:
        async for d in stream.text_stream:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            chunks.append(d)
    return {"text": "".join(chunks), "ttft_ms": ttft or 0, "total_ms": (time.monotonic() - t0) * 1000}


async def openai_chat(system: str, user: str) -> dict:
    client = AsyncOpenAI(api_key=OAI_KEY)
    t0 = time.monotonic()
    ttft = None
    chunks: list[str] = []
    stream = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4, max_tokens=160, stream=True,
    )
    async for c in stream:
        if c.choices and c.choices[0].delta.content:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            chunks.append(c.choices[0].delta.content)
    return {"text": "".join(chunks), "ttft_ms": ttft or 0, "total_ms": (time.monotonic() - t0) * 1000}


async def groq_chat(system: str, user: str, model: str) -> dict:
    client = AsyncOpenAI(base_url=GROQ_BASE, api_key=GROQ_KEY)
    t0 = time.monotonic()
    ttft = None
    chunks: list[str] = []
    stream = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.4, max_tokens=160, stream=True,
    )
    async for c in stream:
        if c.choices and c.choices[0].delta.content:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            chunks.append(c.choices[0].delta.content)
    return {"text": "".join(chunks), "ttft_ms": ttft or 0, "total_ms": (time.monotonic() - t0) * 1000}


async def main():
    print("Building REAL production system prompt from live AgentConfig...")
    system, cfg = await build_production_system_prompt()
    print(f"\nSystem prompt size: {len(system)} chars (~{len(system)//4} tokens estimate)")
    print(f"Active config: default_lang={cfg.default_language}  "
          f"use_case={cfg.use_case_type}  auto_mirror={cfg.auto_mirror_language}")
    print(f"Business desc length: {len(cfg.business_description)} chars")
    print(f"Style examples length: {len(cfg.style_examples)} chars (0 = built-in)")
    print(f"Persona override length: {len(cfg.outbound_persona)} chars (0 = built-in)")
    print(f"\n--- First 800 chars of the actual prompt ---")
    print(system[:800])
    print("...")
    print(f"\n--- Last 400 chars ---")
    print(system[-400:])
    print()

    candidates = [
        ("claude-haiku-4-5",  lambda u: claude_chat(system, u)),
        ("gpt-4o-mini",        lambda u: openai_chat(system, u)),
        ("groq/llama-4-scout-17b", lambda u: groq_chat(system, u, "meta-llama/llama-4-scout-17b-16e-instruct")),
        ("groq/llama-3.3-70b", lambda u: groq_chat(system, u, "llama-3.3-70b-versatile")),
    ]

    # Warm-up each (discarded)
    print("Warming up connections...")
    for name, fn in candidates:
        try:
            await fn("test")
        except Exception:
            pass
    print("Warmed.\n")

    for scenario_name, user_msg in SCENARIOS:
        print(f"\n{'='*78}\nSCENARIO: {scenario_name}\n  USER: {user_msg!r}\n")
        for model_name, fn in candidates:
            try:
                r = await fn(user_msg)
                print(f"  [{model_name:30s}] {r['ttft_ms']:>5.0f}ms TTFT  {r['total_ms']:>5.0f}ms total")
                print(f"      {r['text']}")
            except Exception as e:
                print(f"  [{model_name:30s}] FAILED: {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    asyncio.run(main())
