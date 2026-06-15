"""Supabase Postgres persistence (system of record).

Prisma owns the schema/migrations (dashboard side). Python connects to
the SAME database with asyncpg to durably persist calls + transcripts and
keep the live config readable. Redis still handles the sub-second hot
path (semantic cache, live SSE) — this is the durable store the dashboard
reads via Prisma + Supabase Realtime.

Every operation degrades to a no-op if Supabase isn't configured or is
unreachable — persistence must never break a live call.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date as _date, datetime, timedelta

from src.config import settings
from src.clock import now_tz, today_tz

logger = logging.getLogger("db")

_pool = None
# Transient-failure backoff (NOT a permanent latch). The old code set a
# process-global `_disabled=True` on the first create_pool() failure —
# so one network/DNS blip (the same one that causes dead-air) silently
# killed ALL persistence for the whole worker lifetime, even after the
# network recovered. Calls ran fine but nothing was saved -> dashboard
# 404 / infinite spinner. Now we just back off briefly and RETRY, so
# persistence self-heals the moment connectivity returns.
_retry_after = 0.0
_RETRY_BACKOFF = 20.0  # seconds between create_pool attempts while down

# Run-once guard for the appointment slot-uniqueness DDL.
_appt_idx_ready = False


async def _ensure_appt_constraints(pool) -> None:
    """Create a PARTIAL UNIQUE index on (date, time) for booked rows so
    the database itself rejects a second booking of a slot that's already
    taken — closing the check-then-INSERT race two concurrent calls could
    otherwise both pass. Prisma can't express a partial unique index, so
    we create it here, idempotently. Guarded: if it can't be created
    (e.g. pre-existing duplicate booked rows for a slot, or insufficient
    privilege) we log and continue — the code-level catch in appt_book /
    appt_reschedule still applies, and an operator can dedupe + restart.
    """
    global _appt_idx_ready
    if _appt_idx_ready:
        return
    try:
        async with pool.acquire() as c:
            await c.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS appt_slot_booked_uq '
                'ON voiceai."Appointment" (date, time) '
                "WHERE status = 'booked'"
            )
        _appt_idx_ready = True
        logger.info("appt unique-slot index ensured")
    except Exception:
        _appt_idx_ready = True  # don't hammer it every pool use
        logger.warning(
            "could not create appt unique-slot index (existing duplicate "
            "booked rows, or no DDL privilege) — double-booking guard "
            "relies on the code-level checks until resolved",
            exc_info=True,
        )


def _ensure_executor() -> None:
    """Python 3.13 + LiveKit inference subprocess: when the inference
    subprocess exits, it calls loop.shutdown_default_executor() which
    kills the ThreadPoolExecutor that asyncpg needs for getaddrinfo DNS
    resolution. Every subsequent pool.acquire() → new connection →
    getaddrinfo then raises RuntimeError('Executor shutdown has been
    called'), silently dropping all DB writes for the rest of the call.
    Fix: detect the dead executor and replace it with a fresh one."""
    import concurrent.futures
    loop = asyncio.get_event_loop()
    try:
        loop._check_default_executor()  # raises RuntimeError if dead
    except (RuntimeError, AttributeError):
        loop.set_default_executor(
            concurrent.futures.ThreadPoolExecutor(max_workers=4)
        )


async def _get_pool():
    """Lazily create a small asyncpg pool. Returns None *for now* if
    Supabase is unreachable, but RETRIES on a later call so a transient
    outage doesn't permanently disable persistence."""
    global _pool, _retry_after
    if not settings.supabase_db_url:
        return None
    if _pool is not None:
        _ensure_executor()  # revive executor if killed by LiveKit subprocess
        return _pool
    if time.monotonic() < _retry_after:
        return None  # backing off; try again after the window
    try:
        import asyncpg

        from src.pg import asyncpg_args

        _ensure_executor()  # must be alive before create_pool DNS lookup
        dsn, extra = asyncpg_args(settings.supabase_db_url)
        _pool = await asyncpg.create_pool(
            dsn,
            min_size=4,
            max_size=150,         # Supabase Pro = 200 direct conns; increased
                                  # from 100 to 150 for sub-500ms target.
                                  # Higher pool prevents connection starvation
                                  # under high concurrent call load.
            command_timeout=10,
            # never let a slow query block a call forever waiting for
            # a free connection — fail fast and degrade to no-op.
            timeout=5,
            max_inactive_connection_lifetime=120,
            # No prepared-statement cache: a schema migration (prisma db
            # push) invalidates cached plans on live pooled connections,
            # which made EVERY upsert fail mid-call on 2026-06-12 until
            # a worker restart. Re-preparing per query costs ~0; broken
            # telemetry costs a blind dashboard.
            statement_cache_size=extra.pop("statement_cache_size", 0),
            **extra,
        )
        logger.info("Supabase pool connected")
        await _ensure_appt_constraints(_pool)
        return _pool
    except Exception:
        _retry_after = time.monotonic() + _RETRY_BACKOFF
        logger.warning(
            "Supabase unreachable; persistence degraded, retrying in %ss",
            int(_RETRY_BACKOFF),
            exc_info=True,
        )
        return None


async def upsert_call(
    call_id: str,
    *,
    room: str,
    direction: str,
    status: str | None = None,
    language: str | None = None,
    emotion: str | None = None,
    intent: str | None = None,
    caller_name: str | None = None,
    turns: int | None = None,
    llm_calls: int | None = None,
    kb_calls: int | None = None,
    bypass_rate: float | None = None,
    avg_eou_ms: int | None = None,
    max_eou_ms: int | None = None,
    avg_llm_ttft_ms: int | None = None,
    max_llm_ttft_ms: int | None = None,
    avg_tts_ttfb_ms: int | None = None,
    max_tts_ttfb_ms: int | None = None,
    avg_assembly_ms: int | None = None,
    max_assembly_ms: int | None = None,
    avg_snapshot_ms: int | None = None,
    max_snapshot_ms: int | None = None,
) -> bool:
    """Return True on durable success, False on failure (pool down,
    SSL fail, exception). Callers MUST use this to gate retry — the
    old None return masked silent failures (the FK-cascade bug)."""
    pool = await _get_pool()
    if pool is None:
        return False
    try:
        async with pool.acquire() as c:
            try:
                await c.execute(
                    """
                    INSERT INTO voiceai."Call"
                      (id, room, direction, status,
                       "avgAssemblyMs", "maxAssemblyMs",
                       "avgSnapshotMs", "maxSnapshotMs")
                    VALUES ($1, $2, $3, COALESCE($4, 'live'),
                            COALESCE($19, 0), COALESCE($20, 0),
                            COALESCE($21, 0), COALESCE($22, 0))
                    ON CONFLICT (id) DO UPDATE SET
                      status         = COALESCE($4, "Call".status),
                      language       = COALESCE($5, "Call".language),
                      emotion        = COALESCE($6, "Call".emotion),
                      intent         = COALESCE($7, "Call".intent),
                      "callerName"   = COALESCE($8, "Call"."callerName"),
                      turns          = COALESCE($9, "Call".turns),
                      "llmCalls"     = COALESCE($10, "Call"."llmCalls"),
                      "kbCalls"      = COALESCE($11, "Call"."kbCalls"),
                      "bypassRate"   = COALESCE($12, "Call"."bypassRate"),
                      "avgEouMs"     = COALESCE($13, "Call"."avgEouMs"),
                      "maxEouMs"     = COALESCE($14, "Call"."maxEouMs"),
                      "avgLlmTtftMs" = COALESCE($15, "Call"."avgLlmTtftMs"),
                      "maxLlmTtftMs" = COALESCE($16, "Call"."maxLlmTtftMs"),
                      "avgTtsTtfbMs" = COALESCE($17, "Call"."avgTtsTtfbMs"),
                      "maxTtsTtfbMs" = COALESCE($18, "Call"."maxTtsTtfbMs"),
                      "avgAssemblyMs"= COALESCE($19, "Call"."avgAssemblyMs"),
                      "maxAssemblyMs"= COALESCE($20, "Call"."maxAssemblyMs"),
                      "avgSnapshotMs"= COALESCE($21, "Call"."avgSnapshotMs"),
                      "maxSnapshotMs"= COALESCE($22, "Call"."maxSnapshotMs")
                    """,
                    call_id, room, direction, status, language, emotion,
                    intent, caller_name, turns, llm_calls, kb_calls,
                    bypass_rate,
                    avg_eou_ms, max_eou_ms,
                    avg_llm_ttft_ms, max_llm_ttft_ms,
                    avg_tts_ttfb_ms, max_tts_ttfb_ms,
                    avg_assembly_ms, max_assembly_ms,
                    avg_snapshot_ms, max_snapshot_ms,
                )
            except Exception:
                # Pre-migration column-missing safety: if the new latency
                # columns aren't in Supabase yet (mid-deploy window), fall
                # back to the legacy 12-arg upsert so calls don't error.
                logger.debug(
                    "upsert_call: new latency cols missing, legacy upsert",
                    exc_info=True,
                )
                await c.execute(
                    """
                    INSERT INTO voiceai."Call" (id, room, direction, status)
                    VALUES ($1, $2, $3, COALESCE($4, 'live'))
                    ON CONFLICT (id) DO UPDATE SET
                      status      = COALESCE($4, "Call".status),
                      language    = COALESCE($5, "Call".language),
                      emotion     = COALESCE($6, "Call".emotion),
                      intent      = COALESCE($7, "Call".intent),
                      "callerName"= COALESCE($8, "Call"."callerName"),
                      turns       = COALESCE($9, "Call".turns),
                      "llmCalls"  = COALESCE($10, "Call"."llmCalls"),
                      "kbCalls"   = COALESCE($11, "Call"."kbCalls"),
                      "bypassRate"= COALESCE($12, "Call"."bypassRate")
                    """,
                    call_id, room, direction, status, language, emotion,
                    intent, caller_name, turns, llm_calls, kb_calls,
                    bypass_rate,
                )
        return True
    except Exception:
        # Visible logging: a silent upsert_call failure used to take
        # down the whole transcript chain (FK violation everywhere).
        logger.warning("upsert_call FAILED id=%s", call_id, exc_info=True)
        return False


async def insert_transcript(call_id: str, role: str, text: str) -> bool:
    """Return True on durable success, False on any failure (pool
    down, FK violation, SSL fail). Replay/counters must use the bool
    — the old None return inflated 'back-filled' counts with attempts
    that actually never landed in Supabase."""
    pool = await _get_pool()
    if pool is None or not text:
        return False
    try:
        async with pool.acquire() as c:
            await c.execute(
                'INSERT INTO voiceai."Transcript" ("callId", role, text) '
                "VALUES ($1, $2, $3)",
                call_id, role, text,
            )
        return True
    except Exception:
        # Visible so a recurring FK / pool problem stops being silent.
        logger.warning(
            "insert_transcript FAILED call=%s role=%s",
            call_id, role, exc_info=True,
        )
        return False


async def transcript_count(call_id: str) -> int:
    """How many Transcript rows exist for this call. Used by the
    telemetry end-of-call replay to detect a gap vs the Redis buffer
    and back-fill the missing tail (the "no transcript" safety net)."""
    pool = await _get_pool()
    if pool is None:
        return 0
    try:
        async with pool.acquire() as c:
            n = await c.fetchval(
                'SELECT count(*) FROM voiceai."Transcript" '
                'WHERE "callId" = $1',
                call_id,
            )
        return int(n or 0)
    except Exception:
        logger.warning("transcript_count failed call=%s", call_id,
                       exc_info=True)
        return 0


async def end_call(call_id: str) -> None:
    pool = await _get_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as c:
            await c.execute(
                'UPDATE voiceai."Call" SET status = $2, "endedAt" = now() '
                "WHERE id = $1",
                call_id, "ended",
            )
    except Exception:
        logger.debug("end_call failed", exc_info=True)


# ─── Campaign helpers (used by the control-API runner) ──────────────
async def get_campaign(cid: str) -> dict | None:
    pool = await _get_pool()
    if pool is None:
        return None
    async with pool.acquire() as c:
        try:
            row = await c.fetchrow(
                'SELECT id, name, status, "callerId", language, total, '
                'script, "voiceModel", "voiceSpeaker", "useCaseType", '
                '"businessDescription", "styleExamples", "kbVectorStoreId" '
                'FROM voiceai."Campaign" WHERE id = $1',
                cid,
            )
        except Exception:
            # New columns not migrated yet -> legacy SELECT (degrade-safe;
            # use-case/content overrides simply fall back to global).
            logger.debug("get_campaign: new cols missing, legacy select",
                         exc_info=True)
            row = await c.fetchrow(
                'SELECT id, name, status, "callerId", language, total, '
                'script, "voiceModel", "voiceSpeaker" '
                'FROM voiceai."Campaign" WHERE id = $1',
                cid,
            )
        return dict(row) if row else None


async def pending_contacts(cid: str) -> list[dict]:
    pool = await _get_pool()
    if pool is None:
        return []
    async with pool.acquire() as c:
        rows = await c.fetch(
            'SELECT id, phone, name FROM voiceai."CampaignContact" '
            "WHERE \"campaignId\" = $1 AND status IN ('pending','failed') "
            "ORDER BY \"updatedAt\" ASC",
            cid,
        )
        return [dict(r) for r in rows]


async def set_campaign_status(cid: str, status: str) -> None:
    pool = await _get_pool()
    if pool is None:
        return
    col = '"startedAt"' if status == "running" else '"finishedAt"'
    async with pool.acquire() as c:
        await c.execute(
            f'UPDATE voiceai."Campaign" SET status=$2, {col}=now() '
            "WHERE id=$1",
            cid, status,
        )


async def update_contact(
    contact_id: str, *, status: str, room: str = "", error: str = "",
    bump_attempts: bool = False,
) -> None:
    pool = await _get_pool()
    if pool is None:
        return
    # `attempts` must increment ONCE per real dial. update_contact is
    # called twice per dial ("dialing" then "done"/"failed"); bumping on
    # both double-counted attempts and tripped the max-attempts cap at
    # ~1.5 real tries. Caller bumps only on the "dialing" transition.
    attempts_sql = "attempts=attempts+1, " if bump_attempts else ""
    async with pool.acquire() as c:
        await c.execute(
            'UPDATE voiceai."CampaignContact" '
            f'SET status=$2, room=$3, error=$4, {attempts_sql}'
            '"updatedAt"=now() WHERE id=$1',
            contact_id, status, room, error[:300],
        )


async def refresh_campaign_counts(cid: str) -> None:
    pool = await _get_pool()
    if pool is None:
        return
    async with pool.acquire() as c:
        await c.execute(
            'UPDATE voiceai."Campaign" SET '
            'completed=(SELECT count(*) FROM voiceai."CampaignContact" '
            "  WHERE \"campaignId\"=$1 AND status='done'), "
            'failed=(SELECT count(*) FROM voiceai."CampaignContact" '
            "  WHERE \"campaignId\"=$1 AND status='failed') "
            "WHERE id=$1",
            cid,
        )


async def reset_campaign(cid: str, only_failed: bool = False) -> int:
    """Re-arm a finished campaign so it can be run again.

    only_failed=False -> reset EVERY contact (re-run the whole list).
    only_failed=True  -> reset only the ones that did NOT complete
                         (failed / stuck), keep the 'done' ones done.

    Clears attempts/error/room, sets contacts back to 'pending' and the
    campaign back to 'pending', then recomputes counts. Returns the
    number of contacts re-armed.
    """
    pool = await _get_pool()
    if pool is None:
        return 0
    where = '"campaignId"=$1'
    if only_failed:
        where += " AND status <> 'done'"
    async with pool.acquire() as c:
        rows = await c.fetch(
            'UPDATE voiceai."CampaignContact" '
            "SET status='pending', attempts=0, error='', room='', "
            '"updatedAt"=now() '
            f"WHERE {where} RETURNING id",
            cid,
        )
        await c.execute(
            'UPDATE voiceai."Campaign" '
            "SET status='pending', \"finishedAt\"=NULL WHERE id=$1",
            cid,
        )
    await refresh_campaign_counts(cid)
    return len(rows)


# ─── Campaign RUN history (preserve every run's results) ────────────
async def create_campaign_run(cid: str, total: int) -> str | None:
    """Open a new run for a campaign (runNo auto-increments). Returns
    the run id, or None if persistence is down (caller degrades)."""
    pool = await _get_pool()
    if pool is None:
        return None
    rid = uuid.uuid4().hex
    try:
        async with pool.acquire() as c:
            run_no = await c.fetchval(
                'SELECT COALESCE(MAX("runNo"),0)+1 FROM '
                'voiceai."CampaignRun" WHERE "campaignId"=$1',
                cid,
            )
            await c.execute(
                'INSERT INTO voiceai."CampaignRun" '
                '(id,"campaignId","runNo",status,total,completed,failed) '
                "VALUES ($1,$2,$3,'running',$4,0,0)",
                rid, cid, run_no, total,
            )
        return rid
    except Exception:
        logger.debug("create_campaign_run failed", exc_info=True)
        return None


async def record_run_contact(
    run_id: str | None, phone: str, *, name: str = "",
    status: str = "dialing", room: str = "", error: str = "",
) -> None:
    """Snapshot a contact's outcome for THIS run (upsert by run+phone),
    so a later re-run never overwrites this run's history."""
    pool = await _get_pool()
    if pool is None or not run_id:
        return
    try:
        async with pool.acquire() as c:
            await c.execute(
                'INSERT INTO voiceai."CampaignRunContact" '
                '(id,"runId",phone,name,status,room,error,"updatedAt") '
                "VALUES ($1,$2,$3,$4,$5,$6,$7,now()) "
                'ON CONFLICT ("runId",phone) DO UPDATE SET '
                'status=$5, room=$6, error=$7, name=$4, "updatedAt"=now()',
                uuid.uuid4().hex, run_id, phone, name[:120], status,
                room, error[:300],
            )
    except Exception:
        logger.debug("record_run_contact failed", exc_info=True)


async def finalize_campaign_run(run_id: str | None) -> None:
    """Close a run and freeze its completed/failed counts."""
    pool = await _get_pool()
    if pool is None or not run_id:
        return
    try:
        async with pool.acquire() as c:
            await c.execute(
                'UPDATE voiceai."CampaignRun" SET status=\'done\', '
                '"finishedAt"=now(), '
                'completed=(SELECT count(*) FROM '
                'voiceai."CampaignRunContact" '
                "WHERE \"runId\"=$1 AND status='done'), "
                'failed=(SELECT count(*) FROM '
                'voiceai."CampaignRunContact" '
                "WHERE \"runId\"=$1 AND status='failed') "
                "WHERE id=$1",
                run_id,
            )
    except Exception:
        logger.debug("finalize_campaign_run failed", exc_info=True)


# ─── KB document helpers ────────────────────────────────────────────
async def insert_kb_document(
    doc_id: str, filename: str, size: int, kb_id: str = ""
) -> None:
    pool = await _get_pool()
    if pool is None:
        return
    async with pool.acquire() as c:
        await c.execute(
            'INSERT INTO voiceai."KbDocument" '
            '(id, filename, "sizeBytes", status, "kbId") VALUES ($1,$2,$3,$4,$5)',
            doc_id, filename, size, "ingesting", kb_id or None,
        )


async def update_kb_document(
    doc_id: str, *, status: str, vector_store_id: str = "", error: str = ""
) -> None:
    pool = await _get_pool()
    if pool is None:
        return
    async with pool.acquire() as c:
        await c.execute(
            'UPDATE voiceai."KbDocument" '
            'SET status=$2, "vectorStoreId"=$3, error=$4 WHERE id=$1',
            doc_id, status, vector_store_id, error[:300],
        )


async def set_kb_vector_store(vsid: str) -> None:
    """Point the active AgentConfig at the KB vector store."""
    pool = await _get_pool()
    if pool is None:
        return
    async with pool.acquire() as c:
        await c.execute(
            'UPDATE voiceai."AgentConfig" SET "kbVectorStoreId"=$1 '
            "WHERE id='default'",
            vsid,
        )


# ─── Appointments (calendar + slots) ─────────────────────────────────
# Working hours start from env defaults but are REFRESHED per-call by the
# agent from the active AgentConfig row (see `_refresh_appt_grid` below) so
# any business can edit hours from the dashboard without a redeploy.
APPT_OPEN_HOUR = settings.appt_open_hour
APPT_CLOSE_HOUR = settings.appt_close_hour
APPT_SLOT_MIN = settings.appt_slot_min
APPT_OPEN_WEEKDAYS_RAW = settings.appt_open_weekdays
APPT_OPEN_WEEKDAYS = {
    int(x) for x in str(settings.appt_open_weekdays).split(",") if x.strip()
}


def _refresh_appt_grid(cfg) -> None:
    """Re-apply the appointment grid from the active runtime config so
    dashboard-edited hours take effect on the next call. Called by the
    agent right after `load_runtime_config()`. Safe with None / partial
    cfg — missing/invalid fields fall back to env defaults; an exception
    keeps the last good values."""
    global APPT_OPEN_HOUR, APPT_CLOSE_HOUR, APPT_SLOT_MIN
    global APPT_OPEN_WEEKDAYS, APPT_OPEN_WEEKDAYS_RAW
    try:
        o = int(getattr(cfg, "appt_open_hour", 0) or settings.appt_open_hour)
        c = int(getattr(cfg, "appt_close_hour", 0) or settings.appt_close_hour)
        s = int(getattr(cfg, "appt_slot_min", 0) or settings.appt_slot_min)
        wd_raw = (getattr(cfg, "appt_open_weekdays", "")
                  or settings.appt_open_weekdays)
        wd = {int(x) for x in str(wd_raw).split(",") if x.strip().isdigit()}
        # Sanity-clamp: nonsense values (close <= open, slot >= window)
        # would produce an empty slot grid and break booking entirely.
        # Fall back to env if so.
        if not (0 <= o < 24) or not (1 <= c <= 24) or c <= o or s <= 0 \
                or s * 60 > (c - o) * 3600 or not wd:
            raise ValueError(f"invalid appt grid: o={o} c={c} s={s} wd={wd}")
        APPT_OPEN_HOUR = o
        APPT_CLOSE_HOUR = c
        APPT_SLOT_MIN = s
        APPT_OPEN_WEEKDAYS = wd
        APPT_OPEN_WEEKDAYS_RAW = str(wd_raw)
    except Exception:
        logger.warning(
            "appt grid refresh: invalid cfg, keeping last good values",
            exc_info=True,
        )

_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _all_slots() -> list[str]:
    out, t = [], APPT_OPEN_HOUR * 60
    while t < APPT_CLOSE_HOUR * 60:
        out.append(f"{t // 60:02d}:{t % 60:02d}")
        t += APPT_SLOT_MIN
    return out


def norm_time(text: str) -> str | None:
    """Loose spoken time -> a valid grid 'HH:MM', snapped to the nearest
    slot. Handles '5', '5 pm', '17:00', '1700', '5:15', 'evening 5',
    'morning 9'. Returns None if no hour found. The tool layer still
    offers the nearest FREE slot if this one is taken."""
    import re

    s = (text or "").strip().lower()
    pm = any(w in s for w in ("pm", "evening", "night", "sayantram",
                              "సాయంత్రం", "రాత్రి"))
    am = any(w in s for w in ("am", "morning", "podduna", "ఉదయం",
                              "పొద్దున"))
    m = re.search(r"(\d{1,2})\s*[:.]?\s*(\d{2})?", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2)) if m.group(2) else 0
    if pm and hh < 12:
        hh += 12
    if am and hh == 12:
        hh = 0
    total = hh * 60 + mm
    step = APPT_SLOT_MIN
    total = round(total / step) * step          # snap to grid
    lo, hi = APPT_OPEN_HOUR * 60, (APPT_CLOSE_HOUR * 60) - step
    if total < lo or total > hi:
        return None
    return f"{total // 60:02d}:{total % 60:02d}"


