"""Admin notifications via Telegram.

Fire-and-forget messages to the clinic admin's Telegram chat on every
booking-state change (book / reschedule / cancel / cancel-all).

Design contract:
  - The bookings DB write is the source of truth. Notification is BEST
    EFFORT, AFTER the row is persisted. A Telegram outage MUST NOT
    affect, delay, or roll back a successful booking.
  - All errors swallowed and logged at WARNING, never raised.
  - When TELEGRAM_BOT_TOKEN or TELEGRAM_ADMIN_CHAT_ID is empty (default),
    every function is a silent no-op — safe to deploy without creds and
    flip on later via .env update + worker restart.
  - 3-second timeout on the HTTP call so a slow/down Telegram never
    bottlenecks a live call's pipeline.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import Any

import httpx

from src.config import settings

logger = logging.getLogger("notify")

_TG_API = "https://api.telegram.org"
_HTTP_TIMEOUT = 3.0  # seconds — hard cap so a slow Telegram never blocks
_shared_client: httpx.AsyncClient | None = None
# Strong refs to in-flight fire-and-forget notify tasks (asyncio only
# keeps weak refs; without this a pending alert can be GC'd mid-flight).
_inflight: set[asyncio.Task] = set()


def _client() -> httpx.AsyncClient | None:
    """Lazy process-wide httpx client (keepalive + HTTP/2) for Telegram.
    Returns None if Telegram is not configured (silent no-op path)."""
    global _shared_client
    if not settings.telegram_bot_token or not settings.telegram_admin_chat_id:
        return None
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(
            http2=False,  # api.telegram.org is HTTP/1.1
            timeout=httpx.Timeout(_HTTP_TIMEOUT),
            limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=120),
        )
    return _shared_client


async def _send(text: str) -> None:
    """Internal: POST to Telegram sendMessage. Never raises."""
    client = _client()
    if client is None:
        return  # not configured
    url = f"{_TG_API}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_admin_chat_id,
        "text": text,
        "parse_mode": "HTML",
        # voice-grade: don't trigger sound on phones for these alerts
        "disable_notification": False,
        # link previews would expand any URL in messages — keeps the
        # alert compact for admins glancing at notifications
        "disable_web_page_preview": True,
    }
    try:
        r = await client.post(url, json=payload)
        if r.status_code != 200:
            logger.warning(
                "telegram notify failed status=%s body=%s",
                r.status_code, r.text[:200],
            )
    except Exception as e:
        # Network blip / DNS / SSL / timeout — never let it surface
        logger.warning("telegram notify failed: %s", type(e).__name__)


def _h(v: Any) -> str:
    """HTML-escape a value for safe insertion into Telegram HTML markup.
    Telegram HTML supports <b><i><code><pre><a> only; user data could
    contain <, >, & that need escaping or the message API rejects."""
    if v is None or v == "":
        return "—"
    return html.escape(str(v))


def _now_ist() -> str:
    """IST timestamp for the alert footer. Avoids timezone library
    dependency by using a fixed +5:30 offset (India never has DST)."""
    return time.strftime("%Y-%m-%d %H:%M IST", time.gmtime(time.time() + 19800))


# ─── Public notification helpers ───────────────────────────────────
# Each wraps `_send()` in a fire-and-forget task scheduled on the running
# event loop — booking code awaits NOTHING here. The notification's
# success/failure is independent of the booking's success.

def _fire(coro) -> None:
    """Schedule a coroutine on the current event loop without awaiting.
    If we're outside an event loop (sync caller), run it briefly via a
    new loop — but that's not the expected path (db.* are async)."""
    try:
        loop = asyncio.get_running_loop()
        # Retain a strong reference until done: asyncio only holds a WEAK
        # reference to bare tasks, so a pending notification could be
        # garbage-collected before it runs ("Task was destroyed but it is
        # pending"). Track + discard-on-done keeps it alive.
        t = loop.create_task(coro)
        _inflight.add(t)
        t.add_done_callback(_inflight.discard)
    except RuntimeError:
        # No running loop — last-resort fallback (rare in our hot path)
        try:
            asyncio.run(coro)
        except Exception:
            logger.debug("notify sync fallback failed", exc_info=True)


