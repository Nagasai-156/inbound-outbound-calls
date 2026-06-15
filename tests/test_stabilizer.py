"""Transcript stabilizer — flicker must not leak downstream."""

from src.pipeline.stabilizer import TranscriptStabilizer


def _fast():
    # debounce 0 so the test exercises the persistence logic, not the clock
    return TranscriptStabilizer(
        min_stable_partials=2, debounce_seconds=0.0, min_confidence=0.0
    )


def test_token_stabilizes_only_after_repeat():
    s = _fast()
    assert s.push("naa") == ""            # first sighting -> not stable
    assert s.push("naa or") == "naa"      # "naa" persisted -> stable
    assert s.stable_text == "naa"


def test_flicker_does_not_emit_wrong_token():
    s = _fast()
    s.push("naa or")
    s.push("naa order")          # "or" -> "order": tail rewritten
    out = s.push("naa order")    # "order" now persisted twice
    assert "order" in s.stable_text
    assert "or" not in s.stable_text.split()


def test_reset_clears_state():
    s = _fast()
    s.push("hello")
    s.push("hello")
    assert s.stable_text == "hello"
    s.reset()
    assert s.stable_text == ""


def test_low_confidence_blocks_stabilization():
    s = TranscriptStabilizer(
        min_stable_partials=1, debounce_seconds=0.0, min_confidence=0.8
    )
    # confidence below floor -> token withheld
    assert s.push("refund", confidences=[0.3]) == ""
    # confidence above floor -> released
    assert s.push("refund", confidences=[0.95]) == "refund"
