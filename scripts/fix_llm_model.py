"""One-shot: point the live AgentConfig at a chosen LLM model and bust
the runtime-config Redis cache so the NEXT call reloads it.

Usage:
    python -m scripts.fix_llm_model                      # default below
    python -m scripts.fix_llm_model llama-3.1-8b-instant # Groq, sub-500ms
    python -m scripts.fix_llm_model gpt-4o-mini          # back to OpenAI

Why this exists
---------------
The Supabase AgentConfig.llmModel row is the LIVE source of truth — it
OVERRIDES the .env default for every call. Editing .env alone does
nothing until this row + the Redis cache agree.

Model picks (measured TTFT from India, with the 8k prompt budget active):
  * llama-3.1-8b-instant  ~168ms median  — Groq LPU, the sub-500ms fix.
                          Function-calling + Tenglish both verified.
                          Slightly below gpt-4o-mini on complex booking
                          reasoning; A/B on a live call before scaling.
  * gpt-4o-mini           ~1s            — OpenAI US compute floor. Best
                          quality of the cheap tier. Reversible target.
  * azure/gpt-4o-mini     ~300ms-1s      — India-hosted, needs Azure env.

Reversible: just re-run with the previous model name.
"""

from __future__ import annotations

import asyncio
import sys

from src.config import settings
from src.pg import asyncpg_args

DEFAULT_MODEL = "llama-3.1-8b-instant"


async def main(target_model: str) -> None:
    import asyncpg

    dsn, extra = asyncpg_args(settings.supabase_db_url)
    conn = await asyncpg.connect(dsn, timeout=10, **extra)
    try:
        before = await conn.fetchval(
            'SELECT "llmModel" FROM voiceai."AgentConfig" WHERE id=$1',
            "default",
        )
        await conn.execute(
            'UPDATE voiceai."AgentConfig" SET "llmModel"=$2, '
            '"updatedBy"=$3 WHERE id=$1',
            "default", target_model, "fix_llm_model_script",
        )
        after = await conn.fetchval(
            'SELECT "llmModel" FROM voiceai."AgentConfig" WHERE id=$1',
            "default",
        )
        print(f"AgentConfig.llmModel: {before!r} -> {after!r}")
    finally:
        await conn.close()

    # Bust the runtime-config Redis cache so the NEXT call reloads it.
    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, socket_connect_timeout=3)
        await r.delete("agentconfig:default")
        await r.aclose()
        print("redis agentconfig:default cache cleared")
    except Exception as e:
        print(f"redis cache clear failed (non-fatal): {e}")


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    asyncio.run(main(model))