def notify_booking(
    *, date: str, time_str: str, name: str = "", phone: str = "",
    reason: str = "", party_size: int = 0, service_type: str = "",
    notes: str = "", source: str = "", room: str = "",
) -> None:
    """Fire admin alert for a NEW booking. Called by db.appt_book on
    successful INSERT."""
    extras = []
    if service_type:
        extras.append(f"💼 <b>Service:</b> {_h(service_type)}")
    if party_size and party_size > 0:
        extras.append(f"👥 <b>Party size:</b> {party_size}")
    if notes:
        extras.append(f"📝 <b>Notes:</b> {_h(notes)}")
    extra_lines = ("\n" + "\n".join(extras)) if extras else ""
    src_tag = f"{_h(source)}" + (f" (<code>{_h(room)}</code>)" if room else "")
    text = (
        "🆕 <b>New Appointment Booked</b>\n\n"
        f"👤 <b>Name:</b> {_h(name)}\n"
        f"📞 <b>Phone:</b> <code>{_h(phone)}</code>\n"
        f"📅 <b>Date:</b> {_h(date)}\n"
        f"⏰ <b>Time:</b> {_h(time_str)}\n"
        f"🩺 <b>Reason:</b> {_h(reason)}"
        f"{extra_lines}\n"
        f"🏥 <b>Source:</b> {src_tag}\n"
        f"🕒 <b>Booked:</b> {_now_ist()}"
    )
    _fire(_send(text))


def notify_reschedule(
    *, old_date: str, old_time: str, new_date: str, new_time: str,
    name: str = "", phone: str = "", reason: str = "",
) -> None:
    """Fire admin alert for a reschedule. Called by db.appt_reschedule
    after the atomic cancel-old + book-new completes."""
    text = (
        "🔄 <b>Appointment Rescheduled</b>\n\n"
        f"👤 <b>Name:</b> {_h(name)}\n"
        f"📞 <b>Phone:</b> <code>{_h(phone)}</code>\n"
        f"📅 <b>From:</b> {_h(old_date)} {_h(old_time)}\n"
        f"📅 <b>To:</b>   {_h(new_date)} {_h(new_time)}\n"
        f"🩺 <b>Reason:</b> {_h(reason)}\n"
        f"🕒 <b>Rescheduled:</b> {_now_ist()}"
    )
    _fire(_send(text))


def notify_cancel(
    *, date: str, time_str: str, name: str = "", phone: str = "",
    reason: str = "", appt_id: str = "",
) -> None:
    """Fire admin alert for a single cancellation."""
    text = (
        "❌ <b>Appointment Cancelled</b>\n\n"
        f"👤 <b>Name:</b> {_h(name)}\n"
        f"📞 <b>Phone:</b> <code>{_h(phone)}</code>\n"
        f"📅 <b>Date:</b> {_h(date)}\n"
        f"⏰ <b>Time:</b> {_h(time_str)}\n"
        f"🩺 <b>Reason:</b> {_h(reason)}\n"
        f"🕒 <b>Cancelled:</b> {_now_ist()}"
    )
    _fire(_send(text))


def notify_cancel_all(*, phone: str = "", count: int = 0) -> None:
    """Fire admin alert when a caller cancelled ALL their upcoming
    bookings in one action (cancel_all_appointments)."""
    text = (
        "❌ <b>ALL Appointments Cancelled</b>\n\n"
        f"📞 <b>Phone:</b> <code>{_h(phone)}</code>\n"
        f"🔢 <b>Count:</b> {count} booking(s) cancelled\n"
        f"🕒 <b>At:</b> {_now_ist()}"
    )
    _fire(_send(text))


async def test_ping() -> dict:
    """Sync test helper: send a one-shot test message. Returns a dict
    with status + error if any. Used by `scripts/test_telegram.py`
    or any quick CLI check after wiring credentials."""
    if not settings.telegram_bot_token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
    if not settings.telegram_admin_chat_id:
        return {"ok": False, "error": "TELEGRAM_ADMIN_CHAT_ID not set"}
    try:
        await _send(
            "✅ <b>Diigoo Voice Console — Telegram alerts wired</b>\n\n"
            "You will receive notifications for:\n"
            "  • New bookings 🆕\n"
            "  • Reschedules 🔄\n"
            "  • Cancellations ❌\n\n"
            f"🕒 {_now_ist()}"
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
