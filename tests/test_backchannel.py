"""Tests for real-time backchanneling decision logic.

Covers the gating that keeps acks human (occasional, one-per-utterance,
long-utterance-only, cooldown-spaced) and the anti-repeat phrase picker.
"""

from __future__ import annotations

import pytest

from src import backchannel
from src.backchannel import Backchanneler, pick_backchannel


@pytest.fixture(autouse=True)
def _thresholds(monkeypatch):
    """Pin deterministic thresholds regardless of .env."""
    monkeypatch.setattr(backchannel.settings, "backchannel_min_words", 8)
    monkeypatch.setattr(backchannel.settings, "backchannel_min_seconds", 2.0)
    monkeypatch.setattr(
        backchannel.settings, "backchannel_cooldown_seconds", 6.0
    )


_LONG = "i want to book an appointment for my father next week sometime"


def test_short_utterance_never_acks():
    bc = Backchanneler()
    # 3 words, well past min_seconds — still too short to deserve an ack.
    assert bc.should_ack("book an appointment", now=100.0) is False


def test_long_utterance_acks_once_after_min_seconds():
    bc = Backchanneler()
    # Utterance starts at t=100; min_seconds=2 not yet elapsed.
    assert bc.should_ack(_LONG, now=100.0) is False
    # 2.5s later -> long enough + enough words -> fires once.
    assert bc.should_ack(_LONG, now=102.5) is True
    # Same utterance, must NOT fire again.
    assert bc.should_ack(_LONG + " around evening", now=103.5) is False


def test_cooldown_blocks_next_utterance_when_too_soon():
    bc = Backchanneler()
    bc.should_ack(_LONG, now=100.0)
    assert bc.should_ack(_LONG, now=102.5) is True  # first ack at 102.5
    bc.reset_utterance()
    # New utterance starts at 104; even though it's long and >2s by 106.5,
    # only 4s since the last ack (<6s cooldown) -> suppressed.
    assert bc.should_ack(_LONG, now=104.0) is False
    assert bc.should_ack(_LONG, now=106.5) is False


def test_cooldown_allows_next_utterance_after_window():
    bc = Backchanneler()
    bc.should_ack(_LONG, now=100.0)
    assert bc.should_ack(_LONG, now=102.5) is True
    bc.reset_utterance()
    # New utterance well after the cooldown -> fires again.
    assert bc.should_ack(_LONG, now=120.0) is False  # min_seconds not met
    assert bc.should_ack(_LONG, now=122.5) is True


def test_pick_backchannel_language_and_anti_repeat():
    # Telugu pool, never the same phrase twice in a row.
    prev = None
    for _ in range(20):
        p = pick_backchannel("te")
        assert p in backchannel._POOLS["te"]
        assert p != prev
        prev = p


def test_pick_backchannel_lang_fallback():
    assert pick_backchannel("fr") in backchannel._POOLS["en"]
    assert pick_backchannel(None) in backchannel._POOLS["en"]
    assert pick_backchannel("te-mix") in backchannel._POOLS["te"]
    assert pick_backchannel("hi") in backchannel._POOLS["hi"]
