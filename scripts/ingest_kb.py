"""Ingest knowledge-base documents into the pgvector KB (Supabase).

This is the ONE knowledge base. (The old OpenAI file_search path was
retired — runtime retrieval is pgvector via src/kb_store.py, so ingest
must write there too, otherwise ingested docs were never queried.)

Usage:
    python scripts/ingest_kb.py ./kb_docs
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from src.kb_store import ingest_document

_SUPPORTED = {".txt", ".md", ".pdf", ".docx", ".json", ".html"}


def _extract(path: Path) -> str:
    ext = path.suffix.lower()
    data = path.read_bytes()
    if ext in (".txt", ".md", ".json", ".html"):
        text = data.decode("utf-8", errors="ignore")
        if ext == ".html":
            import re

            text = re.sub(r"<[^>]+>", " ", text)
        return text
    if ext == ".pdf":
        import io

        from pypdf import PdfReader

        return "\n".join(
            (p.extract_text() or "")
            for p in PdfReader(io.BytesIO(data)).pages
        )
    if ext == ".docx":
        import io

        import docx

        d = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in d.paragraphs)
    return ""


async def _run(docs_dir: str) -> None:
    path = Path(docs_dir)
    if not path.is_dir():
        sys.exit(f"Not a directory: {docs_dir}")
    files = [
        p for p in sorted(path.rglob("*"))
        if p.is_file() and p.suffix.lower() in _SUPPORTED
    ]
    if not files:
        sys.exit(f"No ingestible files {sorted(_SUPPORTED)} in {docs_dir}")

    total = 0
    for f in files:
        text = _extract(f)
        if not text.strip():
            print(f"skip (no text): {f.name}")
            continue
        doc_id = uuid.uuid4().hex
        n = await ingest_document(doc_id, f.name, text)
        total += n
        print(f"ingested {f.name} -> {n} chunk(s) into pgvector")
    print(f"\nDone. {total} chunk(s) across {len(files)} file(s).")


if __name__ == "__main__":
    asyncio.run(_run(sys.argv[1] if len(sys.argv) > 1 else "./kb_docs"))
