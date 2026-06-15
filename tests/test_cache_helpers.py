"""Pure-helper tests for src/cache.py — _entry_id, ns_for, _cos.

These do NOT touch Redis or the embedder; they cover the deterministic
helper functions that drive cache correctness (stable ids across process
restarts, per-business namespace isolation, cosine math)."""

from __future__ import annotations

import numpy as np

from src.cache import _entry_id, ns_for, SemanticCache


# ─── _entry_id (stable SHA-1) ────────────────────────────────────────


def test_entry_id_is_stable_across_calls():
    assert _entry_id("hello world") == _entry_id("hello world")


def test_entry_id_differs_for_different_queries():
    assert _entry_id("hello") != _entry_id("world")


def test_entry_id_ignores_case_and_whitespace():
    """Otherwise 'Hello' and 'hello' would store two cache rows for the
    same logical question, blowing up the index size."""
    assert _entry_id("Hello") == _entry_id("hello")
    assert _entry_id("hello") == _entry_id("  hello  ")
    assert _entry_id("HELLO") == _entry_id("hello")


def test_entry_id_is_20_chars():
    """Truncated SHA-1 prefix to keep Redis hash keys short."""
    assert len(_entry_id("anything")) == 20


def test_entry_id_pure_function_no_per_process_randomness():
    """Regression: Python's built-in hash() is per-process random; the
    OLD implementation used hash() and every restart orphaned all cache
    entries. SHA-1 must be process-independent."""
    # Compare to a stable expected value.
    import hashlib
    expected = hashlib.sha1(b"specific test query").hexdigest()[:20]
    assert _entry_id("specific test query") == expected


# ─── ns_for (per-business namespace) ─────────────────────────────────


def test_ns_for_stable_per_persona():
    assert ns_for("dental persona") == ns_for("dental persona")


def test_ns_for_differs_per_persona():
    assert ns_for("dental persona") != ns_for("salon persona")


def test_ns_for_handles_none():
    assert ns_for(None) == ns_for("default")


def test_ns_for_handles_empty():
    assert ns_for("") == ns_for("default")


def test_ns_for_is_short():
    """12-char SHA-1 prefix — long enough for collision resistance
    across hundreds of businesses, short enough to keep keys readable."""
    assert len(ns_for("any business")) == 12


def test_ns_for_lowercase_and_whitespace_normalisation():
    """A dashboard whitespace edit shouldn't invalidate the cache."""
    assert ns_for("Dental Persona") == ns_for("dental persona")
    assert ns_for("  Dental Persona  ") == ns_for("dental persona")


# ─── _cos (cosine similarity) ────────────────────────────────────────


def test_cos_identical_vectors_return_one():
    sc = SemanticCache()
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert abs(sc._cos(v, v) - 1.0) < 1e-5


def test_cos_orthogonal_vectors_return_zero():
    sc = SemanticCache()
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    assert abs(sc._cos(a, b)) < 1e-5


def test_cos_opposite_vectors_return_negative_one():
    sc = SemanticCache()
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([-1.0, 0.0], dtype=np.float32)
    assert abs(sc._cos(a, b) - (-1.0)) < 1e-5


def test_cos_zero_vector_doesnt_div_by_zero():
    """Defensive — embedder could (theoretically) return a zero vec."""
    sc = SemanticCache()
    a = np.array([0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0], dtype=np.float32)
    # Should not raise; result is implementation-defined.
    result = sc._cos(a, b)
    assert isinstance(result, float)
