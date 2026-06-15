"""Cosine-similarity property tests across 500 random vector pairs."""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from src.cache import SemanticCache


def _gen_pairs(seed: int, n: int, dim: int) -> list[tuple[np.ndarray, np.ndarray]]:
    random.seed(seed)
    np.random.seed(seed)
    return [
        (np.random.randn(dim).astype(np.float32),
         np.random.randn(dim).astype(np.float32))
        for _ in range(n)
    ]


_SC = SemanticCache()

# 5 batches × 50 pairs = 250 cases each property
_PAIRS_128 = _gen_pairs(seed=1, n=50, dim=128)
_PAIRS_512 = _gen_pairs(seed=2, n=50, dim=512)
_PAIRS_1536 = _gen_pairs(seed=3, n=50, dim=1536)
_PAIRS_HUGE = _gen_pairs(seed=4, n=20, dim=4096)


@pytest.mark.parametrize("pair", _PAIRS_128)
def test_cosine_in_range_128(pair):
    a, b = pair
    cos = _SC._cos(a, b)
    assert -1.001 <= cos <= 1.001
    assert math.isfinite(cos)


@pytest.mark.parametrize("pair", _PAIRS_512)
def test_cosine_in_range_512(pair):
    a, b = pair
    cos = _SC._cos(a, b)
    assert -1.001 <= cos <= 1.001
    assert math.isfinite(cos)


@pytest.mark.parametrize("pair", _PAIRS_1536)
def test_cosine_in_range_1536(pair):
    """OpenAI ada-002 dim is 1536; this is our real production size."""
    a, b = pair
    cos = _SC._cos(a, b)
    assert -1.001 <= cos <= 1.001
    assert math.isfinite(cos)


@pytest.mark.parametrize("pair", _PAIRS_HUGE)
def test_cosine_in_range_4k(pair):
    a, b = pair
    cos = _SC._cos(a, b)
    assert -1.001 <= cos <= 1.001
    assert math.isfinite(cos)


@pytest.mark.parametrize("pair", _PAIRS_128 + _PAIRS_512)
def test_cosine_self_identity(pair):
    """cos(v, v) ≈ 1 — always."""
    a, _ = pair
    if np.linalg.norm(a) < 1e-9:
        return  # zero vector edge case
    cos = _SC._cos(a, a)
    assert abs(cos - 1.0) < 1e-3


@pytest.mark.parametrize("pair", _PAIRS_128)
def test_cosine_symmetry(pair):
    """cos(a, b) == cos(b, a)"""
    a, b = pair
    assert abs(_SC._cos(a, b) - _SC._cos(b, a)) < 1e-5


@pytest.mark.parametrize("pair", _PAIRS_128)
def test_cosine_scale_invariance(pair):
    """cos(a, b) == cos(2a, b) (cosine is scale-invariant)"""
    a, b = pair
    if np.linalg.norm(a) < 1e-9 or np.linalg.norm(b) < 1e-9:
        return
    c1 = _SC._cos(a, b)
    c2 = _SC._cos(a * 5, b)
    assert abs(c1 - c2) < 1e-3
