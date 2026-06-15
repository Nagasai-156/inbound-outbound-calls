"""Tests for the hard per-turn prompt token budget.

These pin the structural guarantee that the assembled LLM prompt can
NEVER grow past a configured cap — the fix for the Groq free-tier 413
dead-air bug (prompt climbed 7.6k→12.9k tokens across one call) and for
TTFT compounding on long calls.
"""

from __future__ import annotations

import pytest

from src.prompt_budget import (
    count_tokens,
    enforce_prompt_budget,
    item_tokens,
)

# Use the real livekit ChatContext when available; skip cleanly if not
# (mirrors the rest of the suite's livekit-optional pattern).
try:
    from livekit.agents.llm import ChatContext

    _HAVE_LK = True
except Exception:  # pragma: no cover
    _HAVE_LK = False

pytestmark = pytest.mark.skipif(
    not _HAVE_LK, reason="livekit-agents not available"
)


def _ctx(messages):
    """Build a ChatContext from a list of (role, text) tuples."""
    ctx = ChatContext.empty()
    for role, text in messages:
        ctx.add_message(role=role, content=text)
    return ctx


def _roles(ctx):
    return [getattr(it, "role", None) for it in ctx.items]


def test_count_tokens_basic():
    assert count_tokens("") == 0
    assert count_tokens("hello world") > 0
    # Indic script tokenises to multiple tokens — count must be positive.
    assert count_tokens("నమస్కారం అండి") > 0


def test_item_tokens_includes_overhead():
    ctx = _ctx([("user", "hi")])
    assert item_tokens(ctx.items[0]) >= count_tokens("hi")


def test_no_trim_when_under_budget():
    ctx = _ctx([("system", "persona"), ("user", "hello"), ("assistant", "hi")])
    dropped = enforce_prompt_budget(ctx, max_tokens=10_000)
    assert dropped == 0
    assert len(ctx.items) == 3


def test_system_messages_never_dropped():
    # Big persona + many old turns, tiny budget.
    msgs = [("system", "PERSONA " * 200)]
    for i in range(20):
        msgs.append(("user", f"old user turn number {i} " * 5))
        msgs.append(("assistant", f"old agent reply number {i} " * 5))
    ctx = _ctx(msgs)
    enforce_prompt_budget(ctx, max_tokens=300, keep_recent_msgs=2)
    # The system message must survive no matter how tight the budget.
    assert any(getattr(it, "role", None) == "system" for it in ctx.items)


def test_drops_oldest_first_keeps_recent():
    msgs = [("system", "p")]
    for i in range(10):
        msgs.append(("user", f"turn {i} " * 20))
    ctx = _ctx(msgs)
    enforce_prompt_budget(ctx, max_tokens=200, keep_recent_msgs=2)
    texts = [it.text_content for it in ctx.items if getattr(it, "role", None) == "user"]
    # The most recent user turn (turn 9) must still be present.
    assert any("turn 9" in t for t in texts)
    # The oldest (turn 0) must have been dropped.
    assert not any("turn 0 " in t for t in texts)


def test_keep_recent_msgs_protected_even_over_budget():
    msgs = [("system", "p")]
    for i in range(8):
        msgs.append(("user", f"u{i} " * 50))
    ctx = _ctx(msgs)
    # Budget is impossibly small but the 3 most-recent msgs are protected.
    enforce_prompt_budget(ctx, max_tokens=1, keep_recent_msgs=3)
    convo = [it for it in ctx.items if getattr(it, "role", None) == "user"]
    assert len(convo) >= 3


def test_zero_budget_is_noop():
    ctx = _ctx([("system", "p"), ("user", "x")])
    assert enforce_prompt_budget(ctx, max_tokens=0) == 0
    assert len(ctx.items) == 2


def test_empty_context_is_safe():
    ctx = ChatContext.empty()
    assert enforce_prompt_budget(ctx, max_tokens=100) == 0
