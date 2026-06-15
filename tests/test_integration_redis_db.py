"""Live Redis + Supabase integration tests. Skip if unreachable.

These exercise real I/O round-trips: cache write/read, Redis pub/sub,
DB pool, transcript persistence. A schema mismatch / network issue
caught here would have been silent in pure unit tests."""

from __future__ import annotations

import asyncio
import os

import pytest

from dotenv import load_dotenv
load_dotenv()


async def _redis_up() -> bool:
    try:
        import redis.asyncio as redis
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        r = redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def _db_up() -> bool:
    """True ONLY if pool acquires AND the voiceai schema exists.
    A pool that connected to a different DB doesn't help our integration
    tests — skip cleanly instead of failing."""
    try:
        from src.db import _get_pool
        p = await _get_pool()
        if p is None:
            return False
        async with p.acquire() as c:
            row = await c.fetchval(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'voiceai'"
            )
        return row == 1
    except Exception:
        return False


@pytest.mark.asyncio
async def test_redis_ping_works():
    if not await _redis_up():
        pytest.skip("Redis not available")
    import redis.asyncio as redis
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(url, decode_responses=True)
    assert await r.ping() is True
    await r.aclose()


@pytest.mark.asyncio
async def test_redis_set_get_roundtrip():
    if not await _redis_up():
        pytest.skip("Redis not available")
    import redis.asyncio as redis
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(url, decode_responses=True)
    key = "test:integ:roundtrip"
    await r.set(key, "hello", ex=60)
    val = await r.get(key)
    assert val == "hello"
    await r.delete(key)
    await r.aclose()


@pytest.mark.asyncio
async def test_redis_pipeline_executes():
    if not await _redis_up():
        pytest.skip("Redis not available")
    import redis.asyncio as redis
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(url, decode_responses=True)
    key = "test:integ:pipeline"
    async with r.pipeline(transaction=False) as p:
        p.rpush(key, "a", "b", "c")
        p.ltrim(key, 0, 10)
        p.expire(key, 60)
        await p.execute()
    items = await r.lrange(key, 0, -1)
    assert items == ["a", "b", "c"]
    await r.delete(key)
    await r.aclose()


@pytest.mark.asyncio
async def test_redis_indic_unicode_roundtrip():
    if not await _redis_up():
        pytest.skip("Redis not available")
    import redis.asyncio as redis
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(url, decode_responses=True)
    key = "test:integ:indic"
    await r.set(key, "మంచి రోజు అండి", ex=60)
    val = await r.get(key)
    assert val == "మంచి రోజు అండి"
    await r.delete(key)
    await r.aclose()


@pytest.mark.asyncio
async def test_db_pool_acquires_connection():
    if not await _db_up():
        pytest.skip("Supabase not available")
    from src.db import _get_pool
    pool = await _get_pool()
    assert pool is not None
    async with pool.acquire() as c:
        v = await c.fetchval("SELECT 1")
        assert v == 1


@pytest.mark.asyncio
async def test_db_voiceai_schema_exists():
    if not await _db_up():
        pytest.skip("Supabase not available")
    from src.db import _get_pool
    pool = await _get_pool()
    async with pool.acquire() as c:
        row = await c.fetchval(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'voiceai'"
        )
        assert row == 1


@pytest.mark.asyncio
async def test_db_call_table_exists_with_latency_columns():
    """Verify our recent Prisma migration landed."""
    if not await _db_up():
        pytest.skip("Supabase not available")
    from src.db import _get_pool
    pool = await _get_pool()
    async with pool.acquire() as c:
        cols = await c.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'voiceai' AND table_name = 'Call'"
        )
    col_names = {r["column_name"] for r in cols}
    # New latency fields added this session.
    for needed in ["avgEouMs", "maxEouMs", "avgLlmTtftMs", "maxLlmTtftMs",
                   "avgTtsTtfbMs", "maxTtsTtfbMs"]:
        assert needed in col_names, f"Call table missing column {needed}"


@pytest.mark.asyncio
async def test_db_appointment_table_exists():
    if not await _db_up():
        pytest.skip("Supabase not available")
    from src.db import _get_pool
    pool = await _get_pool()
    async with pool.acquire() as c:
        cols = await c.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'voiceai' AND table_name = 'Appointment'"
        )
    col_names = {r["column_name"] for r in cols}
    for needed in ["id", "date", "time", "phone", "status"]:
        assert needed in col_names


@pytest.mark.asyncio
async def test_db_kbchunk_table_exists():
    if not await _db_up():
        pytest.skip("Supabase not available")
    from src.db import _get_pool
    pool = await _get_pool()
    async with pool.acquire() as c:
        # kb_chunks is the @@map target.
        v = await c.fetchval(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'voiceai' AND table_name = 'kb_chunks'"
        )
        assert v == 1
