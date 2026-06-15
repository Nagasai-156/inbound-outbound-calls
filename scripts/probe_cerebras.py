"""Probe Cerebras inference for our voice use-case: TTFT, tool-calling,
Tenglish quality. Cerebras runs Llama on custom wafer-scale silicon
(~1800 tok/s on 8B) with an OpenAI-compatible API.

Setup (free tier):
    1. Sign up at https://cloud.cerebras.ai → create an API key.
    2. Set it:  setx CEREBRAS_API_KEY "csk-..."   (new shell after)
       or add CEREBRAS_API_KEY=csk-... to .env
    3. python -m scripts.probe_cerebras

Read-only probe. Does NOT change any config. Mirrors probe_sarvam so
the numbers are directly comparable (same tool, same prompts).
"""

from __future__ import annotations

import asyncio
import os
import time

import openai as _sdk

_BASE = "https://api.cerebras.ai/v1"
# Cerebras model ids actually available on this account (queried live).
# gpt-oss-120b = OpenAI open-weights 120B MoE (strong tool-calling);
# zai-glm-4.7 = Zhipu GLM 4.7 (strong multilingual). Both on wafer-scale.
_MODELS = ["gpt-oss-120b", "zai-glm-4.7"]

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
    "You are a warm Telugu call-center agent. Reply in Tenglish: Telugu "
    "in NATIVE Telugu script (తెలుగు లిపి) for connectors, English words "
    "for business terms (appointment, confirm, details). NEVER use Roman/"
    "transliterated Telugu like 'cheppandi' — write 'చెప్పండి'. When the "
    "caller asks to book or check availability for a day, you MUST call "
    "the check_appointment_slots tool. Keep replies to one short sentence."
)


async def _one(client, model, label, messages, *, with_tools):
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 400,
        "stream": True,
    }
    if with_tools:
        kwargs["tools"] = _TOOLS
        kwargs["tool_choice"] = "auto"

    t0 = time.monotonic()
    ttft = None
    text = []
    reason = []
    tool_seen = None
    finish = None
    try:
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            if not chunk.choices:
                continue
            ch0 = chunk.choices[0]
            if getattr(ch0, "finish_reason", None):
                finish = ch0.finish_reason
            d = ch0.delta
            if d is None:
                continue
            if getattr(d, "content", None):
                text.append(d.content)
            rc = getattr(d, "reasoning_content", None) or getattr(d, "reasoning", None)
            if rc:
                reason.append(rc)
            tc = getattr(d, "tool_calls", None)
            if tc and tool_seen is None:
                tool_seen = tc[0].function.name if tc[0].function else "?"
        total = (time.monotonic() - t0) * 1000
        rout = "".join(reason)
        print(f"\n[{model} | {label}]")
        print(f"  TTFT={ttft:.0f}ms  total={total:.0f}ms  finish={finish}")
        print(f"  tool_call={tool_seen}  reasoning_chars={len(rout)}")
        print(f"  text={''.join(text)[:200]!r}")
    except Exception as e:
        print(f"\n[{model} | {label}] ERROR: {type(e).__name__}: {str(e)[:200]}")


async def main() -> None:
    key = os.environ.get("CEREBRAS_API_KEY", "")
    if not key:
        # fall back to .env via settings if present
        try:
            from src.config import settings
            key = getattr(settings, "cerebras_api_key", "") or ""
        except Exception:
            pass
    if not key:
        print("CEREBRAS_API_KEY not set. Get a free key at "
              "https://cloud.cerebras.ai and set CEREBRAS_API_KEY.")
        return
    client = _sdk.AsyncOpenAI(api_key=key, base_url=_BASE)

    for model in _MODELS:
        await _one(
            client, model, "plain Tenglish",
            [
                {"role": "system", "content": _SYS},
                {"role": "user", "content": "Hello, meeru clinic nunchi calling aa?"},
            ],
            with_tools=False,
        )
        await _one(
            client, model, "tool-calling",
            [
                {"role": "system", "content": _SYS},
                {"role": "user", "content": "Repu morning appointment unda? check cheyandi."},
            ],
            with_tools=True,
        )
        # warm second call (steady-state latency)
        await _one(
            client, model, "warm plain",
            [
                {"role": "system", "content": _SYS},
                {"role": "user", "content": "Naa booking confirm aindaa andi?"},
            ],
            with_tools=False,
        )

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
