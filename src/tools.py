"""LLM function tools.

`kb_search` (grounded answers), the appointment tools (real Supabase),
and `order_status`. order_status NEVER fabricates a status — if no real
order backend is configured it honestly defers to a human callback.
Tools are deliberately few and fast; the persona keeps their output
short and spoken.
"""

from __future__ import annotations

import functools
import logging
import time

from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Optional

from livekit.agents import RunContext, function_tool

from src.kb import kb_context


def _period(hh: int) -> str:
    """Deterministic clock-hour -> spoken period word. Computed in code so
    the model NEVER has to derive AM/PM->period itself — that derivation is
    what produced the live "4:00 PM read back as 'ఉదయం నాలుగు' (morning 4)"
    loop (call out-976d2cbb18, reproduced 8/8 on 2026-06-15). Language-
    agnostic: the English period word anchors the model, which still speaks
    it in the caller's language (సాయంత్రం / शाम / evening)."""
    if 5 <= hh < 12:
        return "morning"
    if 12 <= hh < 16:
        return "afternoon"
    return "evening"  # 16:00-18:00 booking window (and any later slot)


def ampm12(t: str) -> str:
    """'15:00' -> '3:00 PM (afternoon)'. The LLM misread raw 24-hour strings
    on live calls (snapshot '15:00' spoken as Telugu 'ఉదయం మూడు' = 3 AM,
    call out-27691b1ea2; '16:00' spoken as 'ఉదయం నాలుగు' = morning 4,
    call out-976d2cbb18). So every time shown to the model is now an
    unambiguous 12-hour AM/PM string WITH its spoken period attached —
    computed here, never left to the model to derive (the "dynamic", not
    prompt-obedient, fix)."""
    try:
        hh, mm = (int(x) for x in str(t).strip().split(":")[:2])
    except Exception:
        return str(t)
    suffix = "AM" if hh < 12 else "PM"
    return f"{hh % 12 or 12}:{mm:02d} {suffix} ({_period(hh)})"


def ampm12_list(ts) -> str:
    return ", ".join(ampm12(t) for t in ts)

logger = logging.getLogger("tools")


def _instrument(name: str):
    """Wraps a tool function so EVERY invocation logs:
      tool=<name> status=ok|error elapsed_ms=<n> args=<...> result=<snippet>
    Pure observability — no behavior change. Two captures, both off the
    streaming hot path:
      * args  — the LLM-supplied tool arguments (the date/time the model
        PARSED). This is the booking-loop smoking gun: if the caller said
        "9 AM" but the model passed time="4 PM", that mis-parse is now
        visible WITHOUT a synthetic repro (which never reproduced it). And
        if a booking turn produced NO tool line at all, the model skipped
        the tool — equally diagnostic.
      * result (truncated) — what the table returned (free slots / "morning
        booked"), the other half of the booking decision.
    The original timing signature (slow DB? tool never fired?) is kept."""
    def deco(fn):
        @functools.wraps(fn)
        async def inner(context: "RunContext", *args, **kwargs):
            t0 = time.monotonic()
            # context arrives positionally, so kwargs holds exactly the
            # model-supplied named arguments. Cheap dict copy; small payloads.
            _call_args = {k: v for k, v in kwargs.items() if k != "context"}
            try:
                out = await fn(context, *args, **kwargs)
                ms = (time.monotonic() - t0) * 1000
                logger.info(
                    "tool=%s status=ok elapsed_ms=%.0f args=%s "
                    "result_chars=%d result=%.200s",
                    name, ms, _call_args,
                    len(out) if isinstance(out, str) else 0,
                    out if isinstance(out, str) else "",
                )
                return out
            except Exception as e:
                ms = (time.monotonic() - t0) * 1000
                logger.warning(
                    "tool=%s status=ERROR elapsed_ms=%.0f args=%s err=%s",
                    name, ms, _call_args, type(e).__name__, exc_info=True,
                )
                raise
        return inner
    return deco