def resolve_date(text: str) -> str | None:
    """Natural date -> 'YYYY-MM-DD'. Handles YYYY-MM-DD, today, tomorrow,
    day-after, and weekday names (next occurrence). None if unparseable.

    Whitespace-insensitive substring match — `"ఈ రోజు"` (with space) and
    `"ఈరోజు"` (without) both resolve to today; same for Hindi `"आज"` and
    Roman `"today"` embedded in fuller phrases ("today only please").
    """
    raw = (text or "").strip().lower()
    today = today_tz()
    try:
        datetime.strptime(raw, "%Y-%m-%d")
        return raw
    except ValueError:
        pass
    # Whitespace-stripped form so "ఈ రోజు" / "ఈ  రోజు" match "ఈరోజు".
    s_nospace = "".join(raw.split())
    # Substring/contains match — LLM occasionally wraps the date word
    # ("today only", "tomorrow morning"); the previous exact-equality
    # match returned None and the booking tool then said "Date unclear".
    today_words = ("today", "eeroju", "ee roju", "ఈరోజు", "నేడు", "आज", "aaj")
    tomo_words = ("tomorrow", "repu", "రేపు", "कल", "kal")
    day_after_words = ("day after tomorrow", "ellundi", "ఎల్లుండి", "परसो", "parso")
    # Order matters: day-after must be checked BEFORE tomorrow because
    # "day after tomorrow" contains the substring "tomorrow" — checking
    # tomorrow first short-circuits and returns the wrong (off-by-one)
    # date, the real bug surfaced by tests/test_db_helpers.
    for w in today_words:
        if w in raw or w.replace(" ", "") in s_nospace:
            return today.isoformat()
    for w in day_after_words:
        if w in raw or w.replace(" ", "") in s_nospace:
            return (today + timedelta(days=2)).isoformat()
    for w in tomo_words:
        if w in raw or w.replace(" ", "") in s_nospace:
            return (today + timedelta(days=1)).isoformat()
    for name, wd in _WEEKDAYS.items():
        if name in raw:
            ahead = (wd - today.weekday()) % 7
            ahead = ahead or 7  # "monday" => next monday, not today
            return (today + timedelta(days=ahead)).isoformat()
    return None


