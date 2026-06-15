"""Groq models comparison vs gpt-4o-mini baseline.

Tests:
  T1. Basic Telugu chat + TTFT
  T2. Function calling reliability (CRITICAL — Claude failed this)
  T3. Multi-turn conversation flow

Targets the same 3 voice scenarios as the Claude test so numbers are
directly comparable.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from statistics import mean, stdev

from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv("d:/diigoo/ai calls/.env", override=True)

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
OAI_KEY = os.environ.get("OPENAI_API_KEY", "")
GROQ_BASE = "https://api.groq.com/openai/v1"

SYSTEM = (
    "You are a polite voice receptionist for Zannara Clinic in Hyderabad. "
    "Reply in TELUGU using తెలుగు లిపి with natural English code-mix. "
    "Keep replies 1-2 short conversational sentences — voice register. "
    "Use గారు/అండి honorifics. NO emojis. Be warm, human."
)

TOOLS = [
    {"type": "function", "function": {
        "name": "check_slots", "description": "Get free slots for a date",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string"}}, "required": ["date"]}}},
    {"type": "function", "function": {
        "name": "book_slot", "description": "Book an appointment",
        "parameters": {"type": "object", "properties": {
            "date": {"type": "string"}, "time": {"type": "string"},
            "name": {"type": "string"}}, "required": ["date", "time"]}}},
]


def has_telugu(t: str) -> bool:
    return any(0x0C00 <= ord(c) <= 0x0C7F for c in t)


async def call_model(base_url: str | None, api_key: str, model: str,
                     user_msgs: list[dict], tools=None,
                     max_tokens: int = 120, temperature: float = 0.4) -> dict:
    client = AsyncOpenAI(base_url=base_url, api_key=api_key) if base_url \
        else AsyncOpenAI(api_key=api_key)
    t0 = time.monotonic()
    ttft = None
    text_parts: list[str] = []
    raw_tool_args: dict[int, dict] = {}
    in_tok = out_tok = 0
    messages = [{"role": "system", "content": SYSTEM}] + user_msgs
    kwargs: dict = dict(model=model, messages=messages,
                        temperature=temperature, max_tokens=max_tokens,
                        stream=True,
                        stream_options={"include_usage": True})
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    try:
        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.usage:
                in_tok = chunk.usage.prompt_tokens
                out_tok = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            d = chunk.choices[0].delta
            if getattr(d, "content", None):
                if ttft is None:
                    ttft = (time.monotonic() - t0) * 1000
                text_parts.append(d.content)
            if getattr(d, "tool_calls", None):
                for tc in d.tool_calls:
                    idx = tc.index
                    slot = raw_tool_args.setdefault(idx, {"name": "", "args": ""})
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["args"] += tc.function.arguments
        total = (time.monotonic() - t0) * 1000
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:300]}"}

    tool_calls = []
    for slot in raw_tool_args.values():
        try:
            args = json.loads(slot["args"]) if slot["args"] else {}
        except json.JSONDecodeError:
            args = {"_raw": slot["args"]}
        tool_calls.append({"name": slot["name"], "input": args})
    return {
        "text": "".join(text_parts), "ttft_ms": ttft or 0.0,
        "total_ms": total, "in_tok": in_tok, "out_tok": out_tok,
        "tool_calls": tool_calls,
    }


CANDIDATES = [
    ("groq/llama-3.3-70b-versatile", GROQ_BASE, GROQ_KEY, "llama-3.3-70b-versatile"),
    ("groq/llama-3.1-8b-instant",   GROQ_BASE, GROQ_KEY, "llama-3.1-8b-instant"),
    ("groq/llama-4-scout-17b",      GROQ_BASE, GROQ_KEY, "meta-llama/llama-4-scout-17b-16e-instruct"),
    ("openai/gpt-4o-mini",          None,      OAI_KEY,  "gpt-4o-mini"),
]


async def run_t1(label, base, key, model):
    print(f"\n  [T1 chat]  {label}")
    runs = []
    msg = [{"role": "user", "content": "హా మాట్లాడొచ్చండి, రేపు time ఏదైనా ఉందా?"}]
    # warm-up
    await call_model(base, key, model, msg)
    # 3 timed runs
    for _ in range(3):
        r = await call_model(base, key, model, msg)
        if "error" in r:
            print(f"    FAILED: {r['error']}")
            return None
        runs.append(r)
    avg_ttft = mean(r["ttft_ms"] for r in runs)
    last = runs[-1]
    print(f"    avg TTFT={avg_ttft:.0f}ms  total={last['total_ms']:.0f}ms  "
          f"telugu={has_telugu(last['text'])}  in={last['in_tok']} out={last['out_tok']}")
    print(f"    text: {last['text'][:200]}")
    return {"ttft": avg_ttft, "telugu": has_telugu(last['text']),
            "in": last['in_tok'], "out": last['out_tok']}


async def run_t2(label, base, key, model):
    print(f"\n  [T2 tools] {label}")
    prompts = [
        "Tomorrow ki slots cheppandi",
        "Book my slot for tomorrow 10:30 AM, name Ravi",
    ]
    results = []
    for p in prompts:
        r = await call_model(base, key, model, [{"role": "user", "content": p}], tools=TOOLS)
        if "error" in r:
            print(f"    PROMPT {p!r} FAILED: {r['error']}")
            results.append({"fired": False, "complete": False, "error": r['error']})
            continue
        if not r["tool_calls"]:
            print(f"    PROMPT {p!r}: NO tool — text={r['text'][:120]!r}")
            results.append({"fired": False, "complete": False})
        else:
            tc = r["tool_calls"][0]
            args = tc.get("input", {})
            if tc["name"] == "book_slot":
                complete = "date" in args and "time" in args and "name" in args
            else:
                complete = "date" in args
            print(f"    PROMPT {p!r}: {tc['name']}({args}) complete={complete}")
            results.append({"fired": True, "complete": complete})
    fire_count = sum(1 for r in results if r["fired"])
    complete_count = sum(1 for r in results if r["complete"])
    return {"fired": fire_count, "complete": complete_count, "total": len(prompts)}


async def main():
    print("Models under test:")
    for label, _, _, model in CANDIDATES:
        print(f"  - {label}  ({model})")

    summary = {}
    for label, base, key, model in CANDIDATES:
        print(f"\n{'='*78}\n{label}\n{'='*78}")
        t1 = await run_t1(label, base, key, model)
        t2 = await run_t2(label, base, key, model)
        summary[label] = {"t1": t1, "t2": t2}

    print(f"\n{'='*78}\nSUMMARY (vs OpenAI gpt-4o-mini baseline)\n{'='*78}")
    print(f"{'Model':40s} {'TTFT':>8s} {'Tools fire':>11s} {'Complete':>10s} {'Telugu':>8s}")
    for label, data in summary.items():
        t1, t2 = data["t1"], data["t2"]
        if t1 is None:
            print(f"{label:40s}  --- FAILED ---")
            continue
        print(f"{label:40s} {t1['ttft']:>7.0f}ms "
              f"{t2['fired']:>4d}/{t2['total']:<5d}  "
              f"{t2['complete']:>4d}/{t2['total']:<5d}  "
              f"{str(t1['telugu']):>8s}")


if __name__ == "__main__":
    asyncio.run(main())
