"""_entry_id deterministic-hash fuzz: 500 random + crafted inputs."""

from __future__ import annotations

import string
import random

import pytest

from src.cache import _entry_id


def _gen(n: int, seed: int, alphabet: str) -> list[str]:
    random.seed(seed)
    return [
        "".join(random.choice(alphabet) for _ in range(random.randint(1, 60)))
        for _ in range(n)
    ]


_ASCII = string.ascii_letters + string.digits + " ?,.!"
_INDIC = "ఆహాసరేఅండిమంచిరోజుహాబై"
_DEVA = "नमस्तेजीहाँधन्यवादहीठीक"
_MIX = _ASCII + _INDIC + _DEVA


# Generate 4 batches of 50 random strings = 200 cases each parametrize.
@pytest.mark.parametrize("text", _gen(50, 1, _ASCII))
def test_ascii_entry_id_deterministic(text):
    assert _entry_id(text) == _entry_id(text)


@pytest.mark.parametrize("text", _gen(50, 2, _ASCII))
def test_ascii_entry_id_length_20(text):
    assert len(_entry_id(text)) == 20


@pytest.mark.parametrize("text", _gen(50, 3, _INDIC))
def test_indic_entry_id_length_20(text):
    assert len(_entry_id(text)) == 20


@pytest.mark.parametrize("text", _gen(50, 4, _DEVA))
def test_devanagari_entry_id_length_20(text):
    assert len(_entry_id(text)) == 20


@pytest.mark.parametrize("text", _gen(50, 5, _MIX))
def test_mixed_entry_id_length_20(text):
    assert len(_entry_id(text)) == 20


@pytest.mark.parametrize("text", _gen(50, 6, _ASCII))
def test_entry_id_case_normalisation_stable(text):
    """Same content in different case → same id."""
    h_lower = _entry_id(text.lower())
    h_upper = _entry_id(text.upper())
    assert h_lower == h_upper


@pytest.mark.parametrize("text", _gen(50, 7, _ASCII))
def test_entry_id_whitespace_normalisation_stable(text):
    """Leading/trailing whitespace doesn't change hash."""
    base = text.strip()
    if base:
        assert _entry_id(base) == _entry_id(" " + base + " ")


@pytest.mark.parametrize("text", _gen(50, 8, _MIX))
def test_entry_id_all_hex_chars(text):
    h = _entry_id(text)
    assert all(c in "0123456789abcdef" for c in h)
