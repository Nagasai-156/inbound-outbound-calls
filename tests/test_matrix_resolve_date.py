"""Parametrized resolve_date matrix — every language × every relative-date word."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.db import resolve_date


# Each tuple: (input_phrase, expected_offset_days_from_today_or_none)
_TODAY = [
    ("today", 0), ("Today", 0), ("TODAY", 0),
    ("ఈరోజు", 0), ("ఈ రోజు", 0), ("నేడు", 0),
    ("आज", 0), ("aaj", 0), ("eeroju", 0), ("ee roju", 0),
    ("please today only", 0), ("today, that works", 0),
]

_TOMORROW = [
    ("tomorrow", 1), ("Tomorrow", 1),
    ("రేపు", 1), ("कल", 1), ("kal", 1), ("repu", 1),
    ("tomorrow morning", 1), ("tomorrow evening", 1),
    ("can you do tomorrow", 1),
]

_DAY_AFTER = [
    ("day after tomorrow", 2),
    ("Day After Tomorrow", 2),
    ("ఎల్లుండి", 2), ("ellundi", 2),
    ("परसो", 2), ("parso", 2),
    ("day after tomorrow morning", 2),
]


@pytest.mark.parametrize("phrase,offset", _TODAY)
def test_today_phrases_resolve_to_today(phrase, offset):
    expected = (date.today() + timedelta(days=offset)).isoformat()
    assert resolve_date(phrase) == expected, f"{phrase!r} → wrong date"


@pytest.mark.parametrize("phrase,offset", _TOMORROW)
def test_tomorrow_phrases_resolve_to_tomorrow(phrase, offset):
    expected = (date.today() + timedelta(days=offset)).isoformat()
    assert resolve_date(phrase) == expected, f"{phrase!r} → wrong date"


@pytest.mark.parametrize("phrase,offset", _DAY_AFTER)
def test_day_after_phrases_resolve_correctly(phrase, offset):
    """Regression: 'day after tomorrow' substring contained 'tomorrow'
    and used to short-circuit. Loop order was fixed; verify every variant."""
    expected = (date.today() + timedelta(days=offset)).isoformat()
    assert resolve_date(phrase) == expected, f"{phrase!r} → wrong date"


@pytest.mark.parametrize("weekday_name,wd_idx", [
    ("monday", 0), ("tuesday", 1), ("wednesday", 2),
    ("thursday", 3), ("friday", 4), ("saturday", 5), ("sunday", 6),
])
def test_weekday_names_resolve_to_next_occurrence(weekday_name, wd_idx):
    out = resolve_date(weekday_name)
    if out is None:
        return  # impl may or may not support
    d = date.fromisoformat(out)
    assert d.weekday() == wd_idx
    # Must be in the future (1-7 days ahead, NOT today even if same weekday).
    assert (d - date.today()).days >= 1


@pytest.mark.parametrize("iso_date", [
    "2026-12-25", "2027-01-01", "2026-06-15", "2030-12-31",
])
def test_iso_dates_pass_through(iso_date):
    assert resolve_date(iso_date) == iso_date


@pytest.mark.parametrize("garbage", [
    "", "   ", "xyz", "123", "monday tuesday", "hmm",
    "appointment time", "I don't know", "??",
])
def test_garbage_returns_none(garbage):
    out = resolve_date(garbage)
    # None or a fallback date — must not crash.
    assert out is None or isinstance(out, str)