# Short-TTL cache for booked times. The agent calls
# check_appointment_slots SEVERAL times in one call (and concurrent
# calls hit the same dates) — each was a fresh Supabase round-trip over
# the pooler = the "checking slots takes too long / lag" the user saw.
# Bookings rarely change within 20s; appt_book() invalidates the date
# on success so a just-booked slot is never re-offered.
_BOOKED_TTL = 20.0
_booked_cache: dict[str, tuple[float, set[str]]] = {}


async def appt_booked_times(date_str: str, *, fresh: bool = False) -> set[str]:
    """Booked-set for a date. `fresh=True` BYPASSES the 20s cache and
    hits Supabase directly — used right before INSERT in `appt_book` so
    the race window between two near-simultaneous bookings is closed at
    the source (the cache could mask a just-booked slot for up to 20s)."""
    now = time.monotonic()
    cached = _booked_cache.get(date_str)
    if not fresh and cached is not None and cached[0] > now:
        return cached[1]
    pool = await _get_pool()
    if pool is None:
        return set()
    try:
        async with pool.acquire() as c:
            rows = await c.fetch(
                'SELECT time FROM voiceai."Appointment" '
                "WHERE date=$1 AND status='booked'",
                date_str,
            )
        booked = {r["time"] for r in rows}
        _booked_cache[date_str] = (now + _BOOKED_TTL, booked)
        return booked
    except Exception:
        logger.debug("appt_booked_times failed", exc_info=True)
        return set()


