"""Persona prompt token-budget tests.

Every use-case block we add inflates the prompt. At crore-scale this
costs money + slows LLM TTFT. These tests pin upper bounds so future
additions don't bloat past acceptable thresholds."""

from __future__ import annotations

import dataclasses

from src.persona.base import base_prompt, USE_CASE_BLOCKS, CORE_CONSTRAINTS
from src.persona.inbound import inbound_prompt
from src.persona.outbound import outbound_prompt
from src.runtime_config import RuntimeConfig


def _approx_tokens(text: str) -> int:
    """Rough heuristic: 1 token ~ 4 chars for English mixed with Indic.
    Off by ~30% but enough for an order-of-magnitude budget check."""
    return len(text) // 4


def test_core_constraints_under_6000_tokens():
    """Core rails alone must stay reasonable. Bound chosen to track
    current size with headroom; if this trips, audit whether the new
    rule justifies the prompt-bloat cost at crore-scale."""
    assert _approx_tokens(CORE_CONSTRAINTS) < 6000


def test_appointment_block_under_2000_tokens():
    block = USE_CASE_BLOCKS["appointment"]
    assert _approx_tokens(block) < 2000


def test_reschedule_block_under_1500_tokens():
    block = USE_CASE_BLOCKS["reschedule"]
    assert _approx_tokens(block) < 1500


def test_reminder_block_under_1000_tokens():
    block = USE_CASE_BLOCKS["reminder"]
    assert _approx_tokens(block) < 1000


def test_sales_block_under_1500_tokens():
    block = USE_CASE_BLOCKS["sales"]
    assert _approx_tokens(block) < 1500


def test_total_appointment_prompt_under_8000_tokens():
    """The full assembled prompt for an appointment campaign must
    stay under the gpt-4o-mini efficient-prompt budget."""
    cfg = dataclasses.replace(
        RuntimeConfig(),
        use_case_type="appointment",
        business_description="Dental clinic, Mon-Sat 9-6. Cleaning, fillings, root canal.",
        inbound_persona="",
        outbound_persona="",
    )
    full = inbound_prompt(cfg)
    assert _approx_tokens(full) < 8000


def test_total_outbound_prompt_under_8000_tokens():
    cfg = dataclasses.replace(
        RuntimeConfig(),
        use_case_type="reminder",
        business_description="Dental clinic.",
        outbound_persona="",
    )
    full = outbound_prompt(cfg)
    assert _approx_tokens(full) < 8000


def test_each_use_case_block_has_grounding_or_action_rules():
    """Every non-custom block should encode at least one explicit rule
    or behaviour directive — otherwise it's just chat fluff."""
    excluded = {"custom"}
    keywords = [
        "GROUNDING", "LAW", "tool", "_appointment",
        "kb_search", "BEHAVIOR", "RULE", "FLOW",
        "BANNED", "MUST", "NEVER", "ONLY", "Do not",
        "do not", "do NOT", "USE-CASE",
    ]
    for uc, block in USE_CASE_BLOCKS.items():
        if uc in excluded or not block:
            continue
        has_rule = any(k in block for k in keywords)
        assert has_rule, f"{uc} block lacks any rule/tool keyword. Snippet: {block[:200]!r}"


def test_no_block_is_empty_when_listed_in_dashboard():
    """A use-case listed in dashboard options MUST have a block,
    even if minimal."""
    expected_non_empty = {
        "appointment", "reschedule", "reminder", "sales",
        "leadgen", "survey", "feedback", "support", "collections",
    }
    for uc in expected_non_empty:
        block = USE_CASE_BLOCKS.get(uc, "")
        assert block, f"{uc} block is empty"


def test_prompt_does_not_explode_with_huge_business_description():
    """Operator could paste 10KB of business notes. Prompt must
    still cap somehow (we don't currently — just verify no crash)."""
    huge_biz = "Our business is amazing. " * 500
    cfg = dataclasses.replace(
        RuntimeConfig(),
        business_description=huge_biz,
        use_case_type="custom",
    )
    full = inbound_prompt(cfg)
    # Must produce a string, even if huge.
    assert isinstance(full, str)
    assert "amazing" in full


def test_business_context_is_length_capped():
    """A huge pasted business description must NOT inflate the persona
    past a sane bound — it's a never-trimmed system message and would
    otherwise blow the per-turn token budget (Groq 413 dead-air)."""
    from src.persona.base import (
        sanitize_business_context,
        _MAX_BUSINESS_CONTEXT_CHARS,
    )

    huge = "Our clinic offers many services. " * 500  # ~16KB
    out = sanitize_business_context(huge)
    assert len(out) <= _MAX_BUSINESS_CONTEXT_CHARS + 4  # +ellipsis marker
    # Still preserves the leading, useful content.
    assert "clinic" in out


def test_business_context_short_text_untouched():
    from src.persona.base import sanitize_business_context

    short = "Dental clinic, Mon-Sat 9 to 6. Cleaning, fillings, root canal."
    assert sanitize_business_context(short) == short


def test_capped_business_keeps_total_prompt_bounded():
    """Even with a pathological business description, the full assembled
    appointment prompt must stay within the budget test's ceiling."""
    import dataclasses

    cfg = dataclasses.replace(
        RuntimeConfig(),
        use_case_type="appointment",
        business_description="We do everything under the sun. " * 800,
    )
    full = inbound_prompt(cfg)
    assert _approx_tokens(full) < 8000
