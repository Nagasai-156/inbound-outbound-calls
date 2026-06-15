"""Print the LIVE AgentConfig.llmModel + the runtime-config Redis cache,
so we can confirm exactly which model the next call will use."""

from __future__ import annotations

import asyncio

from src.config import settings
from src.pg import asyncpg_args


async def main() -> None:
    import asyncpg

    dsn, extra = asyncpg_args(settings.supabase_db_url)
    conn = await asyncpg.connect(dsn, timeout=10, **extra)
    try:
        v = await conn.fetchval(
            'SELECT "llmModel" FROM voiceai."AgentConfig" WHERE id=$1',
            "default",
        )
    finally:
        await conn.close()
    print("LIVE AgentConfig.llmModel =", repr(v))

    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, socket_connect_timeout=3)
        cached = await r.get("agentconfig:default")
        await r.aclose()
        print("redis agentconfig:default cache =", repr(cached))
    except Exception as e:
        print("redis check failed:", e)

    print("env DEFAULT_LLM_MODEL/LLM_MODEL ->", repr(settings.llm_model))


if __name__ == "__main__":
    asyncio.run(main())