async def appt_available_slots(date_str: str, *, fresh: bool = False) -> list[str]:
    """Free slot start-times for a date ([] if closed that day).

    `fresh=True` skips the 20s booked-cache for callers that need
    real-time table truth (the pre-INSERT check in `appt_book` and the
    per-turn live snapshot the agent injects into the LLM context).

    For TODAY, slots already in the past are filtered out — otherwise the
    agent would offer "10:00 AM" at 3 PM and either fail to book a past
    slot or book one that the caller can't actually attend. A 5-minute
    cushion is kept so "I'll be there in 5" still works.
    """
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return []
    if d.weekday() not in APPT_OPEN_WEEKDAYS or d < today_tz():
        return []
    taken = await appt_booked_times(date_str, fresh=fresh)
    all_slots = _all_slots()
    if d == today_tz():
        now = now_tz()
        # Keep a slot only if its START is at least 5min in the future
        # (business-tz wall clock). cutoff stays tz-aware; only .hour/
        # .minute are read, so no naive/aware arithmetic.
        cutoff = now + timedelta(minutes=5)
        cutoff_str = f"{cutoff.hour:02d}:{cutoff.minute:02d}"
        all_slots = [s for s in all_slots if s >= cutoff_str]
    return [s for s in all_slots if s not in taken]