# Set per-call by agent.entrypoint. Tools read these so a call booking
# has the caller's number and the agent can actually hang up.
caller_phone_var: ContextVar[str] = ContextVar("caller_phone", default="")
kb_id_var: ContextVar[str] = ContextVar("kb_id", default="")
end_call_var: ContextVar[Optional[Callable[[], Awaitable[None]]]] = (
    ContextVar("end_call_cb", default=None)
)
# Optional REAL order backend: a deployment that has an order system
# injects an async (order_id) -> status-string callable here. Default
# None -> order_status honestly defers instead of fabricating.
_order_backend_var: ContextVar[
    Optional[Callable[[str], Awaitable[str]]]
] = ContextVar("order_backend", default=None)

# Set by VoiceAgent so booking tools can invalidate its per-turn live
# table snapshot the moment a write happens (so the very next turn sees
# truly fresh data — no waiting for the 6s TTL).
appt_snapshot_invalidate_var: ContextVar[
    Optional[Callable[[], None]]
] = ContextVar("appt_snapshot_invalidate", default=None)


@function_tool()
@_instrument("kb_search")
async def kb_search(context: RunContext, query: str) -> str:
    """Look up company knowledge (policies, FAQs, refund/payment/delivery
    rules) to answer the caller. Use ONLY when you don't already know.

    Args:
        query: The caller's question, in their own words.
    """
    # RETRIEVAL ONLY (no second LLM): the main streaming LLM that called
    # this tool is already running — it synthesizes the spoken answer
    # from these chunks. This removes a full blocking synthesis round-
    # trip (was 2.5-6s of dead air) from every KB question.
    ctx = await kb_context(query, kb_id=kb_id_var.get())
    if ctx:
        return (
            "Answer the caller using ONLY these company facts. One or two "
            "short spoken sentences in the caller's language. Do NOT quote "
            "or read the text, do NOT say 'according to', do NOT add "
            "anything that is not stated here:\n\n" + ctx
        )
    return (
        "No specific information found. Tell the caller briefly you'll "
        "check and follow up; do not invent details."
    )


@function_tool()
@_instrument("order_status")
async def order_status(context: RunContext, order_id: str) -> str:
    """Get the current status of an order by its id.

    Args:
        order_id: The order/booking id the caller provides.
    """
    oid = (order_id or "").strip()
    if not oid:
        return "Ask the caller for their order id, briefly."
    # No real order backend is wired. Do NOT fabricate a status/date —
    # honestly take the detail and promise a human follow-up.
    backend = _order_backend_var.get()
    if backend is None:
        logger.info("order_status: no backend configured for %s", oid)
        return (
            f"You cannot look up order {oid} live. Tell the caller, in "
            "one short sentence, that you've noted the order id and the "
            "team will check and call back — do NOT invent a status, "
            "date, or any detail."
        )
    try:
        real = await backend(oid)
        return (
            "Tell the caller this order status in one short spoken "
            f"sentence, nothing extra: {real}"
        )
    except Exception:
        logger.debug("order_status backend failed", exc_info=True)
        return (
            f"Order {oid} status couldn't be fetched right now. Tell the "
            "caller you'll check and follow up — do NOT invent details."
        )


