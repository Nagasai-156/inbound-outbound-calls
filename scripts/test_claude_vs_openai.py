"""Live head-to-head: Claude Haiku 4.5 vs OpenAI gpt-4o-mini.

Tests are designed for voice-agent reality:
  1. Basic Telugu chat (Indic script + brevity instructions)
  2. Streaming TTFT (the latency budget caller perceives)
  3. Function calling with our actual tool spec (booking flow)

Reports hard numbers, picks winner per metric. No opinions until data lands.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import anthropic
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv("d:/diigoo/ai calls/.env", override=True)

ANTH_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OAI_KEY = os.environ.get("OPENAI_API_KEY", "")

SYSTEM_TE = (
    "You are a polite Telugu-Hindi-English voice agent for a clinic. "
    "Reply in TELUGU (native Telugu script + English code-mix). "
    "Keep replies 1-2 short sentences."
)
USER_TE = "హా మాట్లాడొచ్చండి. రేపు time ఏదైనా ఉందా?"

OAI_TOOLS = [{
    "type": "function",
    "function": {
        "name": "check_appointment_slots",
        "description": "Get free appointment slots for a date",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD or 'tomorrow'"},
            },
            "required": ["date"],
        },
    },
}]

ANTH_TOOLS = [{
    "name": "check_appointment_slots",
    "description": "Get free appointment slots for a date",
    "input_schema": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "YYYY-MM-DD or 'tomorrow'"},
        },
        "required": ["date"],
    },
}]


def has_telugu(text: str) -> bool:
    return any(0x0C00 <= ord(c) <= 0x0C7F for c in text)


async def test_claude(model: str = "claude-haiku-4-5") -> dict | None:
    print(f"=== Claude {model} ===")
    client = anthropic.AsyncAnthropic(api_key=ANTH_KEY)
    results: dict = {}

    # T1 basic chat
    try:
        t0 = time.monotonic()
        r = await asyncio.wait_for(client.messages.create(
            model=model, max_tokens=120, system=SYSTEM_TE,
            messages=[{"role": "user", "content": USER_TE}],
            temperature=0.4,
        ), timeout=20.0)
        elapsed = (time.monotonic() - t0) * 1000
        reply = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        print(f"  [T1] chat: {elapsed:.0f}ms, telugu_script={has_telugu(reply)}")
        print(f"       reply: {reply[:200]!r}")
        results["basic_ms"] = elapsed
        results["basic_telugu"] = has_telugu(reply)
    except Exception as e:
        print(f"  [T1] FAILED: {type(e).__name__}: {str(e)[:300]}")
        return None

    # T2 streaming TTFT
    try:
        t0 = time.monotonic()
        ttft = None
        deltas = 0
        async with client.messages.stream(
            model=model, max_tokens=120, system=SYSTEM_TE,
            messages=[{"role": "user", "content": USER_TE}],
            temperature=0.4,
        ) as stream:
            async for _ in stream.text_stream:
                if ttft is None:
                    ttft = (time.monotonic() - t0) * 1000
                deltas += 1
        total = (time.monotonic() - t0) * 1000
        print(f"  [T2] streaming: TTFT={ttft:.0f}ms total={total:.0f}ms deltas={deltas}")
        results["stream_ttft_ms"] = ttft
        results["stream_total_ms"] = total
    except Exception as e:
        print(f"  [T2] streaming FAILED: {type(e).__name__}: {str(e)[:300]}")

    # T3 function calling
    try:
        t0 = time.monotonic()
        r = await asyncio.wait_for(client.messages.create(
            model=model, max_tokens=120,
            system="Use the tool to check tomorrow's slots.",
            messages=[{"role": "user", "content": "Tomorrow ki slots cheppandi"}],
            tools=ANTH_TOOLS,
            temperature=0,
        ), timeout=20.0)
        elapsed = (time.monotonic() - t0) * 1000
        tool_use = next((b for b in r.content if getattr(b, "type", "") == "tool_use"), None)
        if tool_use:
            print(f"  [T3] tool_use: {elapsed:.0f}ms -> {tool_use.name}({json.dumps(tool_use.input)})")
            results["tools_ok"] = True
            results["tools_ms"] = elapsed
        else:
            text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
            print(f"  [T3] tool NOT fired. text={text[:200]!r}")
            results["tools_ok"] = False
    except Exception as e:
        print(f"  [T3] FAILED: {type(e).__name__}: {str(e)[:300]}")
        results["tools_ok"] = False

    return results


async def test_openai(model: str = "gpt-4o-mini") -> dict | None:
    print(f"\n=== OpenAI {model} ===")
    client = AsyncOpenAI(api_key=OAI_KEY)
    results: dict = {}

    try:
        t0 = time.monotonic()
        r = await asyncio.wait_for(client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_TE},
                {"role": "user", "content": USER_TE},
            ],
            temperature=0.4, max_tokens=120,
        ), timeout=20.0)
        elapsed = (time.monotonic() - t0) * 1000
        reply = r.choices[0].message.content or ""
        print(f"  [T1] chat: {elapsed:.0f}ms, telugu_script={has_telugu(reply)}")
        print(f"       reply: {reply[:200]!r}")
        results["basic_ms"] = elapsed
        results["basic_telugu"] = has_telugu(reply)
    except Exception as e:
        print(f"  [T1] FAILED: {type(e).__name__}: {str(e)[:300]}")
        return None

    try:
        t0 = time.monotonic()
        ttft = None
        chunks = 0
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_TE},
                {"role": "user", "content": USER_TE},
            ],
            temperature=0.4, max_tokens=120, stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if ttft is None:
                    ttft = (time.monotonic() - t0) * 1000
                chunks += 1
        total = (time.monotonic() - t0) * 1000
        print(f"  [T2] streaming: TTFT={ttft:.0f}ms total={total:.0f}ms chunks={chunks}")
        results["stream_ttft_ms"] = ttft
        results["stream_total_ms"] = total
    except Exception as e:
        print(f"  [T2] streaming FAILED: {type(e).__name__}: {str(e)[:300]}")

    try:
        t0 = time.monotonic()
        r = await asyncio.wait_for(client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Use the tool."},
                {"role": "user", "content": "Tomorrow ki slots cheppandi"},
            ],
            tools=OAI_TOOLS, tool_choice="auto",
            temperature=0, max_tokens=120,
        ), timeout=20.0)
        elapsed = (time.monotonic() - t0) * 1000
        tc = getattr(r.choices[0].message, "tool_calls", None) or []
        if tc:
            print(f"  [T3] tool_call: {elapsed:.0f}ms -> {tc[0].function.name}({tc[0].function.arguments})")
            results["tools_ok"] = True
            results["tools_ms"] = elapsed
        else:
            print(f"  [T3] tool NOT fired")
            results["tools_ok"] = False
    except Exception as e:
        print(f"  [T3] FAILED: {type(e).__name__}: {str(e)[:300]}")

    return results


async def main():
    print(f"Anthropic key configured: {bool(ANTH_KEY)}")
    print(f"OpenAI key configured:    {bool(OAI_KEY)}\n")
    claude = await test_claude("claude-haiku-4-5")
    oai = await test_openai("gpt-4o-mini")

    print("\n=== HEAD-TO-HEAD VERDICT ===")
    if claude and oai:
        def line(label, key, lower_better=True):
            c = claude.get(key)
            o = oai.get(key)
            if c is None or o is None:
                return f"{label:18s} n/a"
            winner = "Claude" if ((c < o) == lower_better) else "OpenAI"
            return f"{label:18s} Claude={c:.0f}ms  OpenAI={o:.0f}ms  -> {winner}"
        print(line("basic chat:",   "basic_ms"))
        print(line("streaming TTFT:", "stream_ttft_ms"))
        print(line("streaming total:", "stream_total_ms"))
        print(line("tools time:",     "tools_ms"))
        print(f"Telugu script:     Claude={claude.get('basic_telugu')}  OpenAI={oai.get('basic_telugu')}")
        print(f"Function calling:  Claude={claude.get('tools_ok')}  OpenAI={oai.get('tools_ok')}")


if __name__ == "__main__":
    asyncio.run(main())
