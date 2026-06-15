"""Knowledge base on Supabase **pgvector** (not OpenAI file_search).

Why pgvector: retrieval is a local Postgres query (no extra internet
round-trip like OpenAI file_search), the data lives in YOUR Supabase,
and it pairs with the strict grounding rules so the agent answers only
from your documents.

Pipeline:
  ingest:  text -> chunk -> OpenAI embedding -> voiceai.kb_chunks
  query :  question -> embedding -> cosine top-k (pgvector <=>) -> chunks

Everything is schema-qualified to `voiceai` and degrades safely.
"""

from __future__ import annotations

import logging

from src.config import settings
from src.pg import asyncpg_args

logger = logging.getLogger("kb_store")

EMBED_DIM = 1536  # text-embedding-3-small
_TABLE = 'voiceai.kb_chunks'

_pool = None


async def _pool_get():
    global _pool
    if _pool is None and settings.supabase_db_url:
        import asyncpg

        dsn, extra = asyncpg_args(settings.supabase_db_url)
        _pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=4, command_timeout=20, **extra
        )
    return _pool


async def ensure_schema() -> None:
    """Create the pgvector extension + chunk table once (idempotent)."""
    pool = await _pool_get()
    if pool is None:
        return
    async with pool.acquire() as c:
        await c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await c.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
              id        bigserial PRIMARY KEY,
              doc_id    text NOT NULL,
              kb_id     text NOT NULL DEFAULT '',
              filename  text NOT NULL DEFAULT '',
              lang      text NOT NULL DEFAULT '',
              content   text NOT NULL,
              embedding vector({EMBED_DIM}) NOT NULL,
              created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        await c.execute(
            "ALTER TABLE voiceai.kb_chunks ADD COLUMN IF NOT EXISTS "
            "kb_id text NOT NULL DEFAULT ''"
        )
        await c.execute(
            f"CREATE INDEX IF NOT EXISTS kb_chunks_doc_idx "
            f"ON {_TABLE} (doc_id)"
        )
        await c.execute(
            f"CREATE INDEX IF NOT EXISTS kb_chunks_kb_idx "
            f"ON {_TABLE} (kb_id)"
        )
        # HNSW cosine index: correct recall even with few rows (ivfflat
        # silently returns nothing until it has training data — bad for
        # a KB that starts empty). Drop any old ivfflat index first.
        await c.execute("DROP INDEX IF EXISTS voiceai.kb_chunks_vec_idx")
        await c.execute(
            f"CREATE INDEX IF NOT EXISTS kb_chunks_hnsw_idx ON {_TABLE} "
            f"USING hnsw (embedding vector_cosine_ops)"
        )


def _chunk(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    text = " ".join((text or "").split())
    if len(text) <= size:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i : i + size])
        i += size - overlap
    return out


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


async def ingest_document(
    doc_id: str, filename: str, text: str, lang: str = "", kb_id: str = ""
) -> int:
    """Chunk + embed + store a document. Returns chunk count."""
    pool = await _pool_get()
    if pool is None:
        raise RuntimeError("Supabase not configured")
    await ensure_schema()
    chunks = _chunk(text)
    if not chunks:
        return 0
    # Token-aware batching (shared helper) — the old fixed 64-chunk
    # batch could silently exceed the OpenAI embeddings token limit.
    from src.embeddings import embed_batch

    vectors = await embed_batch(chunks)
    if len(vectors) != len(chunks):
        raise RuntimeError(
            f"embedding count {len(vectors)} != chunks {len(chunks)}"
        )
    async with pool.acquire() as c:
        # Atomic re-ingest: DELETE old chunks + INSERT new ones in ONE
        # transaction. The old non-transactional version deleted the
        # existing chunks first, so a failing INSERT left the document
        # with NO chunks — silently vanishing from the KB on a failed
        # re-ingest. The transaction rolls the DELETE back on any error.
        async with c.transaction():
            await c.execute(f"DELETE FROM {_TABLE} WHERE doc_id = $1", doc_id)
            await c.executemany(
                f"INSERT INTO {_TABLE} (doc_id, kb_id, filename, lang, content, "
                f"embedding) VALUES ($1,$2,$3,$4,$5,$6::vector)",
                [
                    (doc_id, kb_id, filename, lang, ch, _vec_literal(vec))
                    for ch, vec in zip(chunks, vectors)
                ],
            )
    return len(chunks)


async def search(query: str, k: int = 5, kb_id: str = "") -> list[dict]:
    """Top-k chunks by cosine similarity (pgvector). Empty on miss.

    If kb_id is set, only chunks belonging to that knowledge base are searched.
    If empty, all chunks are searched (backwards-compatible global KB).
    """
    pool = await _pool_get()
    if pool is None:
        return []
    try:
        from src.embeddings import embed as _shared_embed

        qvec = await _shared_embed(query)
        if qvec is None:
            return []
        async with pool.acquire() as c:
            if kb_id:
                rows = await c.fetch(
                    f"SELECT content, 1 - (embedding <=> $1::vector) AS score "
                    f"FROM {_TABLE} WHERE kb_id = $3 "
                    f"ORDER BY embedding <=> $1::vector LIMIT $2",
                    _vec_literal(qvec), k, kb_id,
                )
            else:
                # CROSS-BUSINESS POLLUTION RISK at crore-scale: with empty
                # kb_id, this returns chunks from ALL businesses' KBs in
                # the shared voiceai.KbChunk table. The legacy global
                # search is kept for single-tenant deploys, but loud-log
                # so multi-tenant operators can spot the unset-config.
                logger.warning(
                    "kb_store.search: empty kb_id — searching ALL chunks "
                    "across ALL businesses. Set AgentConfig.kbVectorStoreId "
                    "or Campaign.kbId per call to prevent cross-business "
                    "answer leakage at scale."
                )
                rows = await c.fetch(
                    f"SELECT content, 1 - (embedding <=> $1::vector) AS score "
                    f"FROM {_TABLE} ORDER BY embedding <=> $1::vector LIMIT $2",
                    _vec_literal(qvec), k,
                )
        return [
            {"content": r["content"], "score": float(r["score"])}
            for r in rows
        ]
    except Exception:
        logger.debug("pgvector search failed", exc_info=True)
        return []


async def delete_document(doc_id: str) -> None:
    pool = await _pool_get()
    if pool is None:
        return
    async with pool.acquire() as c:
        await c.execute(f"DELETE FROM {_TABLE} WHERE doc_id = $1", doc_id)