@function_tool()
@_instrument("check_appointment_slots")
async def check_appointment_slots(context: RunContext, date: str) -> str:
    """Get the FREE appointment time-slots for a date. ALWAYS call this
    before telling the caller any availability — never guess slots.

    Args:
        date: The day the caller wants — 'today', 'tomorrow', a weekday
            like 'Monday', or 'YYYY-MM-DD'.
    """
    from src import db

    d = db.resolve_date(date)
    if not d:
        return (
            "Couldn't understand the date. Ask the caller for a clear "
            "day (e.g. tomorrow, Monday, or a date)."
        )
    free = await db.appt_available_slots(d)
    all_slots = db._all_slots()
    total = len(all_slots)
    # Authoritative close + last-slot strings: pulled from settings so
    # the tool wording can NEVER drift from `_hours_facts()` in the
    # persona prompt. The previous wording "they close after {free[-1]}"
    # conflated last-slot-start with close-time and the LLM started
    # rejecting in-window times as "after close" — fixed here.
    # Read from db module — refreshed per-call from the active AgentConfig
    # so the tool's wording uses THIS business's hours, not env defaults.
    last_h, last_m = divmod(db.APPT_CLOSE_HOUR * 60 - db.APPT_SLOT_MIN, 60)
    last_hhmm = f"{last_h:02d}:{last_m:02d}"
    close_hhmm = f"{db.APPT_CLOSE_HOUR:02d}:00"
    if not free:
        return (
            f"TABLE-FRESH DATA for {d}: closed that day or fully booked. "
            "Offer the caller another day."
        )
    # ACCURACY: the agent was telling callers "only 9 or 11 available"
    # when 17/18 slots were actually free — it mistook the 1-2 it should
    # OFFER for the total that EXIST. So state the real picture
    # explicitly: how many free, which (few) are booked, the open
    # window. The example spread is only SUGGESTIONS to move the
    # booking, NOT the limit of availability.
    n = len(free)
    booked = sorted(set(all_slots) - set(free))
    idxs = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1})
    spread = [free[i] for i in idxs]
    if n == total:
        picture = (
            f"the WHOLE day is open — every slot "
            f"{ampm12(free[0])}–{ampm12(last_hhmm)} is free"
        )
    elif n >= total * 0.6:
        picture = (
            f"almost the whole day is open ({n} of {total} free); only "
            f"these are taken: {ampm12_list(booked) or 'none'}"
        )
    else:
        picture = (
            f"{n} of {total} slots free; taken: {ampm12_list(booked)}"
        )
    return (
        f"TABLE-FRESH DATA for {d} (just read from the Appointment "
        f"table this turn): {picture}. The last slot starts at "
        f"{ampm12(last_hhmm)}; clinic closes at {ampm12(close_hhmm)}. "
        "TELL THE CALLER THIS AVAILABILITY ACCURATELY — never say only "
        "one or two times are available when many are free, never under-"
        "state. If they ask 'what's free', say it openly (e.g. 'almost "
        f"all times that day, {ampm12(free[0])} to {ampm12(last_hhmm)}'). "
        f"THEN, to move the booking, suggest 1-2 times near what they "
        f"want: {ampm12_list(spread)}. Don't read the whole list. A time "
        f"AT OR AFTER {ampm12(close_hhmm)} is after closing — anything "
        f"earlier is bookable. Any time in 'free' above is FREE — do NOT "
        f"call any OTHER time 'taken' without re-calling this tool."
    )


@function_tool()
@_instrument("book_appointment")
async def book_appointment(
    context: RunContext,
    date: str,
    time: str,
    name: str = "",
    reason: str = "",
    party_size: int = 0,
    service_type: str = "",
    notes: str = "",
) -> str:
    """Book an appointment slot. Call this after the caller picked a day
    + time. Spoken times are normalised (e.g. "5 pm"/"evening 5"/"17:00"
    -> 17:00, "5:15" snaps to the nearest slot). The caller's phone is
    attached automatically — do not ask for it.

    Args:
        date: 'today'/'tomorrow'/weekday/'YYYY-MM-DD'.
        time: whatever the caller said for time — it gets normalised.
        name: caller's name if known.
        reason: why they're booking, in the caller's own words.
        party_size: number of people (RESTAURANT / HOTEL / event venue).
            Pass 0 (default) for businesses where this is irrelevant
            (clinic, salon, 1-on-1 consultation).
        service_type: which service (SALON / CLINIC / spa) — e.g.
            "haircut", "facial", "consultation", "follow-up". "" if
            irrelevant or unspecified.
        notes: free-form special instructions ("late checkin", "vegan
            menu", "child seat needed"). Keep brief — caller's own words.
    """
    from src import db

    d = db.resolve_date(date)
    if not d:
        return "Date unclear — ask the caller to restate the day."
    t = db.norm_time(time)
    if not t:
        return (
            "Time unclear — ask the caller for a time within working "
            "hours (e.g. 'morning 10' or '5 PM')."
        )
    phone = caller_phone_var.get()
    ok, msg = await db.appt_book(
        d, t, name=name, phone=phone, reason=reason, source="call",
        party_size=party_size, service_type=service_type, notes=notes,
    )
    # Whether success or failure, the table state for this date may have
    # changed (book attempt itself or a sibling): force the next LLM
    # turn to re-read so the live-snapshot in the agent's chat context
    # reflects reality, not a 6s-stale view.
    inv = appt_snapshot_invalidate_var.get()
    if inv is not None:
        try:
            inv()
        except Exception:
            pass
    if ok:
        return (
            f"TOOL CONFIRMED — Appointment table row inserted: "
            f"date={d} time={ampm12(t)}. Read THIS exact time "
            f"({ampm12(t)}) back to the caller — not whatever spoken "
            "form they said (their wording got normalised; say what the "
            "table now has). Confirm in ONE short sentence (day, time, "
            "reason) and close warmly. Do NOT promise an SMS — we do "
            "not send one."
        )
    # Slot taken/invalid -> hand the agent the FULL picture of remaining
    # free slots so it doesn't under-state availability (the agent was
    # only ever shown the first 4 = morning, and then wrongly told
    # callers all afternoons were "also booked"). Spread + count makes
    # the agent represent the day correctly.
    free = await db.appt_available_slots(d)
    if not free:
        return (
            f"Could not book ({msg}) and no other slots free that day. "
            "Offer the caller a different day."
        )
    from src import db as _db
    total = len(_db._all_slots())
    n = len(free)
    idxs = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1})
    spread = [free[i] for i in idxs]
    return (
        f"Could not book ({msg}). Do NOT pretend it's booked. "
        f"REMAINING availability that day: {n} of {total} slots STILL "
        f"FREE — open {ampm12(free[0])}–{ampm12(free[-1])}, examples: "
        f"{ampm12_list(spread)}. NEVER tell the caller other times are "
        "also booked unless you re-call check_appointment_slots and the "
        "tool says so — if they pick a different time, ATTEMPT it (book "
        "or check again), never assume."
    )


