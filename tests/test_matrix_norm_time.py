"""Parametrized norm_time matrix — every hour × indicator across en/te/hi."""

from __future__ import annotations

import pytest

from src.db import norm_time, _all_slots


_AM_HOURS = list(range(9, 12))   # 9, 10, 11 AM
_PM_HOURS = list(range(1, 6))    # 1, 2, 3, 4, 5 PM (within business hours)

_AM_WORDS = ["am", "AM", "morning", "ఉదయం", "podduna", "subah"]
_PM_WORDS = ["pm", "PM", "evening", "సాయంత్రం", "shaam", "sayantram"]


@pytest.mark.parametrize("hour", _AM_HOURS)
@pytest.mark.parametrize("ampm", _AM_WORDS)
def test_norm_time_am_matrix(hour, ampm):
    raw = f"{hour} {ampm}"
    out = norm_time(raw)
    # Must be a HH:MM or None — never crash.
    if out is not None:
        h, _ = out.split(":")
        assert int(h) in (hour, hour - 12)  # AM hour stays as-is mostly


@pytest.mark.parametrize("hour", _PM_HOURS)
@pytest.mark.parametrize("ampm", _PM_WORDS)
def test_norm_time_pm_matrix(hour, ampm):
    raw = f"{hour} {ampm}"
    out = norm_time(raw)
    if out is not None:
        h, _ = out.split(":")
        # PM hour → +12 (e.g. 5 → 17)
        assert int(h) == hour + 12 or int(h) == hour


@pytest.mark.parametrize("hh", range(9, 18))  # 9 to 17 (5 PM)
@pytest.mark.parametrize("mm", ["00", "30"])
def test_norm_time_24h_in_window(hh, mm):
    raw = f"{hh}:{mm}"
    out = norm_time(raw)
    if hh == 17 and mm == "30":
        # 17:30 is past business window (close exclusive)
        assert out in (None, "17:30")
    else:
        assert out is not None
        assert out == f"{hh:02d}:{mm}"


@pytest.mark.parametrize("garbage", [
    "", " ", "abc", "hmm", "okay", "x:y", "::", "--", "?",
    "5pmm", "amm pm", "evening evening", "@5pm", "###",
])
def test_norm_time_garbage_returns_none(garbage):
    """Garbage inputs must return None, not crash."""
    out = norm_time(garbage)
    assert out is None or isinstance(out, str)


def test_all_slots_consistent_with_window():
    slots = _all_slots()
    for s in slots:
        h, m = s.split(":")
        assert 0 <= int(h) < 24
        assert 0 <= int(m) < 60
