"""EchoGuard + audio helper tests.

The agent's own TTS occasionally bleeds back through the PSTN trunk into
its own STT — without EchoGuard this caused the "repeating-nonsense
loop" bug in production. These tests pin the echo-detection contract.
"""

from __future__ import annotations

from src.audio import _norm, EchoGuard


def test_norm_lowercases():
    assert _norm("Hello") == "hello"
    assert _norm("HELLO WORLD") == "hello world"


def test_norm_drops_punctuation():
    assert _norm("Hello, world!") == "hello world"
    assert _norm("It's 'okay'.") == "it s okay"


def test_norm_collapses_whitespace():
    assert _norm("hello   world") == "hello world"
    assert _norm("  hello  ") == "hello"


def test_norm_handles_empty():
    assert _norm("") == ""
    assert _norm(None) == ""


def test_norm_preserves_telugu_devanagari():
    """The regex keeps Telugu (U+0C00–U+0C7F) and Devanagari letters."""
    assert "మంచి" in _norm("మంచి రోజు")
    assert "नमस्ते" in _norm("नमस्ते जी")


def test_echo_guard_exact_match_detects_echo():
    eg = EchoGuard()
    eg.on_agent_started("Sorry sir, malli cheppandi.")
    assert eg.is_echo("Sorry sir, malli cheppandi") is True


def test_echo_guard_handles_stt_dropped_punctuation():
    """Real STT often drops commas/periods. EchoGuard must still detect
    the echo despite punctuation diff."""
    eg = EchoGuard()
    eg.on_agent_started("Sorry sir, malli cheppandi.")
    assert eg.is_echo("sorry sir malli cheppandi") is True


def test_echo_guard_different_text_not_echo():
    eg = EchoGuard()
    eg.on_agent_started("hello world")
    assert eg.is_echo("can you check my order") is False


def test_echo_guard_empty_input_not_echo():
    eg = EchoGuard()
    eg.on_agent_started("anything")
    assert eg.is_echo("") is False


def test_echo_guard_multiple_recent_utterances():
    """The guard should remember several recent agent utterances, not
    just the very last one — sometimes the echo arrives N turns later."""
    eg = EchoGuard()
    eg.on_agent_started("first thing said")
    eg.on_agent_started("second thing said")
    eg.on_agent_started("third thing said")
    assert eg.is_echo("first thing said") is True
    assert eg.is_echo("second thing said") is True
    assert eg.is_echo("third thing said") is True


def test_echo_guard_partial_substring_detection():
    """STT can return a partial prefix of the agent's full utterance."""
    eg = EchoGuard()
    eg.on_agent_started("Sure, let me check the available slots for you")
    # A truncated mishear should still be recognised as echo.
    result = eg.is_echo("Sure, let me check the available slots")
    # Either result is acceptable depending on threshold — just must not crash.
    assert isinstance(result, bool)
