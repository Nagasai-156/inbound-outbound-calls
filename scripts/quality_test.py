"""Offline quality test — drive the LIVE LLM (whatever AgentConfig points
at, currently cerebras/gpt-oss-120b) with the REAL persona prompt + REAL
booking tool schemas through a scripted Telugu booking conversation.

No phone call needed. Prints each turn's response, tool calls, latency,
and a native-Telugu-script check so we can judge quality directly.

    python -m scripts.quality_test
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import openai as _sdk

from src.config import settings
from src.persona.outbound import outbound_prompt
from src.runtime_config import load_runtime_config

# ─── Real booking tool schemas (match src/tools.py named tools) ──────
_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_appointment_slots",
            "description": "Return free/booked slots for a date. Call before booking.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string"}},
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book an appointment after explicit caller confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "name": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["date", "time", "name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "my_appointment",
            "description": "List the caller's existing appointments by phone.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# Fake tool results so the conversation can progress deterministically.
_TOOL_RESULTS = {
    "check_appointment_slots": json.dumps({
        "date": "tomorrow",
        "free": ["09:00", "09:30", "10:00", "10:30", "11:00", "15:00", "16:00"],
        "booked": ["12:00", "14:00"],
    }),
    "book_appointment": json.dumps({
        "status": "success", "date": "tomorrow", "time": "10:00",
        "name": "Ravi", "id": "APT-7781",
    }),
    "my_appointment": json.dumps({"appointments": []}),
}

# Scripted caller turns (realistic Telugu/Tenglish booking flow).
_CALLER_TURNS = [
    "ఆ చెప్పండి, ఎవరు మాట్లాడుతోంది?",
    "నాకు repu oka appointment kావాli andi",
    "morning ten gantalaki vీలవుతుందా?",
    "నా peru Ravi andi",
    "ఆ, confirm cheయండి",
    "thanks andi, inkేమీ వద్దు",
]


def _pick_client_and_model(model: str):
    """Mirror build_llm routing to hit the live provider directly."""
    mlc = (model or "").lower()
    if mlc.startswith("cerebras/"):
        key = settings.cerebras_api_key or os.environ.get("CEREBRAS_API_KEY", "")
        return _sdk.AsyncOpenAI(api_key=key, base_url="https://api.cerebras.ai/v1"), model.split("/", 1)[1]
    if mlc.startswith("llama-") or mlc.startswith("groq"):
        return _sdk.AsyncOpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1"), model
    # default OpenAI
    return _sdk.AsyncOpenAI(api_key=settings.openai_api_key), model


def _has_telugu(s: str) -> bool:
    return any("\u0c00" <= ch <= "\u0c7f" for ch in s)


def _has_roman_letters(s: str) -> bool:
    return any("a" <= ch.lower() <= "z" for ch in s)


async def main() -> None:
    import sys
    cfg = await load_runtime_config()
    # Optional CLI override so we can A/B the same persona across models.
    override = sys.argv[1] if len(sys.argv) > 1 else None
    model_id = override or cfg.llm_model
    print(f"=== model: {model_id} | lang={cfg.default_language} ===\n")
    system = outbound_prompt(cfg)
    client, model = _pick_client_and_model(model_id)

    messages = [{"role": "system", "content": system}]

    for caller in _CALLER_TURNS:
        messages.append({"role": "user", "content": caller})
        print(f"🧑 CALLER: {caller}")

        # Inner loop: resolve any tool calls in the same turn.
        for _ in range(4):
            t0 = time.monotonic()
            try:
                resp = await client.chat.completions.create(
                    model=model, messages=messages, tools=_TOOLS,
                    tool_choice="auto", temperature=0.3, max_tokens=500,
                )
            except Exception as e:
                print(f"   ⚠️ LLM error: {type(e).__name__}: {str(e)[:160]}\n")
                return
            ttft = (time.monotonic() - t0) * 1000
            msg = resp.choices[0].message
            tcs = msg.tool_calls or []
            if tcs:
                # Record the assistant tool call, then feed a fake result.
                messages.append({
                    "role": "assistant", "content": msg.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name,
                                      "arguments": tc.function.arguments}}
                        for tc in tcs
                    ],
                })
                for tc in tcs:
                    name = tc.function.name
                    print(f"   🔧 TOOL CALL: {name}({tc.function.arguments}) [{ttft:.0f}ms]")
                    messages.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": _TOOL_RESULTS.get(name, "{}"),
                    })
                continue  # let the model speak after the tool result
            # Final spoken reply.
            text = msg.content or ""
            messages.append({"role": "assistant", "content": text})
            flags = []
            if cfg.default_language == "te":
                if not _has_telugu(text):
                    flags.append("❌ NO Telugu script")
                if not _has_roman_letters(text):
                    flags.append("⚠️ no English words (not code-mixed)")
            tag = ("  " + " ".join(flags)) if flags else "  ✓"
            print(f"🤖 AGENT [{ttft:.0f}ms]:{tag}\n   {text}\n")
            break

    await client.close()
    print("=== done ===")


if __name__ == "__main__":
    asyncio.run(main())
