"""Business-timezone clock.

ALL appointment date/slot logic must use the BUSINESS timezone, not the
server's local clock. Production hosts commonly run UTC; with naive
`date.today()` / `datetime.now()` the agent resolved "today"/"tomorrow"
to the wrong calendar day near the day boundary and filtered same-day
past slots against the wrong wall-clock time (e.g. at 3 PM IST = 09:30
UTC it thought it was 09:30 and offered slots that had already passed,
or hid slots that were still valid).

Default timezone is Asia/Kolkata (IST = UTC+5:30, no DST). For India
deploys this needs NO `tzdata` package — if `zoneinfo` can't load the
named zone we fall back to a FIXED +5:30 offset, which is exactly IST
year-round. A non-IST `APPT_TIMEZONE` that can't be resolved logs a
warning and also falls back to +5:30 (operator should install tzdata).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from src.config import settings

logger = logging.getLogger("clock")

# India Standard Time as a fixed offset — correct all year (no DST).
_IST = timezone(timedelta(hours=5, minutes=30), "IST")
_IST_NAMES = {"asia/kolkata", "asia/calcutta", "ist", "+05:30", "+0530"}

_tz_cache: timezone | None = None


def _tz():
    """Resolve the configured business timezone once (cached)."""
    global _tz_cache
    if _tz_cache is not None:
        return _tz_cache
    name = (settings.appt_timezone or "").strip()
    if not name or name.lower() in _IST_NAMES:
        _tz_cache = _IST
        return _tz_cache
    try:
        from zoneinfo import ZoneInfo

        _tz_cache = ZoneInfo(name)  # type: ignore[assignment]
    except Exception:
        logger.warning(
            "APPT_TIMEZONE=%r could not be loaded (install tzdata?) — "
            "falling back to IST (+5:30)", name,
        )
        _tz_cache = _IST
    return _tz_cache


def now_tz() -> datetime:
    """Current time in the business timezone (tz-aware)."""
    return datetime.now(_tz())


def today_tz() -> date:
    """Current calendar date in the business timezone."""
    return now_tz().date()