async def appt_book(
    date_str: str,
    time_str: str,
    *,
    name: str = "",
    phone: str = "",
    reason: str = "",
    source: str = "call",
    room: str = "",
    # Generic optional fields — defaults preserve old call-sites.
    party_size: int = 0,
    service_type: str = "",
    notes: str = "",
) -> tuple[bool, str]:
    """Book a slot if free. Returns (ok, human message)."""
    pool = await _get_pool()
    if pool is None:
        return False, "booking system temporarily unavailable"
    if time_str not in _all_slots():
        return False, f"{time_str} is not a valid slot time"
    # Past-slot guard for same-day bookings — clearer message than the
    # generic "already booked" the agent used to repeat back to callers
    # who asked for a time that had already passed today.
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        d = None
    if d == today_tz():
        now = now_tz()
        cutoff_str = f"{now.hour:02d}:{now.minute:02d}"
        if time_str < cutoff_str:
            return False, f"{time_str} is in the past today"
    # Pre-INSERT freshness: bypass the 20s cache so a slot booked within
    # the last 20s by a sibling call is seen as taken HERE (closing the
    # narrow race window before we actually INSERT).
    free = await appt_available_slots(date_str, fresh=True)
    if not free:
        return False, f"{date_str}: closed or no slots that day"
    if time_str not in free:
        return False, f"{time_str} on {date_str} is already booked"
    # Duplicate guard: same phone already has an active booking on this
    # SAME date → do NOT stack a second one. Callers shouldn't end up
    # with 3 bookings on Friday because the agent asked twice; force the
    # model to acknowledge & either reschedule or confirm a second slot
    # is genuinely wanted. Phone normalised to last-10 digits so
    # "+919398..." and "919398..." match the same person.
    if phone:
        norm = "".join(c for c in phone if c.isdigit())[-10:]
        if norm:
            try:
                async with pool.acquire() as c:
                    existing = await c.fetch(
                        'SELECT id, time, reason FROM voiceai."Appointment" '
                        'WHERE date = $1 AND status = \'booked\' '
                        'AND right(regexp_replace(phone, \'\\D\', \'\', \'g\'), 10) = $2',
                        date_str, norm,
                    )
                if existing:
                    times = ", ".join(r["time"] for r in existing)
                    return False, (
                        f"this caller already has {len(existing)} active "
                        f"booking(s) on {date_str} at {times}. Confirm "
                        f"with the caller before booking another slot on "
                        f"the same day — offer to reschedule the existing "
                        f"one OR confirm they really want a second slot."
                    )
            except Exception:
                logger.debug("duplicate-guard query failed", exc_info=True)
                # Fail open: if the guard query errors, do not block the
                # legitimate booking — the audit log will still catch it.
    # Bounded retry: most appt_book failures are TRANSIENT (pool busy,
    # network blip, brief Supabase 5xx). Without retry, ONE blip lost
    # the booking silently — exactly the "I booked at 2 PM but not in
    # table" complaint. 3 attempts with backoff absorb the transient
    # band; if it still fails, the agent's tool wrapper honestly
    # tells the caller "could not book" (we never fake success).
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            async with pool.acquire() as c:
                await c.execute(
                    'INSERT INTO voiceai."Appointment" '
                    '(id,date,time,name,phone,reason,status,source,room,'
                    '"partySize","serviceType",notes) '
                    "VALUES ($1,$2,$3,$4,$5,$6,'booked',$7,$8,$9,$10,$11)",
                    uuid.uuid4().hex, date_str, time_str, name[:120],
                    phone[:20], reason[:120], source, room,
                    max(0, int(party_size or 0)),
                    (service_type or "")[:60],
                    (notes or "")[:500],
                )
            # Invalidate the cache for this date so the slot we just
            # took disappears from the next availability check.
            _booked_cache.pop(date_str, None)
            if attempt > 0:
                logger.warning(
                    "appt_book recovered on attempt %d for %s %s",
                    attempt + 1, date_str, time_str,
                )
            # Fire-and-forget admin alert AFTER the row is committed
            # (booking is durable). Notification failure is silent.
            try:
                from src import notify as _notify
                _notify.notify_booking(
                    date=date_str, time_str=time_str, name=name,
                    phone=phone, reason=reason, party_size=party_size,
                    service_type=service_type, notes=notes,
                    source=source, room=room,
                )
            except Exception:
                logger.debug("notify_booking failed (non-fatal)", exc_info=True)
            return True, f"booked {date_str} {time_str}"
        except Exception as e:
            # A unique-violation means the (date,time) slot was taken by a
            # concurrent booking in the SELECT->INSERT window (or this is a
            # retry of an INSERT that actually committed before the ack was
            # lost). Either way retrying is wrong — report the slot taken,
            # never duplicate. (No-op unless the partial unique index from
            # _ensure_appt_constraints exists.)
            try:
                import asyncpg as _asyncpg
                if isinstance(e, _asyncpg.exceptions.UniqueViolationError):
                    _booked_cache.pop(date_str, None)
                    logger.info(
                        "appt_book slot race: %s %s taken concurrently "
                        "(unique violation) — not retrying", date_str, time_str,
                    )
                    return False, f"{time_str} on {date_str} was just booked"
            except ImportError:
                pass
            last_err = e
            if attempt < 2:
                await asyncio.sleep(0.3 * (2 ** attempt))  # 0.3s, 0.6s
                continue
            logger.warning(
                "appt_book FAILED after retries date=%s time=%s "
                "name=%s reason=%s", date_str, time_str, name, reason,
                exc_info=True,
            )
    return False, f"could not book ({str(last_err)[:80]})"


