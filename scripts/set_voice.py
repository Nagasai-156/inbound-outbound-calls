"""Set the live TTS voice (model + speaker + pace) and bust the Redis
cache so the next call uses it. Default = Bulbul v2 'anushka' — Sarvam's
warmest/most-natural voice (the v3-beta 'ritu' sounded robotic).

    python -m scripts.set_voice                       # v2 anushka, pace 1.0
    python -m scripts.set_voice bulbul:v2 manisha 1.0
    python -m scripts.set_voice bulbul:v3-beta pooja 1.05
"""

from __future__ import annotations

import asyncio
import sys

from src.config import settings
from src.pg import asyncpg_args

MODEL = sys.argv[1] if len(sys.argv) > 1 else "bulbul:v2"
SPEAKER = sys.argv[2] if len(sys.argv) > 2 else "anushka"
PACE = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0


async def main() -> None:
    import asyncpg

    dsn, extra = asyncpg_args(settings.supabase_db_url)
    conn = await asyncpg.connect(dsn, timeout=10, **extra)
    try:
        await conn.execute(
            'UPDATE voiceai."AgentConfig" SET '
            '"ttsModel"=$2, "ttsSpeakerTe"=$3, "ttsSpeakerHi"=$3, '
            '"ttsSpeakerEn"=$3, "ttsPace"=$4, "updatedBy"=$1 WHERE id=$1',
            "default", MODEL, SPEAKER, PACE,
        )
        row = await conn.fetchrow(
            'SELECT "ttsModel","ttsSpeakerTe","ttsPace" '
            'FROM voiceai."AgentConfig" WHERE id=$1', "default",
        )
        print("voice set ->", dict(row))
    finally:
        await conn.close()

    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.delete("agentconfig:default")
        await r.aclose()
        print("redis cache cleared — next call uses the new voice")
    except Exception as e:
        print("redis clear failed:", e)


if __name__ == "__main__":
    asyncio.run(main())
