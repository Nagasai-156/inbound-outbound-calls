"""Pure-helper tests for src/db.py — norm_time + resolve_date.

These are the time/date parsers the appointment tools rely on; their
correctness directly affects every booking. No network/DB needed.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.db import norm_time, resolve_date


# ─── norm_time ──────────────────────────────────────────────────────


def test_norm_time_handles_plain_hour():
    assert norm_time("9") in ("09:00", "09:30")  # snaps to grid


def test_norm_time_handles_pm_indicator():
    # English PM
    assert norm_time("5 pm") in ("17:00", "17:30")
    # Telugu evening
    out = norm_time("సాయంత్రం 5")
    assert out is not None and out.startswith("17"), out
    # Hindi evening (no AM/PM word) — should NOT default to PM
    # (this is a known limitation: bare digits default to AM-ish)


def test_norm_time_handles_am_indicator():
    out = norm_time("ఉదయం 10")
    assert out == "10:00", out
    out_en = norm_time("morning 9")
    assert out_en == "09:00", out_en


def test_norm_time_handles_24h_format():
    assert norm_time("17:00") in ("17:00",)
    assert norm_time("14:30") in ("14:30",)


def test_norm_time_returns_none_for_garbage():
    assert norm_time("hmm") is None
    assert norm_time("") is None
    assert norm_time("xyz") is None


def test_norm_time_clamps_out_of_range():
    # Hours outside business window must return None, not garbage.
    assert norm_time("3 am") is None      # before 9 AM open
    assert norm_time("11 pm") is None     # after close


# ─── resolve_date ─────────────────────────────────────────────────


def _today_iso() -> str:
    return date.today().isoformat()


def _tomorrow_iso() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


def _day_after_iso() -> str:
    return (date.today() + timedelta(days=2)).isoformat()


def test_resolve_date_today_words():
    for w in ("today", "ఈరోజు", "ఈ రోజు", "నేడు", "आज", "aaj", "eeroju"):
        assert resolve_date(w) == _today_iso(), f"{w!r} should be today"


def test_resolve_date_tomorrow_words():
    for w in ("tomorrow", "రేపు", "कल", "kal", "repu"):
        assert resolve_date(w) == _tomorrow_iso(), f"{w!r} should be tomorrow"


def test_resolve_date_day_after_words():
    for w in ("day after tomorrow", "ఎల్లుండి", "ellundi", "परसो", "parso"):
        assert resolve_date(w) == _day_after_iso(), f"{w!r} should be day-after"


def test_resolve_date_iso_format_passes_through():
    assert resolve_date("2026-12-25") == "2026-12-25"


def test_resolve_date_garbage_returns_none():
    assert resolve_date("xyz") is None
    assert resolve_date("") is None


def test_resolve_date_handles_embedded_words():
    # LLM occasionally wraps the date word with extra context.
    assert resolve_date("today only please") == _today_iso()
    assert resolve_date("tomorrow morning") == _tomorrow_iso()
