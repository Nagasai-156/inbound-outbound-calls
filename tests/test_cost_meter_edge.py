"""CallMeter edge cases — bypass rate math, history trimming, summary."""

from __future__ import annotations

from dataclasses import dataclass

from src.cost import CallMeter, trim_history
from src.router.intent_router import Route


@dataclass
class _Msg:
    role: str
    content: str = ""


def test_empty_meter_bypass_is_zero():
    m = CallMeter()
    assert m.llm_bypass_rate == 0.0


def test_all_canned_turns_bypass_100_percent():
    m = CallMeter()
    for _ in range(5):
        m.record_route(Route.CANNED)
    assert m.llm_bypass_rate == 1.0


def test_all_llm_turns_bypass_0_percent():
    m = CallMeter()
    for _ in range(5):
        m.record_route(Route.LLM)
    assert m.llm_bypass_rate == 0.0


def test_half_llm_half_canned_bypass_50_percent():
    m = CallMeter()
    m.record_route(Route.LLM)
    m.record_route(Route.CANNED)
    assert m.llm_bypass_rate == 0.5


def test_cache_route_counts_as_bypass():
    m = CallMeter()
    m.record_route(Route.CACHE)
    assert m.llm_bypass_rate == 1.0


def test_action_route_counts_as_bypass():
    m = CallMeter()
    m.record_route(Route.ACTION)
    assert m.llm_bypass_rate == 1.0


def test_llm_calls_only_increments_on_llm_route():
    m = CallMeter()
    m.record_route(Route.CANNED)
    m.record_route(Route.LLM)
    m.record_route(Route.CACHE)
    m.record_route(Route.LLM)
    assert m.llm_calls == 2
    assert sum(m.routes.values()) == 4


def test_kb_calls_independent_of_routes():
    m = CallMeter()
    m.record_kb()
    m.record_kb()
    m.record_kb()
    assert m.kb_calls == 3
    assert sum(m.routes.values()) == 0
    assert m.llm_bypass_rate == 0.0  # no turns recorded yet


def test_summary_format_is_grep_friendly():
    m = CallMeter()
    m.record_route(Route.LLM)
    m.record_route(Route.CANNED)
    m.record_kb()
    s = m.summary()
    assert "turns=2" in s
    assert "llm=1" in s
    assert "kb=1" in s
    assert "bypass=50%" in s


# ─── trim_history ────────────────────────────────────────────────────


def test_trim_preserves_system_messages():
    messages = [
        _Msg("system", "persona"),
        _Msg("system", "rules"),
        _Msg("user", "u1"),
        _Msg("assistant", "a1"),
        _Msg("user", "u2"),
        _Msg("assistant", "a2"),
        _Msg("user", "u3"),
        _Msg("assistant", "a3"),
    ]
    trimmed = trim_history(messages, max_turns=2)
    system_count = sum(1 for m in trimmed if m.role == "system")
    assert system_count == 2  # all system msgs preserved


def test_trim_keeps_last_n_turns():
    """max_turns=2 means last 2 user+assistant pairs = 4 messages."""
    messages = [_Msg("system", "p")] + [
        _Msg("user" if i % 2 == 0 else "assistant", f"m{i}")
        for i in range(10)
    ]
    trimmed = trim_history(messages, max_turns=2)
    convo = [m for m in trimmed if m.role != "system"]
    assert len(convo) == 4  # 2 turns * 2 messages each


def test_trim_with_max_turns_zero_keeps_only_system():
    messages = [
        _Msg("system", "p"),
        _Msg("user", "u1"),
        _Msg("assistant", "a1"),
    ]
    trimmed = trim_history(messages, max_turns=0)
    assert all(m.role == "system" for m in trimmed)


def test_trim_handles_empty_history():
    assert trim_history([], max_turns=5) == []


def test_trim_handles_only_system_messages():
    messages = [_Msg("system", "p"), _Msg("system", "q")]
    trimmed = trim_history(messages, max_turns=10)
    assert len(trimmed) == 2
