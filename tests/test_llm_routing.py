"""Provider routing tests for build_llm — Sarvam / OpenAI / Mistral.

The dropdown lets operators pick a provider via model-name prefix. A wrong
prefix routes to the wrong base_url and the call silently 404s mid-
conversation (the bug we hardened against). These tests assert every model
in the dropdown lands at the correct base_url.
"""

from __future__ import annotations

import dataclasses

from src.runtime_config import RuntimeConfig
from src.pipeline.llm import build_llm


def _base_url(cfg_model: str) -> str:
    cfg = dataclasses.replace(RuntimeConfig(), llm_model=cfg_model)
    llm = build_llm(cfg)
    client = getattr(llm, "_client", None)
    assert client is not None, f"build_llm({cfg_model}) returned no client"
    return str(getattr(client, "base_url", ""))


def test_openai_models_route_to_openai():
    for m in ("gpt-4o-mini", "gpt-4.1-nano", "gpt-4o", "gpt-4.1", "gpt-4.1-mini"):
        url = _base_url(m)
        assert "openai.com" in url, f"{m} should route to OpenAI, got {url}"
        assert "groq.com" not in url
        assert "sarvam.ai" not in url


def test_mistral_routes_correctly():
    # Mistral is selected via the `mistral/` prefix and routes to its base.
    assert "mistral.ai" in _base_url("mistral/mistral-small-latest")


def test_bedrock_routes_to_mumbai():
    # Bedrock is selected via the `bedrock/` prefix and routes to its
    # India-hosted (ap-south-1) OpenAI-compatible endpoint. The `bedrock/`
    # prefix is stripped so the real model id reaches the API.
    url = _base_url("bedrock/mistral.ministral-3-14b-instruct")
    assert "bedrock-runtime.ap-south-1.amazonaws.com" in url
    assert "openai/v1" in url
    assert "openai.com" not in url


def test_sarvam_routes_to_sarvam():
    url = _base_url("sarvam-30b")
    assert "sarvam.ai" in url
    assert "openai.com" not in url


def test_openai_default_for_unknown_prefix():
    # Unknown model name (typo / future addition) falls back to OpenAI —
    # the safe default since that's where most user keys are valid.
    url = _base_url("some-unknown-future-model-xyz")
    assert "openai.com" in url
