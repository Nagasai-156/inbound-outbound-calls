"""Probe Azure OpenAI (India region) before flipping live calls to it.

This is the moment of truth: is the India-hosted endpoint's TTFT actually
~250-400ms (vs ~1080ms from OpenAI US)? Also verifies function-calling
(appointment tools) and Tenglish quality. Tries several deployment names
since we don't know which one exists.

Reads AZURE_OPENAI_API_KEY from env. base_url is the /openai/v1 surface.
Run: $env:AZURE_OPENAI_API_KEY="..."; python -m scripts.test_azure_llm
"""

from __future__ import annotations

import asyncio
import os
import time

BASE = "https://diigoo-openai-india.openai.azure.com/openai/v1"
# Try the fast voice models first; o4-mini is a reasoning model (likely slow).
CANDIDATES = ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o", "o4-mini"]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "book_appointment",
        "description": "Book an appointment slot.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "time": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["date", "time"],
        },
    },
}]


async def probe(client, model: str) -> None:
    print(f"\n========== deployment: {model} ==========")
    # 1) streaming TTFT (the key metric) + Tenglish quality
    try:
        t0 = time.monotonic()
        first = None
        out = []
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a Telugu clinic agent. Reply in ONE short natural Tenglish sentence (Telugu script + English business words like 'appointment','slots'). No lists."},
                {"role": "user", "content": "Repu morning slots unnaya andi?"},
            ],
            max_tokens=80,
            temperature=0.4,
            stream=True,
        )
        async for ch in stream:
            d = ch.choices[0].delta.content if ch.choices else None
            if d:
                if first is None:
                    first = time.monotonic() - t0
                out.append(d)
        total = time.monotonic() - t0
        ttft = f"{first*1000:.0f}ms" if first else "n/a"
        print(f"  TTFT={ttft}  total={total*1000:.0f}ms")
        print(f"  reply: {''.join(out)[:220]}")
    except Exception as e:
        print(f"  STREAM FAILED: {type(e).__name__}: {str(e)[:220]}")
        return

    # 2) function-calling (must be a structured tool_call)
    try:
        r = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You book appointments. Call the tool when asked. Today is 2026-06-06."},
                {"role": "user", "content": "Book tomorrow 10 AM for Nagasai."},
            ],
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=120,
            temperature=0.2,
        )
        m = r.choices[0].message
        tc = getattr(m, "tool_calls", None)
        if tc:
            print(f"  TOOLS: OK -> {tc[0].function.name}({tc[0].function.arguments})")
        else:
            print(f"  TOOLS: NO tool_call. content: {(m.content or '')[:150]!r}")
    except Exception as e:
        print(f"  TOOLS FAILED: {type(e).__name__}: {str(e)[:220]}")


async def main() -> None:
    key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not key:
        print("AZURE_OPENAI_API_KEY not set in env"); return
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key, base_url=BASE)
    for model in CANDIDATES:
        await probe(client, model)
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
