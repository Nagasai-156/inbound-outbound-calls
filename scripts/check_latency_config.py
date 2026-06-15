"""Print the LIVE endpointing/turn-taking values from AgentConfig so we
know why measured endpointing (~720ms) is higher than intended."""

from __future__ import annotations

import asyncio

from src.config import settings
from src.pg import asyncpg_args

_FIELDS = [
    "minEndpointingDelay", "maxEndpointingDelay",
    "teluguMinEndpointingDelay", "minInterruptionDuration",
    "fillerLatencyThreshold", "llmModel",
]


async def main() -> None:
    import asyncpg

    dsn, extra = asyncpg_args(settings.supabase_db_url)
    conn = await asyncpg.connect(dsn, timeout=10, **extra)
    try:
        cols = ", ".join(f'"{f}"' for f in _FIELDS)
        row = await conn.fetchrow(
            f'SELECT {cols} FROM voiceai."AgentConfig" WHERE id=$1', "default"
        )
    finally:
        await conn.close()
    print("LIVE AgentConfig endpointing/turn values:")
    for f in _FIELDS:
        print(f"  {f} = {row[f]!r}")
    print("\nenv defaults:")
    print(f"  min_endpointing_delay = {settings.min_endpointing_delay}")
    print(f"  max_endpointing_delay = {settings.max_endpointing_delay}")
    print(f"  telugu_min_endpointing_delay = {settings.telugu_min_endpointing_delay}")


if __name__ == "__main__":
    asyncio.run(main())
