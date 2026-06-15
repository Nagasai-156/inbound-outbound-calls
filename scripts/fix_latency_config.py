"""Tighten the live endpointing/turn-taking values for snappier turns.

Measured endpointing was ~720ms avg (unmasked silence the caller hears).
Lowering the silence-wait thresholds shaves the tunable portion (the
rest is STT-final round-trip + turn-detector model, a floor we can't
remove with config). Values kept safe enough not to clip mid-sentence.
"""

from __future__ import annotations

import asyncio

from src.config import settings
from src.pg import asyncpg_args

# Aggressive — pushed harder for minimal dead-air. telugu 0.15 is near
# the floor before mid-pause clipping; max 0.38 caps worst-case wait.
_VALUES = {
    "minEndpointingDelay": 0.08,
    "maxEndpointingDelay": 0.38,
    "teluguMinEndpointingDelay": 0.15,
    "minInterruptionDuration": 0.18,
}


async def main() -> None:
    import asyncpg

    dsn, extra = asyncpg_args(settings.supabase_db_url)
    conn = await asyncpg.connect(dsn, timeout=10, **extra)
    try:
        sets = ", ".join(f'"{k}"=${i+2}' for i, k in enumerate(_VALUES))
        await conn.execute(
            f'UPDATE voiceai."AgentConfig" SET {sets}, '
            f'"updatedBy"=$1 WHERE id=$1',
            "default", *_VALUES.values(),
        )
        row = await conn.fetchrow(
            'SELECT "minEndpointingDelay","maxEndpointingDelay",'
            '"teluguMinEndpointingDelay","minInterruptionDuration" '
            'FROM voiceai."AgentConfig" WHERE id=$1', "default",
        )
        print("updated endpointing ->", dict(row))
    finally:
        await conn.close()

    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.delete("agentconfig:default")
        await r.aclose()
        print("redis cache cleared")
    except Exception as e:
        print("redis clear failed:", e)


if __name__ == "__main__":
    asyncio.run(main())
