"""Property-based / randomized tests — randomized inputs against
invariants. Catches edge cases handwritten tests miss."""

from __future__ import annotations

import random
import string

import pytest

from src.cache import _entry_id, ns_for, SemanticCache
from src.router.classifier import detect_language, classify
from src.audio import _norm, EchoGuard
from src.pipeline.tts import _safe_speaker, _safe_model, _V2_SPEAKERS, _V3_SPEAKERS
from src.cost import CallMeter
from src.router.intent_router import Route


def _rand_text(maxlen: int = 50) -> str:
    n = random.randint(0, maxlen)
    chars = string.ascii_lowercase + " ?,.!" + "ఆహాసరేఅండి" + "हाँबताइए"
    return "".join(random.choice(chars) for _ in range(n))


# ─── _entry_id properties ────────────────────────────────────────


def test_entry_id_invariant_length(_unused_seed=42):
    random.seed(42)
    for _ in range(200):
        s = _rand_text()
        h = _entry_id(s)
        assert len(h) == 20
        # SHA-1 hex chars only
        assert all(c in "0123456789abcdef" for c in h)


def test_entry_id_invariant_deterministic():
    random.seed(7)
    for _ in range(50):
        s = _rand_text()
        assert _entry_id(s) == _entry_id(s)


def test_entry_id_distribution_no_obvious_collisions():
    """Run 1000 random inputs — no more than ~2 collisions expected."""
    random.seed(123)
    seen = {}
    collisions = 0
    for i in range(1000):
        s = _rand_text(20) + str(i)
        h = _entry_id(s)
        if h in seen and seen[h] != s:
            collisions += 1
        seen[h] = s
    # 20-char SHA-1 prefix should have negligible collisions at this scale.
    assert collisions == 0, f"saw {collisions} collisions"


# ─── ns_for properties ────────────────────────────────────────────


def test_ns_for_invariant_length():
    random.seed(99)
    for _ in range(200):
        s = _rand_text(100)
        n = ns_for(s)
        assert len(n) == 12
        assert all(c in "0123456789abcdef" for c in n)


def test_ns_for_lowercase_invariant():
    random.seed(101)
    for _ in range(50):
        s = "Business " + str(random.randint(0, 999))
        assert ns_for(s) == ns_for(s.upper())
        assert ns_for(s) == ns_for(s.strip())


# ─── _norm properties ────────────────────────────────────────────


def test_norm_idempotent():
    """norm(norm(x)) == norm(x) — applying twice = same as once."""
    random.seed(7)
    for _ in range(100):
        s = _rand_text(40)
        assert _norm(_norm(s)) == _norm(s)


def test_norm_lowercase_invariant():
    random.seed(8)
    for _ in range(50):
        s = _rand_text(30)
        assert _norm(s) == _norm(s.upper())


def test_norm_never_throws():
    random.seed(11)
    for _ in range(200):
        s = _rand_text(30)
        _norm(s)  # must not raise
    # Edge inputs
    for s in ["", " ", "\x00\x01\x02", "🚀😀", "\n\n\n"]:
        _norm(s)


# ─── classify properties ────────────────────────────────────────


def test_classify_never_throws_on_random_input():
    random.seed(13)
    for _ in range(200):
        s = _rand_text(50)
        c = classify(s)
        assert c.language in ("te", "hi", "en", "mixed")
        assert isinstance(c.is_trivial, bool)
        assert 0.0 <= c.confidence <= 1.0


def test_detect_language_returns_valid_set():
    random.seed(17)
    valid = {"te", "hi", "en", "mixed"}
    for _ in range(200):
        s = _rand_text(50)
        assert detect_language(s) in valid


# ─── _safe_speaker properties ────────────────────────────────────


def test_safe_speaker_always_returns_valid_speaker():
    """Property: regardless of input, returned speaker is in the
    matching model's roster."""
    random.seed(19)
    for _ in range(100):
        bad = _rand_text(15)
        v2 = _safe_speaker("bulbul:v2", bad)
        assert v2 in _V2_SPEAKERS, f"v2 returned {v2} for input {bad!r}"
        v3 = _safe_speaker("bulbul:v3-beta", bad)
        assert v3 in _V3_SPEAKERS, f"v3 returned {v3} for input {bad!r}"


def test_safe_model_always_returns_known():
    random.seed(23)
    valid = {"bulbul:v2", "bulbul:v3-beta"}
    for _ in range(100):
        bad = _rand_text(20)
        out = _safe_model(bad)
        assert out in valid


# ─── CallMeter properties ───────────────────────────────────────


def test_meter_bypass_rate_in_unit_range():
    """For any mix of routes, bypass rate is in [0,1]."""
    random.seed(29)
    routes = list(Route)
    for _ in range(100):
        m = CallMeter()
        for _ in range(random.randint(1, 50)):
            m.record_route(random.choice(routes))
        assert 0.0 <= m.llm_bypass_rate <= 1.0


def test_meter_total_routes_equals_sum_of_counts():
    random.seed(31)
    routes = list(Route)
    for _ in range(20):
        m = CallMeter()
        n = random.randint(1, 50)
        for _ in range(n):
            m.record_route(random.choice(routes))
        assert sum(m.routes.values()) == n


# ─── EchoGuard properties ───────────────────────────────────────


def test_echo_guard_self_echo_always_detected():
    """If we just told the agent we said X, hearing X back must be echo."""
    random.seed(37)
    eg = EchoGuard()
    for _ in range(30):
        text = _rand_text(20)
        if not text.strip():
            continue
        eg.on_agent_started(text)
        assert eg.is_echo(text) is True


# ─── Cosine similarity properties ──────────────────────────────


def test_cosine_is_in_minus_one_to_one():
    import numpy as np
    sc = SemanticCache()
    random.seed(41)
    for _ in range(50):
        a = np.random.randn(128).astype(np.float32)
        b = np.random.randn(128).astype(np.float32)
        cos = sc._cos(a, b)
        assert -1.0001 <= cos <= 1.0001  # tiny float slop
