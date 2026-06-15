"""Tighten the live prompt-growth knobs so late-turn LLM prefill stays
fast on long calls (the 10-turn call's prompt had grown, pushing TTFT
up). Safe: persona + recent turns are always kept; only the oldest raw
history is trimmed sooner. No behaviour change, just a smaller per-turn
prompt -> lower prefill latency.

    python -m scripts.tune_prompt_perf
"""

from __future__ import annotations

import asyncio

from src.config import settings
from src.pg import asyncpg_args

_VALUES = {
    # Fewer raw history turns carried per prompt (CallMemory still keeps
    # the durable gist — name/intent/summary — so nothing important lost).
    "memoryMaxTurns": 4,
}


async def main() -> None:
    import asyncpg

    dsn, extra = asyncpg_args(settings.supabase_db_url)
    conn = await asyncpg.connect(dsn, timeout=10, **extra)
    try:
        sets = ", ".join(f'"{k}"=${i+2}' for i, k in enumerate(_VALUES))
        await conn.execute(
            f'UPDATE voiceai."AgentConfig" SET {sets}, "updatedBy"=$1 '
            f'WHERE id=$1',
            "default", *_VALUES.values(),
        )
        row = await conn.fetchrow(
            'SELECT "memoryMaxTurns" '
            'FROM voiceai."AgentConfig" WHERE id=$1', "default",
        )
        print("tuned ->", dict(row))
    finally:
        await conn.close()

    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.delete("agentconfig:default")
        await r.aclose()
        print("redis cache cleared — next call uses the tighter prompt")
    except Exception as e:
        print("redis clear failed:", e)


if __name__ == "__main__":
    asyncio.run(main())
