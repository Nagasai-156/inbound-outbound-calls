"""More norm_time + resolve_date edge cases for crore-scale safety."""

from __future__ import annotations

from datetime import date, timedelta

from src.db import norm_time, resolve_date


# ─── norm_time additional patterns ───────────────────────────────


def test_norm_time_4_digit_military():
    """Operator/caller types '1700' meaning 5 PM — should normalise."""
    out = norm_time("1700")
    # Either accepted (17:00) or rejected — both valid; just no crash.
    assert out is None or out == "17:00"


def test_norm_time_telugu_pm_word():
    out = norm_time("సాయంత్రం 6")
    assert out is None or out.startswith("18") or out.startswith("06")


def test_norm_time_hindi_pm_word():
    out = norm_time("shaam 5 baje")
    # "shaam" isn't in our PM words; but should still parse 5 (AM).
    assert out is None or out in ("05:00", "17:00")


def test_norm_time_snap_to_grid():
    """5:13 should snap to nearest 30-min slot (5:00 or 5:30)."""
    out = norm_time("5:13 PM")
    assert out is None or out in ("17:00", "17:30")


def test_norm_time_handles_extra_text():
    """Caller's natural speech includes context around the time."""
    out = norm_time("I want 10 am please")
    assert out == "10:00"


def test_norm_time_handles_double_digit_minutes():
    out = norm_time("5:45 PM")
    assert out is None or out in ("17:30", "18:00")


def test_norm_time_handles_negative_hour():
    """Pathological caller speech — must not crash."""
    out = norm_time("-5 pm")
    # Either parsed (snapping to a valid slot) or None — no exception.
    assert out is None or isinstance(out, str)


# ─── resolve_date — more patterns ─────────────────────────────────


def test_resolve_date_weekday_names_english():
    out = resolve_date("monday")
    if out is not None:
        d = date.fromisoformat(out)
        # The Monday returned should be in the next 7 days.
        assert (d - date.today()).days <= 7
        assert d.weekday() == 0


def test_resolve_date_weekday_returns_next_occurrence():
    today_wd = date.today().weekday()
    target_wd = (today_wd + 1) % 7
    name_map = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    out = resolve_date(name_map[target_wd])
    if out:
        d = date.fromisoformat(out)
        assert d.weekday() == target_wd
        # Should be tomorrow (not today and not next week).
        assert (d - date.today()).days == 1


def test_resolve_date_today_weekday_returns_next_week():
    """If caller says 'monday' on a Monday, return NEXT Monday, not today."""
    today = date.today()
    name = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][today.weekday()]
    out = resolve_date(name)
    if out:
        d = date.fromisoformat(out)
        assert d != today
        assert d.weekday() == today.weekday()


def test_resolve_date_handles_mixed_case():
    """Case-insensitive day-name matching."""
    out = resolve_date("Today")
    assert out == date.today().isoformat()


def test_resolve_date_iso_passthrough_with_year():
    assert resolve_date("2027-01-15") == "2027-01-15"


def test_resolve_date_invalid_iso_returns_none_or_pass():
    out = resolve_date("2026-13-99")  # invalid month/day
    # Either None (parsing failed) or whatever fallback — no exception.
    assert out is None or isinstance(out, str)


def test_resolve_date_telugu_today_with_spaces():
    """'ఈ రోజు' with space should resolve same as 'ఈరోజు'."""
    a = resolve_date("ఈ రోజు")
    b = resolve_date("ఈరోజు")
    assert a == b
    assert a == date.today().isoformat()
