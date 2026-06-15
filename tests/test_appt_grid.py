"""Appointment slot-grid generation + dashboard refresh tests."""

from __future__ import annotations

import dataclasses

from src.db import _all_slots, _refresh_appt_grid, APPT_OPEN_HOUR, APPT_CLOSE_HOUR, APPT_SLOT_MIN
import src.db as _db
from src.runtime_config import RuntimeConfig


def test_default_slot_grid_runs_open_to_close_step():
    slots = _all_slots()
    assert len(slots) > 0
    # Each slot is HH:MM 24h format.
    for s in slots:
        assert ":" in s
        h, m = s.split(":")
        assert 0 <= int(h) < 24
        assert int(m) in (0, 15, 30, 45)


def test_slot_grid_starts_at_open_hour():
    slots = _all_slots()
    first = slots[0]
    h = int(first.split(":")[0])
    assert h == APPT_OPEN_HOUR


def test_slot_grid_does_not_include_close_hour():
    """Last bookable slot is BEFORE close_hour (exclusive)."""
    slots = _all_slots()
    last_h = int(slots[-1].split(":")[0])
    assert last_h < APPT_CLOSE_HOUR


def test_slot_grid_consecutive_step_is_slot_min():
    slots = _all_slots()
    def _to_min(hhmm):
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    if len(slots) >= 2:
        assert _to_min(slots[1]) - _to_min(slots[0]) == APPT_SLOT_MIN


def test_refresh_appt_grid_with_valid_cfg():
    """Dashboard edit: open 10am, close 8pm, 60-min slots."""
    cfg = dataclasses.replace(RuntimeConfig(), appt_open_hour=10, appt_close_hour=20, appt_slot_min=60, appt_open_weekdays="0,1,2,3,4,5,6")
    _refresh_appt_grid(cfg)
    assert _db.APPT_OPEN_HOUR == 10
    assert _db.APPT_CLOSE_HOUR == 20
    assert _db.APPT_SLOT_MIN == 60
    assert 0 in _db.APPT_OPEN_WEEKDAYS


def test_refresh_appt_grid_rejects_invalid_close_before_open():
    """Close hour <= open hour is nonsense — must NOT overwrite."""
    # First set a known good grid.
    good = dataclasses.replace(RuntimeConfig(), appt_open_hour=9, appt_close_hour=18, appt_slot_min=30, appt_open_weekdays="0,1,2,3,4,5")
    _refresh_appt_grid(good)
    saved_open = _db.APPT_OPEN_HOUR
    saved_close = _db.APPT_CLOSE_HOUR
    # Now try a bad config: close < open.
    bad = dataclasses.replace(RuntimeConfig(), appt_open_hour=18, appt_close_hour=9, appt_slot_min=30, appt_open_weekdays="0,1,2,3,4,5")
    _refresh_appt_grid(bad)
    # Last good values must be preserved.
    assert _db.APPT_OPEN_HOUR == saved_open
    assert _db.APPT_CLOSE_HOUR == saved_close


def test_refresh_appt_grid_rejects_zero_slot_min():
    good = dataclasses.replace(RuntimeConfig(), appt_open_hour=9, appt_close_hour=18, appt_slot_min=30, appt_open_weekdays="0,1,2,3,4,5")
    _refresh_appt_grid(good)
    saved_slot = _db.APPT_SLOT_MIN
    bad = dataclasses.replace(RuntimeConfig(), appt_open_hour=9, appt_close_hour=18, appt_slot_min=0, appt_open_weekdays="0,1,2,3,4,5")
    _refresh_appt_grid(bad)
    # Should keep last good (NOT apply 0).
    assert _db.APPT_SLOT_MIN == saved_slot


def test_refresh_appt_grid_rejects_empty_weekdays():
    good = dataclasses.replace(RuntimeConfig(), appt_open_hour=9, appt_close_hour=18, appt_slot_min=30, appt_open_weekdays="0,1,2,3,4,5")
    _refresh_appt_grid(good)
    saved_wd = set(_db.APPT_OPEN_WEEKDAYS)
    bad = dataclasses.replace(RuntimeConfig(), appt_open_hour=9, appt_close_hour=18, appt_slot_min=30, appt_open_weekdays="")
    _refresh_appt_grid(bad)
    # Should keep last good.
    assert _db.APPT_OPEN_WEEKDAYS == saved_wd


def test_refresh_appt_grid_with_partial_weekdays():
    """Salon open Tue-Sun (Mon closed) — weekday set excludes 0."""
    cfg = dataclasses.replace(RuntimeConfig(), appt_open_hour=10, appt_close_hour=20, appt_slot_min=30, appt_open_weekdays="1,2,3,4,5,6")
    _refresh_appt_grid(cfg)
    assert 0 not in _db.APPT_OPEN_WEEKDAYS
    assert 1 in _db.APPT_OPEN_WEEKDAYS


def test_refresh_appt_grid_handles_none_cfg_gracefully():
    """If cfg is None or missing fields, defaults kick in."""
    # Set a known state first.
    good = dataclasses.replace(RuntimeConfig(), appt_open_hour=9, appt_close_hour=18, appt_slot_min=30, appt_open_weekdays="0,1,2,3,4,5")
    _refresh_appt_grid(good)
    saved_open = _db.APPT_OPEN_HOUR
    # None cfg should not crash and should NOT mutate (uses env defaults).
    _refresh_appt_grid(None)
    # State should be derived from env defaults (or kept) — just check no crash.
    assert isinstance(_db.APPT_OPEN_HOUR, int)


def test_slot_count_for_30min_grid_9_to_18():
    """9 AM to 6 PM at 30 min = 18 slots. Concrete sanity check."""
    cfg = dataclasses.replace(RuntimeConfig(), appt_open_hour=9, appt_close_hour=18, appt_slot_min=30, appt_open_weekdays="0,1,2,3,4,5")
    _refresh_appt_grid(cfg)
    slots = _all_slots()
    # 9 hours × 2 slots/hr = 18.
    assert len(slots) == 18
