"""AdaptiveBuffer (jitter buffer) + EchoGuard advanced tests."""

from __future__ import annotations

from src.audio import AdaptiveBuffer, EchoGuard


# ─── EchoGuard advanced ────────────────────────────────────────────


def test_echo_guard_punctuation_diff_still_detects():
    eg = EchoGuard()
    eg.on_agent_started("Sure, I can help you with that.")
    # STT often drops punctuation.
    assert eg.is_echo("sure i can help you with that") is True


def test_echo_guard_whitespace_diff_still_detects():
    eg = EchoGuard()
    eg.on_agent_started("hello   sir")
    assert eg.is_echo("hello sir") is True


def test_echo_guard_case_diff_still_detects():
    eg = EchoGuard()
    eg.on_agent_started("HELLO World")
    assert eg.is_echo("hello world") is True


def test_echo_guard_unrelated_text_not_echo():
    eg = EchoGuard()
    eg.on_agent_started("appointment confirmed for tomorrow")
    assert eg.is_echo("what is my balance") is False


def test_echo_guard_indic_echo_detected():
    eg = EchoGuard()
    eg.on_agent_started("మీ appointment confirm chesam andi")
    assert eg.is_echo("మీ appointment confirm chesam andi") is True


# ─── AdaptiveBuffer ────────────────────────────────────────────────


def test_adaptive_buffer_default_state():
    b = AdaptiveBuffer()
    assert b.min_ms <= b.current_ms <= b.max_ms
    assert b.degraded is False


def test_adaptive_buffer_on_poor_quality_widens_buffer():
    b = AdaptiveBuffer()
    start = b.current_ms
    new = b.on_quality("poor")
    assert new >= start
    assert new <= b.max_ms
    assert b.degraded is True


def test_adaptive_buffer_on_lost_quality_widens_buffer():
    b = AdaptiveBuffer()
    start = b.current_ms
    new = b.on_quality("lost")
    assert new >= start
    assert b.degraded is True


def test_adaptive_buffer_recovers_on_good_quality():
    b = AdaptiveBuffer()
    b.on_quality("poor")
    b.on_quality("poor")
    # Now recover.
    b.on_quality("excellent")
    assert b.degraded is False


def test_adaptive_buffer_clamps_at_max():
    b = AdaptiveBuffer()
    for _ in range(50):
        b.on_quality("poor")
    assert b.current_ms <= b.max_ms


def test_adaptive_buffer_clamps_at_min():
    b = AdaptiveBuffer()
    for _ in range(50):
        b.on_quality("excellent")
    assert b.current_ms >= b.min_ms


def test_adaptive_buffer_unknown_quality_treated_as_good():
    b = AdaptiveBuffer()
    b.on_quality("poor")
    assert b.degraded
    b.on_quality("unknown-string")
    # Anything not poor/lost = recovered.
    assert not b.degraded
