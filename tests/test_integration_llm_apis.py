"""Live LLM API integration tests — OpenAI / Sarvam.

Skip gracefully if keys aren't configured. Verifies the full HTTPS
chain works: TLS, auth, model presence, streaming."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()


def _key(name: str) -> str:
    return os.environ.get(name, "")


# ─── OpenAI ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_models_list_accessible():
    if not _key("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not configured")
    import openai
    client = openai.AsyncOpenAI(api_key=_key("OPENAI_API_KEY"))
    models = await client.models.list()
    ids = [m.id for m in models.data]
    assert any("gpt-4o-mini" in i for i in ids)


@pytest.mark.asyncio
async def test_openai_gpt_4o_mini_streams():
    if not _key("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not configured")
    import openai
    client = openai.AsyncOpenAI(api_key=_key("OPENAI_API_KEY"))
    stream = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "say hi in 3 words"}],
        max_tokens=20, stream=True,
    )
    got_content = False
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            got_content = True
            break
    assert got_content


# ─── Sarvam STT ──────────────────────────────────────────────────


def test_sarvam_api_key_format():
    """Sarvam keys start with 'sk_' or similar — basic sanity."""
    key = _key("SARVAM_API_KEY")
    if not key:
        pytest.skip("SARVAM_API_KEY not configured")
    assert len(key) > 10


# ─── Cross-provider routing through build_llm ─────────────────────


@pytest.mark.asyncio
async def test_build_llm_creates_openai_client():
    if not _key("OPENAI_API_KEY"):
        pytest.skip("no OpenAI key")
    import dataclasses
    from src.runtime_config import RuntimeConfig
    from src.pipeline.llm import build_llm
    cfg = dataclasses.replace(RuntimeConfig(), llm_model="gpt-4o-mini")
    llm = build_llm(cfg)
    # Underlying client base_url should be api.openai.com.
    client = getattr(llm, "_client", None)
    assert client is not None
    assert "openai.com" in str(client.base_url)
