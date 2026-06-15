"""Probe sarvam-m (non-think mode) on the hosted Sarvam API for our
real voice use-case: TTFT latency, tool-calling correctness, Tenglish.

Read-only network probe. Prints hard numbers so we decide data-first,
exactly like the earlier provider probes. Does NOT change any config.
"""

from __future__ import annotations

import asyncio
import json
import time

import openai as _sdk

from src.config import settings

_BASE = "https://api.sarvam.ai/v1"
# sarvam-m is deprecated; hosted API now only serves these (both
# reasoning models). We probe the smaller/faster one.
_MODEL = "sarvam-30b"

# A realistic booking tool the agent actually uses.
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_appointment_slots",
            "description": "Return free/booked slots for a given date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "Date like 'tomorrow' or '2026-06-10'",
                    }
                },
                "required": ["date"],
            },
        },
    }
]

_SYS = (
    "You are a warm Telugu call-center agent. Reply in Tenglish (Telugu "
    "script + English business words). When the caller asks to book or "
    "check appointment availability for a day, you MUST call the "
    "check_appointment_slots tool. Keep replies to one short sentence."
)


async def _one(client, label, messages, *, with_tools, extra=None):
    kwargs = {
        "model": _MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 200,
        "stream": True,
    }
    if with_tools:
        kwargs["tools"] = _TOOLS
        kwargs["tool_choice"] = "auto"
    if extra:
        kwargs.update(extra)

    t0 = time.monotonic()
    ttft = None
    text = []
    reason = []
    tool_seen = None
    try:
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            d = chunk.choices[0].delta if chunk.choices else None
            if d is None:
                continue
            if getattr(d, "content", None):
                text.append(d.content)
            rc = getattr(d, "reasoning_content", None)
            if rc:
                reason.append(rc)
            tc = getattr(d, "tool_calls", None)
            if tc and tool_seen is None:
                tool_seen = tc[0].function.name if tc[0].function else "?"
        total = (time.monotonic() - t0) * 1000
        out = "".join(text)
        rout = "".join(reason)
        print(f"\n[{label}]")
        print(f"  TTFT={ttft:.0f}ms  total={total:.0f}ms")
        print(f"  tool_call={tool_seen}")
        print(f"  reasoning_tokens~={len(rout)//4} chars={len(rout)}")
        print(f"  text={out[:160]!r}")
    except Exception as e:
        print(f"\n[{label}] ERROR: {type(e).__name__}: {str(e)[:200]}")


async def main() -> None:
    if not settings.sarvam_api_key:
        print("SARVAM_API_KEY not set; cannot probe.")
        return
    client = _sdk.AsyncOpenAI(api_key=settings.sarvam_api_key, base_url=_BASE)

    # 1) Plain Tenglish reply (latency + language), no tools.
    await _one(
        client, "1. plain Tenglish (no tools)",
        [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": "Hello, meeru clinic nunchi calling aa?"},
        ],
        with_tools=False,
    )

    # 2) Should trigger a tool call (default mode).
    await _one(
        client, "2. tool-calling (default mode)",
        [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": "Repu morning appointment unda? check cheyandi."},
        ],
        with_tools=True,
    )

    # 3) Same, but try to force NON-THINK via reasoning_effort=low
    #    (Mistral-style). If the param is unsupported the API ignores it.
    await _one(
        client, "3. tool-calling (reasoning_effort=low)",
        [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": "Repu morning appointment unda? check cheyandi."},
        ],
        with_tools=True,
        extra={"reasoning_effort": "low"},
    )

    # 4) Warm-pool second call latency (closer to real steady-state).
    await _one(
        client, "4. warm plain Tenglish",
        [
            {"role": "system", "content": _SYS},
            {"role": "user", "content": "Naa booking confirm aindaa andi?"},
        ],
        with_tools=False,
    )

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