async def appt_list(date_str: str) -> list[dict]:
    pool = await _get_pool()
    if pool is None:
        return []
    try:
        async with pool.acquire() as c:
            rows = await c.fetch(
                'SELECT id,date,time,name,phone,reason,status,source,room '
                'FROM voiceai."Appointment" WHERE date=$1 '
                "ORDER BY time ASC",
                date_str,
            )
        return [dict(r) for r in rows]
    except Exception:
        logger.debug("appt_list failed", exc_info=True)
        return []


async def appt_cancel(appt_id: str, phone: str = "") -> bool:
    pool = await _get_pool()
    if pool is None:
        return False
    # Caller-ownership scope: when a caller phone is supplied, the WHERE
    # also matches the stored number's last-10 digits, so a guessed /
    # hallucinated id can NEVER cancel another caller's booking. Empty
    # phone = unscoped (admin/manual/dashboard path) — old behavior.
    norm = "".join(c for c in (phone or "") if c.isdigit())[-10:]
    own = (
        " AND right(regexp_replace(phone, '\\D', '', 'g'), 10) = $2"
        if norm else ""
    )
    args = (appt_id, norm) if norm else (appt_id,)
    try:
        async with pool.acquire() as c:
            # Capture the row BEFORE the UPDATE so the admin notification
            # can include name/phone/date/time. The UPDATE clobbers
            # nothing we need, but we still snap the values once for the
            # alert body — single round-trip, no perf cost vs old code.
            row = await c.fetchrow(
                'SELECT date,time,name,phone,reason FROM voiceai."Appointment" '
                'WHERE id=$1' + own, *args,
            )
            if norm and not row:
                logger.info(
                    "appt_cancel refused: id=%s not owned by caller", appt_id
                )
                return False
            await c.execute(
                'UPDATE voiceai."Appointment" SET status=\'cancelled\' '
                'WHERE id=$1' + own, *args,
            )
        _booked_cache.clear()  # state changed; keep availability honest
        # Fire-and-forget admin alert.
        if row:
            try:
                from src import notify as _notify
                _notify.notify_cancel(
                    date=row["date"] or "", time_str=row["time"] or "",
                    name=row["name"] or "", phone=row["phone"] or "",
                    reason=row["reason"] or "", appt_id=appt_id,
                )
            except Exception:
                logger.debug("notify_cancel failed (non-fatal)", exc_info=True)
        return True
    except Exception:
        logger.debug("appt_cancel failed", exc_info=True)
        return False


