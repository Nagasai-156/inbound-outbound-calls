"""COMPREHENSIVE Claude vs OpenAI comparison — every dimension that
matters for production voice agents.

Tests:
  A. Latency variance (5 runs each, cold + warm)
  B. Multi-turn conversation flow (3 turns deep)
  C. Function calling with multiple tools (slot check + book)
  D. Three language registers (Telugu, Hindi, Hinglish)
  E. Edge cases (empty, very long, code-switching mid-sentence)
  F. Cost per turn (from actual token counts)
  G. Output cleanliness (emoji rate, markdown leakage)

Each section reports concrete numbers + side-by-side outputs. No opinions.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from statistics import mean, median, stdev

import anthropic
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv("d:/diigoo/ai calls/.env", override=True)

ANTH_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OAI_KEY = os.environ.get("OPENAI_API_KEY", "")

# Models under test
CLAUDE_MODEL = "claude-haiku-4-5"
OPENAI_MODEL = "gpt-4o-mini"

# Costs ($/Mtok)
COST = {
    CLAUDE_MODEL: {"in": 1.00, "out": 5.00},
    OPENAI_MODEL: {"in": 0.15, "out": 0.60},
}

SYSTEM = (
    "You are a polite voice receptionist for Zannara Clinic in Hyderabad. "
    "Reply in TELUGU using తెలుగు లిపి with natural English code-mix. "
    "Keep replies 1-2 short conversational sentences — voice register, "
    "not chat. Use గారు/అండి honorifics. NEVER promise 'I'll check' or "
    "'we'll confirm immediately' unless you've actually performed the "
    "lookup. NO emojis (TTS reads them literally). Be warm, human."
)

EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U00002702-\U000027B0]"
)


def has_telugu(t: str) -> bool:
    return any(0x0C00 <= ord(c) <= 0x0C7F for c in t)


def has_devanagari(t: str) -> bool:
    return any(0x0900 <= ord(c) <= 0x097F for c in t)


def emoji_count(t: str) -> int:
    return len(EMOJI_RE.findall(t))


def md_leaks(t: str) -> bool:
    """Markdown that would sound weird in TTS."""
    return bool(re.search(r"\*\*|`{1,3}|^\s*[-*]\s+|\[.+?\]\(.+?\)", t, re.M))


# ─── Anthropic helpers ─────────────────────────────────────────
async def claude_stream(user_msgs: list[dict], temperature: float = 0.4,
                        max_tokens: int = 120, tools: list | None = None
                        ) -> dict:
    """Run a Claude streaming call. Returns dict with text, ttft_ms,
    total_ms, in_tok, out_tok, tool_calls."""
    client = anthropic.AsyncAnthropic(api_key=ANTH_KEY)
    t0 = time.monotonic()
    ttft = None
    text_chunks: list[str] = []
    tool_calls: list[dict] = []
    kwargs: dict = dict(
        model=CLAUDE_MODEL, max_tokens=max_tokens, system=SYSTEM,
        messages=user_msgs, temperature=temperature,
    )
    if tools is not None:
        kwargs["tools"] = tools
    last_msg = None
    async with client.messages.stream(**kwargs) as stream:
        async for delta in stream.text_stream:
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            text_chunks.append(delta)
        last_msg = await stream.get_final_message()
    total = (time.monotonic() - t0) * 1000
    text = "".join(text_chunks)
    in_tok = last_msg.usage.input_tokens if last_msg else 0
    out_tok = last_msg.usage.output_tokens if last_msg else 0
    if last_msg:
        for block in last_msg.content:
            if getattr(block, "type", "") == "tool_use":
                tool_calls.append({"name": block.name, "input": block.input})
    return {
        "text": text, "ttft_ms": ttft or total, "total_ms": total,
        "in_tok": in_tok, "out_tok": out_tok, "tool_calls": tool_calls,
    }


# ─── OpenAI helpers ────────────────────────────────────────────
async def openai_stream(user_msgs: list[dict], temperature: float = 0.4,
                        max_tokens: int = 120, tools: list | None = None
                        ) -> dict:
    client = AsyncOpenAI(api_key=OAI_KEY)
    t0 = time.monotonic()
    ttft = None
    text_chunks: list[str] = []
    tool_calls: list[dict] = []
    messages = [{"role": "system", "content": SYSTEM}] + user_msgs
    kwargs: dict = dict(
        model=OPENAI_MODEL, messages=messages, temperature=temperature,
        max_tokens=max_tokens, stream=True,
        stream_options={"include_usage": True},
    )
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    in_tok = out_tok = 0
    raw_tool_args: dict[int, dict] = {}
    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        # usage chunk arrives at end with include_usage
        if chunk.usage:
            in_tok = chunk.usage.prompt_tokens
            out_tok = chunk.usage.completion_tokens
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            if ttft is None:
                ttft = (time.monotonic() - t0) * 1000
            text_chunks.append(delta.content)
        if getattr(delta, "tool_calls", None):
            for tc in delta.tool_calls:
                idx = tc.index
                slot = raw_tool_args.setdefault(idx, {"name": "", "args": ""})
                if tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function.arguments:
                    slot["args"] += tc.function.arguments
    total = (time.monotonic() - t0) * 1000
    text = "".join(text_chunks)
    for slot in raw_tool_args.values():
        try:
            args = json.loads(slot["args"]) if slot["args"] else {}
        except json.JSONDecodeError:
            args = {"_raw": slot["args"]}
        tool_calls.append({"name": slot["name"], "input": args})
    return {
        "text": text, "ttft_ms": ttft or total, "total_ms": total,
        "in_tok": in_tok, "out_tok": out_tok, "tool_calls": tool_calls,
    }


def cost_usd(model: str, in_tok: int, out_tok: int) -> float:
    c = COST[model]
    return (in_tok / 1e6) * c["in"] + (out_tok / 1e6) * c["out"]


# ─── A. Latency variance (5 runs) ──────────────────────────────
async def section_latency():
    print(f"\n{'='*80}\nA. LATENCY VARIANCE — 5 runs each, warm connection\n{'='*80}")
    msg = [{"role": "user", "content": "హా మాట్లాడొచ్చండి, రేపు time ఏదైనా ఉందా?"}]
    # Cold first run discarded
    await claude_stream(msg); await openai_stream(msg)
    c_ttft: list[float] = []
    c_total: list[float] = []
    o_ttft: list[float] = []
    o_total: list[float] = []
    for i in range(5):
        c = await claude_stream(msg)
        o = await openai_stream(msg)
        c_ttft.append(c["ttft_ms"]); c_total.append(c["total_ms"])
        o_ttft.append(o["ttft_ms"]); o_total.append(o["total_ms"])
        print(f"  run {i+1}: Claude TTFT={c['ttft_ms']:.0f}ms total={c['total_ms']:.0f}ms  "
              f"OpenAI TTFT={o['ttft_ms']:.0f}ms total={o['total_ms']:.0f}ms")
    print()
    def stats(label, arr):
        return (f"  {label:18s} avg={mean(arr):.0f}ms  "
                f"median={median(arr):.0f}ms  stdev={stdev(arr):.0f}ms  "
                f"min={min(arr):.0f}ms  max={max(arr):.0f}ms")
    print(stats("Claude TTFT", c_ttft))
    print(stats("OpenAI TTFT", o_ttft))
    print(stats("Claude total", c_total))
    print(stats("OpenAI total", o_total))


# ─── B. Multi-turn conversation ────────────────────────────────
async def section_multiturn():
    print(f"\n{'='*80}\nB. MULTI-TURN CONVERSATION FLOW (3 turns)\n{'='*80}")
    turns_user = [
        "హా మాట్లాడొచ్చండి",
        "రేపు మార్నింగ్ time ఉందా?",
        "10 AM ok ana?",
    ]
    for name, runner in (("Claude", claude_stream), ("OpenAI", openai_stream)):
        print(f"\n--- {name} ---")
        msgs: list[dict] = []
        for ut in turns_user:
            msgs.append({"role": "user", "content": ut})
            r = await runner(msgs)
            print(f"  USER:  {ut}")
            print(f"  BOT:   {r['text']}  ({r['total_ms']:.0f}ms)")
            msgs.append({"role": "assistant", "content": r["text"]})


# ─── C. Function calling (multi-tool) ──────────────────────────
TOOLS_OAI = [
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
TOOLS_ANTH = [
    {"name": "check_slots", "description": "Get free slots for a date",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string"}}, "required": ["date"]}},
    {"name": "book_slot", "description": "Book an appointment",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string"}, "time": {"type": "string"},
         "name": {"type": "string"}}, "required": ["date", "time"]}},
]


async def section_tools():
    print(f"\n{'='*80}\nC. FUNCTION CALLING — multi-tool, multiple prompts\n{'='*80}")
    prompts = [
        "Tomorrow ki slots cheppandi",
        "Book my slot for tomorrow 10:30 AM, name Ravi",
        "Hello, how are you today?",  # should NOT fire a tool
    ]
    for prompt in prompts:
        print(f"\n  PROMPT: {prompt!r}")
        c = await claude_stream([{"role": "user", "content": prompt}], tools=TOOLS_ANTH)
        o = await openai_stream([{"role": "user", "content": prompt}], tools=TOOLS_OAI)
        print(f"    Claude ({c['total_ms']:.0f}ms): tools={c['tool_calls']} text={c['text'][:80]!r}")
        print(f"    OpenAI ({o['total_ms']:.0f}ms): tools={o['tool_calls']} text={o['text'][:80]!r}")


# ─── D. Three language registers ───────────────────────────────
async def section_languages():
    print(f"\n{'='*80}\nD. LANGUAGE REGISTERS — Telugu, Hindi, English\n{'='*80}")
    prompts = [
        ("Telugu", "నేను రేపు రాలేను, ఎప్పుడు free ఉంటారు?"),
        ("Hindi",  "मैं कल नहीं आ सकता, कब free होंगे?"),
        ("English","I can't come tomorrow, when are you free?"),
    ]
    for lang, msg in prompts:
        print(f"\n  [{lang}] {msg}")
        c = await claude_stream([{"role": "user", "content": msg}])
        o = await openai_stream([{"role": "user", "content": msg}])
        c_te = has_telugu(c['text']); c_hi = has_devanagari(c['text'])
        o_te = has_telugu(o['text']); o_hi = has_devanagari(o['text'])
        print(f"    Claude (te={c_te} hi={c_hi}): {c['text'][:150]}")
        print(f"    OpenAI (te={o_te} hi={o_hi}): {o['text'][:150]}")


# ─── E. Output cleanliness ─────────────────────────────────────
async def section_cleanliness():
    print(f"\n{'='*80}\nE. OUTPUT CLEANLINESS — emoji/markdown leakage\n{'='*80}")
    prompts = [
        "Hi, can you help me?",
        "What services do you offer? List them.",
        "Thanks so much! Bye!",
    ]
    c_emoji = c_md = 0
    o_emoji = o_md = 0
    for p in prompts:
        c = await claude_stream([{"role": "user", "content": p}])
        o = await openai_stream([{"role": "user", "content": p}])
        ce, oe = emoji_count(c['text']), emoji_count(o['text'])
        cm, om = md_leaks(c['text']), md_leaks(o['text'])
        c_emoji += ce; o_emoji += oe
        if cm: c_md += 1
        if om: o_md += 1
        print(f"\n  PROMPT: {p!r}")
        print(f"    Claude (emoji={ce} md={cm}): {c['text'][:120]}")
        print(f"    OpenAI (emoji={oe} md={om}): {o['text'][:120]}")
    print(f"\n  TOTAL: Claude emoji={c_emoji} md_replies={c_md}  "
          f"OpenAI emoji={o_emoji} md_replies={o_md}")


# ─── F. Cost per turn ──────────────────────────────────────────
async def section_cost():
    print(f"\n{'='*80}\nF. COST PER TURN — real token counts on realistic prompt\n{'='*80}")
    msg = [{"role": "user", "content": "Hi, can I book an appointment for tomorrow morning?"}]
    c_costs = []; o_costs = []
    c_in = c_out = o_in = o_out = 0
    for _ in range(3):
        c = await claude_stream(msg)
        o = await openai_stream(msg)
        c_costs.append(cost_usd(CLAUDE_MODEL, c["in_tok"], c["out_tok"]))
        o_costs.append(cost_usd(OPENAI_MODEL, o["in_tok"], o["out_tok"]))
        c_in += c["in_tok"]; c_out += c["out_tok"]
        o_in += o["in_tok"]; o_out += o["out_tok"]
    print(f"  Claude:  in={c_in//3} out={c_out//3} tok/turn  avg_cost=${mean(c_costs)*1000:.4f}/1k_turns")
    print(f"  OpenAI:  in={o_in//3} out={o_out//3} tok/turn  avg_cost=${mean(o_costs)*1000:.4f}/1k_turns")
    print(f"\n  100 calls/day × 5 turns each = 500 turns/day:")
    print(f"    Claude:  ${mean(c_costs)*500*30:.2f}/month")
    print(f"    OpenAI:  ${mean(o_costs)*500*30:.2f}/month")


async def main():
    print(f"Anthropic={bool(ANTH_KEY)}  OpenAI={bool(OAI_KEY)}")
    print(f"Testing: {CLAUDE_MODEL}  vs  {OPENAI_MODEL}")
    await section_latency()
    await section_multiturn()
    await section_tools()
    await section_languages()
    await section_cleanliness()
    await section_cost()
    print(f"\n{'='*80}\nDONE\n{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())