@function_tool()
@_instrument("my_appointment")
async def my_appointment(context: RunContext) -> str:
    """Look up the caller's existing upcoming appointment(s) by their
    phone number. Use when the caller asks 'what's my appointment',
    'when is my booking', or wants to change/cancel it."""
    from src import db

    phone = caller_phone_var.get()
    if not phone:
        return "No caller number on file — ask them for their booking day."
    appts = await db.appt_find_by_phone(phone)
    if not appts:
        return (
            "No upcoming appointment found for this number. Offer to "
            "book a new one."
        )
    # Return ALL upcoming bookings — single-appt return was hiding the
    # caller's second/third booking from the agent (it would then say
    # "only one on file" wrongly). The agent picks the right id from
    # this list based on which one the caller is asking about.
    if len(appts) == 1:
        a = appts[0]
        return (
            f"Found ONE upcoming booking: id={a['id']} on {a['date']} at "
            f"{ampm12(a['time'])} for {a['reason'] or 'a visit'}. Tell the caller "
            "the day & time; for changes use reschedule_appointment with "
            "this id."
        )
    lines = [
        f"  - id={a['id']}  {a['date']} {ampm12(a['time'])}  "
        f"({a['reason'] or 'a visit'})"
        for a in appts
    ]
    return (
        f"Found {len(appts)} upcoming bookings for this caller:\n"
        + "\n".join(lines)
        + "\nTell the caller the day+time of EACH (briefly). If they want "
        "to change one, ask WHICH and pass THAT id to "
        "reschedule_appointment — NEVER guess which one."
    )