async def appt_find_by_phone(phone: str) -> list[dict]:
    """Active (booked) upcoming appointments for a caller's number."""
    pool = await _get_pool()
    if pool is None or not phone:
        return []
    # Normalize to last 10 digits so "+919398..." and "919398..." and
    # "09398..." all match the same stored row regardless of prefix format.
    norm = "".join(c for c in phone if c.isdigit())[-10:]
    if not norm:
        return []
    try:
        async with pool.acquire() as c:
            rows = await c.fetch(
                'SELECT id,date,time,name,reason,status FROM '
                'voiceai."Appointment" '
                "WHERE right(regexp_replace(phone, '\\D', '', 'g'), 10) = $1 "
                "AND status='booked' AND date >= $2 "
                "ORDER BY date ASC, time ASC",
                norm, today_tz().isoformat(),
            )
        return [dict(r) for r in rows]
    except Exception:
        logger.debug("appt_find_by_phone failed", exc_info=True)
        return []


async def appt_reschedule(
    appt_id: str, new_date: str, new_time: str, phone: str = ""
) -> tuple[bool, str]:
    """Move an existing booking to a new free slot (atomic-ish:
    cancel old + book new only if the new slot is free)."""
    pool = await _get_pool()
    if pool is None:
        return False, "system unavailable"
    if new_time not in _all_slots():
        return False, f"{new_time} is not a valid slot"
    # fresh=True: bypass the 20s availability cache (matches appt_book
    # line ~598). Two concurrent reschedules pointing at the same slot
    # could both have passed the stale-cache check and INSERTed — fresh
    # closes that narrow window before we touch the table.
    free = await appt_available_slots(new_date, fresh=True)
    if new_time not in free:
        return False, f"{new_time} on {new_date} is not free"
    try:
        async with pool.acquire() as c:
            # Select date+time too so the reschedule notification can
            # show the old→new diff to the admin (was 2026-06-03 10:00,
            # now 2026-06-04 14:00). Without these we'd only show "to".
            # Caller-ownership scope: with a caller phone, the lookup
            # also matches the stored number — a guessed id can't move
            # someone else's booking (row comes back None → "not found").
            norm = "".join(c2 for c2 in (phone or "") if c2.isdigit())[-10:]
            own = (
                " AND right(regexp_replace(phone, '\\D', '', 'g'), 10) = $2"
                if norm else ""
            )
            sel_args = (appt_id, norm) if norm else (appt_id,)
            row = await c.fetchrow(
                'SELECT date,time,name,phone,reason,source,room,"partySize",'
                '"serviceType",notes FROM voiceai."Appointment" WHERE id=$1'
                + own,
                *sel_args,
            )
            if not row:
                return False, "appointment not found"
            # ATOMIC: cancel-old + book-new in ONE transaction. If the
            # INSERT fails (slot just taken / transient error) the cancel
            # is rolled back — the caller NEVER loses their original
            # booking with no replacement (the old non-transactional code
            # left them with neither).
            async with c.transaction():
                await c.execute(
                    'UPDATE voiceai."Appointment" SET status=\'cancelled\' '
                    "WHERE id=$1", appt_id,
                )
                # Preserve the generic optional fields on reschedule so a
                # restaurant party-size / salon service-type / notes survive
                # a day-time move.
                await c.execute(
                    'INSERT INTO voiceai."Appointment" '
                    '(id,date,time,name,phone,reason,status,source,room,'
                    '"partySize","serviceType",notes) '
                    "VALUES ($1,$2,$3,$4,$5,$6,'booked',$7,$8,$9,$10,$11)",
                    uuid.uuid4().hex, new_date, new_time, row["name"],
                    row["phone"], row["reason"], row["source"], row["room"],
                    int(row["partySize"] or 0),
                    row["serviceType"] or "",
                    row["notes"] or "",
                )
        _booked_cache.clear()  # state changed; keep availability honest
        # Fire-and-forget admin alert (after both rows are committed).
        try:
            from src import notify as _notify
            _notify.notify_reschedule(
                old_date=row["date"] or "", old_time=row["time"] or "",
                new_date=new_date, new_time=new_time,
                name=row["name"] or "", phone=row["phone"] or "",
                reason=row["reason"] or "",
            )
        except Exception:
            logger.debug("notify_reschedule failed (non-fatal)", exc_info=True)
        return True, f"moved to {new_date} {new_time}"
    except Exception as e:
        logger.debug("appt_reschedule failed", exc_info=True)
        return False, f"could not reschedule ({str(e)[:80]})"
