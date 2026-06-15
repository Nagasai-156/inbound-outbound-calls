"""Business-timezone clock tests.

Pins the IST (+5:30) default so appointment date/slot logic never uses
the server's local clock (the UTC-host day-boundary bug).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src import clock


def test_now_tz_is_timezone_aware():
    now = clock.now_tz()
    assert now.tzinfo is not None


def test_default_offset_is_ist_530():
    now = clock.now_tz()
    off = now.utcoffset()
    assert off == timedelta(hours=5, minutes=30)


def test_now_tz_matches_utc_plus_530():
    # now_tz() should equal current UTC + 5:30 (within a small skew).
    utc = datetime.now(timezone.utc)
    ist = clock.now_tz()
    # Compare the wall-clock instants: both are aware, so subtraction is
    # offset-correct; difference should be ~0 (not 5.5h).
    assert abs((ist - utc).total_seconds()) < 5


def test_today_tz_returns_a_date():
    from datetime import date

    assert isinstance(clock.today_tz(), date)


def test_today_tz_is_ist_calendar_date():
    # At the UTC/IST boundary the IST date can be one day AHEAD of UTC.
    utc_today = datetime.now(timezone.utc).date()
    ist_today = clock.today_tz()
    assert ist_today in (utc_today, utc_today + timedelta(days=1))
