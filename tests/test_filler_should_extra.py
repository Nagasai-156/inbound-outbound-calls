"""Extended should_filler + pick_filler tests."""

from __future__ import annotations

import dataclasses

from src.filler import should_filler, pick_filler, _lang_key
from src.router.intent_router import Route
from src.runtime_config import RuntimeConfig


# ─── _lang_key ──────────────────────────────────────────────────────


def test_lang_key_telugu():
    assert _lang_key("te") == "te"
    assert _lang_key("te-IN") == "te"
    assert _lang_key("te-mix") == "te"


def test_lang_key_hindi():
    assert _lang_key("hi") == "hi"
    assert _lang_key("hi-IN") == "hi"


def test_lang_key_english_default():
    assert _lang_key("en") == "en"
    assert _lang_key(None) == "en"
    assert _lang_key("") == "en"
    assert _lang_key("xx-yy") == "en"


# ─── should_filler ─────────────────────────────────────────────────


def test_should_filler_fires_on_llm_route():
    cfg = RuntimeConfig()
    assert should_filler(Route.LLM, cfg=cfg) is True


def test_should_filler_skips_canned_route():
    """Canned route is instant (~100ms) — adding a filler before it
    creates the dreaded 'okay sir hmm' pre-bot tell."""
    cfg = RuntimeConfig()
    assert should_filler(Route.CANNED, cfg=cfg) is False


def test_should_filler_skips_cache_route():
    """Cache hits are instant too."""
    cfg = RuntimeConfig()
    assert should_filler(Route.CACHE, cfg=cfg) is False


def test_should_filler_skips_action_route():
    """Action route handles deterministic tools; fillers there add noise."""
    cfg = RuntimeConfig()
    assert should_filler(Route.ACTION, cfg=cfg) is False


def test_should_filler_fires_on_low_stt_confidence():
    cfg = RuntimeConfig()
    # Even with non-LLM route, low confidence should trigger filler.
    assert should_filler(Route.CANNED, stt_confidence=0.1, cfg=cfg) is True


def test_should_filler_fires_when_elapsed_over_threshold():
    cfg = RuntimeConfig()
    # filler_latency_threshold defaults to 0.3s; elapsed > should fire.
    assert should_filler(Route.CANNED, elapsed_seconds=0.5, cfg=cfg) is True


def test_should_filler_does_not_fire_under_threshold():
    cfg = RuntimeConfig()
    assert should_filler(Route.CANNED, elapsed_seconds=0.05, cfg=cfg) is False


# ─── pick_filler ───────────────────────────────────────────────────


def test_pick_filler_returns_nonempty_string():
    """No empty fillers — would be silence with a beat."""
    f = pick_filler("te")
    assert isinstance(f, str)
    assert len(f) > 0


def test_pick_filler_telugu_in_telugu_script():
    """Telugu pool must have Telugu-script entries (not pure Roman)."""
    fillers_seen = {pick_filler("te") for _ in range(40)}
    # At least one should contain Telugu characters.
    has_telugu = any(
        any(0x0C00 <= ord(c) <= 0x0C7F for c in f)
        for f in fillers_seen
    )
    assert has_telugu


def test_pick_filler_hindi_in_devanagari():
    fillers_seen = {pick_filler("hi") for _ in range(40)}
    has_devanagari = any(
        any(0x0900 <= ord(c) <= 0x097F for c in f)
        for f in fillers_seen
    )
    assert has_devanagari


def test_pick_filler_english():
    fillers_seen = {pick_filler("en") for _ in range(40)}
    # English-only pool — should NOT contain Telugu/Devanagari.
    for f in fillers_seen:
        for c in f:
            assert not (0x0C00 <= ord(c) <= 0x0C7F), f"telugu char in en pool: {f}"
            assert not (0x0900 <= ord(c) <= 0x097F), f"devanagari char in en pool: {f}"


def test_pick_filler_never_repeats_back_to_back():
    """Anti-repeat rotation: same index can't fire twice in a row."""
    prev = pick_filler("en")
    different_count = 0
    same_count = 0
    for _ in range(20):
        curr = pick_filler("en")
        if curr != prev:
            different_count += 1
        else:
            same_count += 1
        prev = curr
    # In 20 picks across a pool of 10, hits should be different > 0
    # times. Strict back-to-back-same is forbidden by design.
    assert same_count == 0, f"saw {same_count} back-to-back repeats"


def test_pick_filler_unknown_language_falls_back_to_english():
    f = pick_filler("xyz")
    # Should not crash; should produce SOMETHING.
    assert isinstance(f, str) and len(f) > 0
