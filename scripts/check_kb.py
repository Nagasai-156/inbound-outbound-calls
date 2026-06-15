"""Show the live business context + KB config so we know what the agent
legitimately knows vs what it would have to invent."""

from __future__ import annotations

import asyncio

from src.config import settings
from src.pg import asyncpg_args


async def main() -> None:
    import asyncpg

    dsn, extra = asyncpg_args(settings.supabase_db_url)
    conn = await asyncpg.connect(dsn, timeout=10, **extra)
    try:
        row = await conn.fetchrow(
            'SELECT "businessDescription","kbVectorStoreId","useCaseType",'
            '"enabledTools" FROM voiceai."AgentConfig" WHERE id=$1', "default",
        )
    finally:
        await conn.close()
    bd = row["businessDescription"] or ""
    print("=== businessDescription ===")
    print(bd if bd else "(EMPTY)")
    print(f"\nlen={len(bd)} chars")
    print(f"kbVectorStoreId = {row['kbVectorStoreId']!r}  (empty = no KB)")
    print(f"useCaseType = {row['useCaseType']!r}")
    print(f"enabledTools = {row['enabledTools']!r}")


if __name__ == "__main__":
    asyncio.run(main())