@function_tool()
@_instrument("reschedule_appointment")
async def reschedule_appointment(
    context: RunContext, appointment_id: str, new_date: str, new_time: str
) -> str:
    """Move the caller's existing appointment to a new day/time. Get the
    appointment_id from my_appointment first.

    Args:
        appointment_id: id returned by my_appointment.
        new_date: 'tomorrow'/weekday/'YYYY-MM-DD'.
        new_time: the new time the caller wants (normalised).
    """
    from src import db

    d = db.resolve_date(new_date)
    t = db.norm_time(new_time)
    if not d or not t:
        return "New day/time unclear — ask the caller to restate it."
    ok, msg = await db.appt_reschedule(
        appointment_id, d, t, phone=caller_phone_var.get()
    )
    # Invalidate snapshot so the very next turn sees the new state
    # (old slot freed, new slot taken) — not a 6s-stale view.
    inv = appt_snapshot_invalidate_var.get()
    if inv is not None:
        try:
            inv()
        except Exception:
            pass
    if ok:
        return (
            f"Rescheduled to {d} at {ampm12(t)}. Confirm the new day & time in "
            "one short sentence. No SMS is sent."
        )
    # Same anti-hallucination shape as book_appointment failure: hand the
    # agent the FULL remaining picture (count + spread + open window), not
    # just the first 4 slots — otherwise it tells callers "afternoons are
    # also taken" when actually most of the day is free.
    free = await db.appt_available_slots(d)
    if not free:
        return (
            f"Could not reschedule ({msg}) and no other free slots that "
            "day. Offer the caller a different day."
        )
    from src import db as _db
    total = len(_db._all_slots())
    n = len(free)
    idxs = sorted({0, n // 4, n // 2, (3 * n) // 4, n - 1})
    spread = [free[i] for i in idxs]
    return (
        f"Could not reschedule ({msg}). Do NOT pretend it moved. "
        f"REMAINING availability that day: {n} of {total} slots STILL "
        f"FREE — open {ampm12(free[0])}–{ampm12(free[-1])}, examples: "
        f"{ampm12_list(spread)}. NEVER tell the caller other times are "
        "also booked unless you re-call check_appointment_slots and the "
        "tool says so."
    )


@function_tool()
@_instrument("cancel_appointment")
async def cancel_appointment(
    context: RunContext, appointment_id: str
) -> str:
    """Cancel ONE specific appointment by its id. Get the id from
    my_appointment first. After a successful cancel, the slot is freed
    immediately.

    Args:
        appointment_id: id returned by my_appointment.
    """
    from src import db

    aid = (appointment_id or "").strip()
    if not aid:
        return (
            "Appointment id missing — call my_appointment first to get "
            "the id, then pass it here."
        )
    ok = await db.appt_cancel(aid, phone=caller_phone_var.get())
    # Invalidate the live snapshot so the next turn re-reads — the freed
    # slot must show as free immediately, and the cancelled booking must
    # disappear from the caller's bookings list.
    inv = appt_snapshot_invalidate_var.get()
    if inv is not None:
        try:
            inv()
        except Exception:
            pass
    if ok:
        return (
            f"TOOL CONFIRMED — Appointment {aid} cancelled in the table. "
            "Tell the caller it's cancelled in ONE short sentence. No "
            "SMS is sent. Do NOT mention the id."
        )
    return (
        f"Could not cancel {aid}. Do NOT pretend it was cancelled. Tell "
        "the caller you couldn't cancel right now and the team will "
        "follow up."
    )


@function_tool()
@_instrument("cancel_all_appointments")
async def cancel_all_appointments(context: RunContext) -> str:
    """Cancel ALL of THIS caller's upcoming appointments at once. Use
    ONLY when the caller explicitly says 'cancel everything / all /
    mottam cancel chey'. Confirm with the caller BEFORE calling — this
    is irreversible. The caller's phone is attached automatically."""
    from src import db

    phone = caller_phone_var.get()
    if not phone:
        return (
            "No caller number on file — cannot identify which bookings "
            "to cancel. Ask the caller for their booking day instead."
        )
    appts = await db.appt_find_by_phone(phone)
    if not appts:
        return (
            "This caller has NO upcoming bookings to cancel. Tell them "
            "honestly that nothing was on file."
        )
    cancelled = 0
    failed = 0
    for a in appts:
        try:
            ok = await db.appt_cancel(a["id"], phone=phone)
            if ok:
                cancelled += 1
            else:
                failed += 1
        except Exception:
            failed += 1
    inv = appt_snapshot_invalidate_var.get()
    if inv is not None:
        try:
            inv()
        except Exception:
            pass
    if cancelled and not failed:
        return (
            f"TOOL CONFIRMED — all {cancelled} of this caller's "
            f"appointments cancelled in the table. Tell the caller they're "
            f"all cancelled, in ONE short sentence, in the caller's CURRENT "
            f"language (gender-neutral honorific — never 'sir/సర్/सर'). Do "
            "NOT list them out again — just acknowledge."
        )
    if cancelled and failed:
        return (
            f"PARTIAL: {cancelled} cancelled, {failed} failed. Tell the "
            "caller most are cancelled and the team will check the rest."
        )
    return (
        "Could not cancel any of the appointments right now. Tell the "
        "caller honestly that there was an issue and the team will "
        "follow up — do NOT claim they're cancelled."
    )


@function_tool()
async def end_call(context: RunContext) -> str:
    """Hang up / end the phone call. Call this ONCE the conversation is
    complete — the caller said bye, the appointment is confirmed and
    they need nothing else, or they clearly want to stop. Say your short
    goodbye line FIRST, then call this."""
    cb = end_call_var.get()
    if cb is None:
        return "Call end not available; just stop talking."
    try:
        await cb()
        return "Call is ending. Do not say anything further."
    except Exception:
        logger.debug("end_call failed", exc_info=True)
        return "Could not end the call; stop talking."


# Per-use-case tool gating. The model can only call a tool it is given,
# so withholding booking tools from a survey/sales/custom call is the
# strongest structural anti-hallucination guard (no prompt obedience
# needed). Booking tools are exposed ONLY for appointment-family
# use-cases; unknown/"custom" gets NO booking tools (user-chosen safest).
_BASE_TOOLS: list[Any] = [kb_search, end_call]
_APPT_TOOLS: list[Any] = [
    check_appointment_slots,
    book_appointment,
    my_appointment,
    reschedule_appointment,
    cancel_appointment,
    cancel_all_appointments,
]
_RESCHED_TOOLS: list[Any] = [
    check_appointment_slots,
    my_appointment,
    reschedule_appointment,
    cancel_appointment,
    cancel_all_appointments,
]
_ORDER_TOOLS: list[Any] = [order_status]

_USE_CASE_TOOLS: dict[str, list[Any]] = {
    "appointment": _APPT_TOOLS,
    "reminder": _APPT_TOOLS,
    "reschedule": _RESCHED_TOOLS,
    "support": _ORDER_TOOLS,
    "collections": _ORDER_TOOLS,
    "custom": _ORDER_TOOLS,   # safest: order lookup ok, NO booking
    "sales": [],
    "leadgen": [],
    "survey": [],
    "feedback": [],
}


# Name → tool lookup. The dashboard stores tools by name (CSV) in
# AgentConfig.enabledTools so an operator can mix tools beyond a single
# use-case (e.g. salon = appointment tools + order_status). kb_search and
# end_call are intentionally NOT here — they live in `_BASE_TOOLS` and are
# always exposed regardless of override (a call always needs to look
# things up and end cleanly).
_NAMED_TOOLS: dict[str, Any] = {
    "check_appointment_slots":  check_appointment_slots,
    "book_appointment":         book_appointment,
    "my_appointment":           my_appointment,
    "reschedule_appointment":   reschedule_appointment,
    "cancel_appointment":       cancel_appointment,
    "cancel_all_appointments":  cancel_all_appointments,
    "order_status":             order_status,
}


def tools_for(use_case: str | None, enabled: str | None = None) -> list[Any]:
    """Resolve the tool set for a call.

    Resolution order (smallest-diff override):
      1. If `enabled` (CSV) is non-empty -> expose ONLY those named
         tools (unknown names are silently dropped) + base tools. This
         is the dashboard's per-config multi-select.
      2. Else fall back to the static use-case map (back-compat: existing
         configs with no override see identical behavior).
    """
    if enabled and enabled.strip():
        wanted = [
            _NAMED_TOOLS[n] for n in (
                t.strip() for t in enabled.split(",")
            ) if n in _NAMED_TOOLS
        ]
        return _BASE_TOOLS + wanted
    uc = (use_case or "custom").strip().lower()
    extra = _USE_CASE_TOOLS.get(uc, _USE_CASE_TOOLS["custom"])
    return _BASE_TOOLS + extra


# Back-compat alias (full set) for any importer expecting the old name.
AGENT_TOOLS: list[Any] = (
    _BASE_TOOLS + _APPT_TOOLS + _ORDER_TOOLS
)
