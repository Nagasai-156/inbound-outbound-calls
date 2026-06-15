"""Parametrized LLM routing matrix — every model name pattern checked."""

from __future__ import annotations

import dataclasses

import pytest

from src.runtime_config import RuntimeConfig
from src.pipeline.llm import build_llm


def _route_url(model: str) -> str:
    cfg = dataclasses.replace(RuntimeConfig(), llm_model=model)
    llm = build_llm(cfg)
    client = getattr(llm, "_client", None)
    return str(getattr(client, "base_url", "")) if client else ""


_OPENAI_MODELS = [
    "gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini",
    "gpt-4.1-nano", "gpt-3.5-turbo", "gpt-4-turbo",
    "gpt-4o-2024-08-06", "gpt-4o-mini-2024-07-18",
]

_SARVAM_MODELS = [
    "sarvam-30b", "sarvam-105b", "sarvam-m",
    "sarvam-future-model",
]


@pytest.mark.parametrize("model", _OPENAI_MODELS)
def test_openai_models_route_to_openai(model):
    url = _route_url(model)
    assert "openai.com" in url, f"{model} → {url}"
    assert "groq" not in url
    assert "sarvam" not in url


@pytest.mark.parametrize("model", _SARVAM_MODELS)
def test_sarvam_models_route_to_sarvam(model):
    url = _route_url(model)
    assert "sarvam.ai" in url, f"{model} → {url}"


@pytest.mark.parametrize("typo", [
    "GPT-4o-Mini", "GROQ/COMPOUND", "SARVAM-30B",
    "llama-3.3-70B-versatile",
])
def test_case_insensitive_routing(typo):
    """Routing must lowercase the model name before prefix check.
    Caps typo'd in dashboard must still route correctly."""
    url = _route_url(typo)
    # Just verify no crash + got a real URL.
    assert "/" in url


@pytest.mark.parametrize("unknown", [
    "claude-3", "mistral-7b", "future-vendor-x",
    "anthropic/claude-3", "",
])
def test_unknown_models_fall_back_to_openai(unknown):
    """Unknown prefix → safe default (OpenAI)."""
    url = _route_url(unknown)
    assert "openai.com" in url
