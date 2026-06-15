"""Empirically validate parallel LLM racing: measure gpt-4o-mini TTFT
for SINGLE requests vs RACE-of-2 (fastest first token) over many trials.

Proves the feature clips the long tail (the 3-4s spikes) without a phone
call. Uses the real shared OpenAI client + a realistic-size prompt.

    python -m scripts.race_latency_test
"""

from __future__ import annotations

import asyncio
import statistics
import time

from src.persona.base import base_prompt
from src.runtime_config import RuntimeConfig

_TRIALS = 8
_RACE_N = 2


def _messages():
    cfg = RuntimeConfig()
    cfg.use_case_type = "appointment"
    sys = base_prompt(cfg)
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": "repu morning appointment book cheyali andi"},
    ]


async def _ttft(client, messages) -> float:
    t0 = time.monotonic()
    stream = await client.chat.completions.create(
        model="gpt-4o-mini", messages=messages, temperature=0.4,
        max_tokens=80, stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            ttft = (time.monotonic() - t0) * 1000
            await stream.close()
            return ttft
    return (time.monotonic() - t0) * 1000


async def _race_ttft(client, messages, n) -> float:
    """TTFT of the fastest of n parallel requests."""
    t0 = time.monotonic()
    tasks = [asyncio.ensure_future(_ttft(client, messages)) for _ in range(n)]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for p in pending:
        p.cancel()
    # The first task to finish already measured its own TTFT; but we want
    # wall-clock to first token across the race:
    return (time.monotonic() - t0) * 1000


def _report(label, xs):
    xs = sorted(xs)
    print(f"\n{label} (n={len(xs)}):")
    print(f"  min={xs[0]:.0f}  median={statistics.median(xs):.0f}  "
          f"avg={statistics.mean(xs):.0f}  max={xs[-1]:.0f}  ms")


async def main() -> None:
    import openai
    from src.config import settings

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    messages = _messages()

    # warm the pool once (don't count it)
    try:
        await _ttft(client, messages)
    except Exception as e:
        print("warmup failed:", e)

    singles, races = [], []
    for i in range(_TRIALS):
        try:
            singles.append(await _ttft(client, messages))
        except Exception as e:
            print(f"single trial {i} err: {e}")
        try:
            races.append(await _race_ttft(client, messages, _RACE_N))
        except Exception as e:
            print(f"race trial {i} err: {e}")
        print(f"  trial {i+1}/{_TRIALS}: single={singles[-1]:.0f}ms  "
              f"race2={races[-1]:.0f}ms")

    _report("SINGLE request TTFT", singles)
    _report(f"RACE-of-{_RACE_N} TTFT", races)
    if singles and races:
        print(f"\nTail (max) cut: {max(singles):.0f}ms -> {max(races):.0f}ms")
        print(f"Avg change: {statistics.mean(singles):.0f}ms -> "
              f"{statistics.mean(races):.0f}ms")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
