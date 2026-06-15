"""Extended TranscriptStabilizer tests beyond the existing 4."""

from __future__ import annotations

from src.pipeline.stabilizer import TranscriptStabilizer


def _new(**kw) -> TranscriptStabilizer:
    return TranscriptStabilizer(
        min_stable_partials=kw.get("min_stable_partials", 2),
        debounce_seconds=kw.get("debounce_seconds", 0.0),
        min_confidence=kw.get("min_confidence", 0.0),
    )


def test_first_partial_emits_nothing():
    """A token must persist to stabilize; single sighting = nothing."""
    s = _new(min_stable_partials=2)
    out = s.push("hello", now=1.0)
    assert out == ""


def test_two_partials_emit_first_word():
    s = _new(min_stable_partials=2)
    s.push("hello", now=1.0)
    out = s.push("hello", now=1.1)
    assert "hello" in out


def test_three_partials_emit_two_words():
    s = _new(min_stable_partials=2)
    s.push("hello world", now=1.0)
    s.push("hello world", now=1.1)
    s.push("hello world today", now=1.2)
    # "hello world" stabilized first.
    assert s.stable_text == "hello world"


def test_flicker_rewinds_stable_prefix():
    """If the next partial diverges from the stable prefix, roll back."""
    s = _new(min_stable_partials=2)
    # Need 3 partials to stabilise BOTH tokens (per-token count semantics).
    s.push("naa order", now=1.0)
    s.push("naa order", now=1.1)
    s.push("naa order", now=1.2)
    assert "naa" in s.stable_text and "order" in s.stable_text
    # STT now rewrites the suffix.
    s.push("naa booking", now=1.3)
    # Stable should keep "naa" but roll back "order".
    assert "naa" in s.stable_text
    assert "order" not in s.stable_text


def test_reset_clears_state_completely():
    s = _new(min_stable_partials=2)
    s.push("hello", now=1.0)
    s.push("hello", now=1.1)
    assert s.stable_text == "hello"
    s.reset()
    assert s.stable_text == ""
    assert s._tracks == []


def test_low_confidence_blocks_stabilization():
    s = _new(min_stable_partials=2, min_confidence=0.7)
    # Provide low confidence per token
    s.push("hello", confidences=[0.3], now=1.0)
    s.push("hello", confidences=[0.3], now=1.1)
    # Should NOT stabilize despite repeat count.
    assert s.stable_text == ""


def test_high_confidence_allows_stabilization():
    s = _new(min_stable_partials=2, min_confidence=0.7)
    s.push("hello", confidences=[0.9], now=1.0)
    s.push("hello", confidences=[0.9], now=1.1)
    assert s.stable_text == "hello"


def test_debounce_window_respected():
    s = _new(min_stable_partials=2, debounce_seconds=0.5)
    s.push("hello", now=1.0)
    # Same time = within debounce window, should not stabilize even
    # though count == min_partials.
    s.push("hello", now=1.0)
    assert s.stable_text == ""
    s.push("hello", now=1.6)  # past debounce
    assert s.stable_text == "hello"


def test_empty_pushes_emit_nothing():
    s = _new()
    assert s.push("", now=1.0) == ""
    assert s.push(None, now=1.1) == ""
    assert s.stable_text == ""


def test_returns_only_newly_stabilized_tokens():
    s = _new(min_stable_partials=2)
    s.push("a b", now=1.0)
    out = s.push("a b", now=1.1)
    # First call returned nothing (not stable yet); second returns the
    # newly stable "a b".
    assert out.strip() in ("a", "a b", "b")
