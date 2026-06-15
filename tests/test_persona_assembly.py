"""Persona prompt assembly tests — inbound vs outbound, business
context injection, sanitization."""

from __future__ import annotations

import dataclasses

from src.persona.base import base_prompt, sanitize_business_context, USE_CASE_BLOCKS
from src.persona.inbound import inbound_prompt
from src.persona.outbound import outbound_prompt
from src.runtime_config import RuntimeConfig


def _cfg(**kw) -> RuntimeConfig:
    return dataclasses.replace(RuntimeConfig(), **kw)


# ─── base_prompt ────────────────────────────────────────────────────


def test_base_prompt_returns_string():
    p = base_prompt(RuntimeConfig())
    assert isinstance(p, str) and len(p) > 100


def test_base_prompt_contains_core_constraints():
    p = base_prompt(RuntimeConfig())
    # Spot-check critical rules that MUST be present
    for marker in [
        "BITE-SIZED",
        "ACTION-HALLUCINATION",
        "VERBAL-CHECK-COMMITMENT",
        "GROUNDING",
        "BANNED GOODBYES",
    ]:
        assert marker in p, f"missing {marker} in base prompt"


def test_inbound_prompt_appends_business_description_when_present():
    """base_prompt itself doesn't inject biz; the wrapping persona
    (inbound/outbound) does. This pins the wrapping behaviour."""
    cfg = _cfg(business_description="Dental clinic. We offer cleaning, fillings.")
    p = inbound_prompt(cfg)
    assert "Dental clinic" in p
    assert "cleaning" in p


def test_inbound_prompt_omits_business_block_when_empty():
    cfg = _cfg(business_description="")
    p = inbound_prompt(cfg)
    assert "BUSINESS CONTEXT:" not in p


def test_base_prompt_includes_use_case_block_for_appointment():
    cfg = _cfg(use_case_type="appointment")
    p = base_prompt(cfg)
    assert "TABLE-GROUNDING-LAW" in p
    assert "book_appointment" in p


def test_base_prompt_includes_reschedule_block():
    cfg = _cfg(use_case_type="reschedule")
    p = base_prompt(cfg)
    assert "RESCHEDULE" in p or "reschedule_appointment" in p


def test_base_prompt_reminder_block():
    cfg = _cfg(use_case_type="reminder")
    p = base_prompt(cfg)
    assert "REMINDER" in p or "my_appointment" in p


def test_base_prompt_custom_omits_booking_rules():
    cfg = _cfg(use_case_type="custom")
    p = base_prompt(cfg)
    # custom = no use-case-specific block appended
    assert "TABLE-GROUNDING-LAW" not in p


# ─── sanitize_business_context ───────────────────────────────────


def test_sanitize_passes_clean_text():
    out = sanitize_business_context("We open at 9 AM, close at 6 PM.")
    assert "9" in out


def test_sanitize_handles_empty():
    assert sanitize_business_context("") == ""
    assert sanitize_business_context(None) == ""


def test_sanitize_strips_unfilled_template_placeholders():
    """The real job: replace `{{phone}}` / `[full_address]` with a
    friendly cue so the LLM doesn't read raw template syntax aloud."""
    out = sanitize_business_context("Address: {{full_address}}, Phone: [number]")
    assert "{{full_address}}" not in out
    assert "[number]" not in out
    assert "team will share" in out.lower()


# ─── inbound_prompt ──────────────────────────────────────────────


def test_inbound_prompt_uses_inbound_persona_text():
    cfg = _cfg(inbound_persona="")  # use built-in
    p = inbound_prompt(cfg)
    # built-in inbound = support tone; should contain "support" or "help".
    lower = p.lower()
    assert "support" in lower or "help" in lower or "assist" in lower


def test_inbound_prompt_dashboard_override_wins():
    cfg = _cfg(inbound_persona="OPERATOR_OVERRIDE_MARKER")
    p = inbound_prompt(cfg)
    assert "OPERATOR_OVERRIDE_MARKER" in p


# ─── outbound_prompt ─────────────────────────────────────────────


def test_outbound_prompt_uses_outbound_persona_text():
    cfg = _cfg(outbound_persona="")
    p = outbound_prompt(cfg)
    # Built-in outbound = warmer/permission-question style.
    lower = p.lower()
    # check at least one outbound-style marker
    assert any(k in lower for k in ["minute", "intro", "permission", "warm"])


def test_outbound_prompt_dashboard_override_wins():
    cfg = _cfg(outbound_persona="CAMPAIGN_SCRIPT_X")
    p = outbound_prompt(cfg)
    assert "CAMPAIGN_SCRIPT_X" in p


def test_outbound_prompt_includes_language_mirror():
    p = outbound_prompt(RuntimeConfig())
    assert "LANGUAGE-MIRROR" in p


# ─── USE_CASE_BLOCKS dict ───────────────────────────────────────


def test_use_case_blocks_has_all_industry_keys():
    """Every use case the dashboard offers must have a corresponding
    behaviour block (or empty string fallback)."""
    needed = ["appointment", "reschedule", "reminder", "sales", "support"]
    for k in needed:
        assert k in USE_CASE_BLOCKS or USE_CASE_BLOCKS.get(k, None) is not None
