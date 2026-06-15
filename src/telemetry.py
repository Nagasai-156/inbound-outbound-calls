"""Per-call telemetry -> Redis (powers the admin dashboard).

The voice worker is headless; the dashboard needs to see what's
happening. This publishes call lifecycle, live transcript, structured
context and cost metrics to Redis, and pushes a pub/sub event on every
change so the web layer can stream updates (SSE) instead of polling hard.

Redis layout:
  calls:active                 SET of call_ids currently live
  call:<id>:meta               HASH room/direction/status/lang/emotion/...
  call:<id>:transcript         LIST of JSON {role,text,ts}
  call:<id>:metrics            HASH route counts / llm / kb / bypass
  channel "calls:events"       JSON {type, call_id} on every change

All operations degrade to no-ops if Redis is unavailable — telemetry
must never break a live call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from src.config import settings

from src import db

logger = logging.getLogger("telemetry")

_TTL = 86_400  # keep ended calls visible for a day


class CallTelemetry:
    def __init__(self, call_id: str, room: str, direction: str) -> None:
        self.call_id = call_id
        self._room = room
        self._direction = direction
        self._redis = None
        # Tracked fire-and-forget persist tasks, flushed at call end so
        # the tail transcript never dies with the job teardown.
        self._tasks: set[asyncio.Task] = set()
        # The Call row MUST exist before any Transcript insert (FK +
        # cascade). start()/upsert_call is fire-and-forget, so a fast
        # first turn could insert_transcript before the row existed ->
        # FK violation -> transcript silently dropped. This guard makes
        # every turn ensure the row exactly once, race-free.
        self._call_ready = False
        self._call_lock = asyncio.Lock()
        # Per-call latency aggregates (milliseconds). Kinds: "eou",
        # "llm_ttft", "tts_ttfb". Running sum/count for avg, plus max.
        # Accurate aggregate, not a guess — feeds the dashboard's
        # per-call Latency panel.
        self._lat: dict[str, dict[str, float]] = {
            "eou":      {"sum": 0.0, "count": 0, "max": 0.0},
            "llm_ttft": {"sum": 0.0, "count": 0, "max": 0.0},
            "tts_ttfb": {"sum": 0.0, "count": 0, "max": 0.0},
            # Sub-stages hidden inside "LLM TTFT": prompt assembly
            # (markers + memory build) and the appointment-snapshot DB read.
            "assembly":    {"sum": 0.0, "count": 0, "max": 0.0},
            "snapshot_db": {"sum": 0.0, "count": 0, "max": 0.0},
            # End-to-end PERCEIVED latency: caller stops talking -> agent's
            # first audio chunk. This is THE number that decides whether a
            # call feels human (sub-800ms target). The stage metrics above
            # are diagnostics; this is the user-facing truth.
            "response": {"sum": 0.0, "count": 0, "max": 0.0},
        }
        # Per-turn RAW samples (seconds) per kind. avg/max alone lie: one
        # 21s caller-silence (STT hang) turn wrecks the mean AND owns the
        # max, so a perfectly snappy call reads "3.7s avg / 22s max". Robust
        # percentiles (p50 = the typical turn the caller feels, p95 = real
        # tail) need the full sample set. Bounded so a pathological call
        # can't grow memory unboundedly.
        self._samples: dict[str, list[float]] = {k: [] for k in self._lat}
        self._SAMPLE_CAP = 500

    def spawn(self, coro) -> None:
        """Fire-and-forget but TRACKED (so flush() can await it at end)."""
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _ensure_call(self) -> None:
        """Idempotently guarantee the Supabase Call row exists before
        any transcript insert — kills the FK race that silently lost
        transcripts on fast calls / cold pool. Crucially we ONLY mark
        the call ready on actual upsert SUCCESS — if Supabase was
        unreachable, future turns retry instead of cascading FK
        violations on a non-existent row (the cascade bug visible logs
        caught)."""
        if self._call_ready:
            return
        async with self._call_lock:
            if self._call_ready:
                return
            ok = await db.upsert_call(
                self.call_id, room=self._room,
                direction=self._direction, status="live",
            )
            self._call_ready = ok

    async def flush(self, timeout: float = 10.0) -> None:
        """Await all pending persist tasks (bounded) so every turn is
        written before the job process exits."""
        pending = {t for t in self._tasks if not t.done()}
        if not pending:
            return
        try:
            await asyncio.wait(pending, timeout=timeout)
        except Exception:
            logger.debug("telemetry flush failed", exc_info=True)

    async def _r(self):
        if self._redis is None:
            import redis.asyncio as redis

            # Tight socket timeouts so a dead Redis doesn't block live
            # telemetry writes / pub-sub for ~5-30s during a real call.
            self._redis = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        return self._redis

    async def _emit(self, etype: str) -> None:
        try:
            r = await self._r()
            await r.publish(
                "calls:events",
                json.dumps({"type": etype, "call_id": self.call_id}),
            )
        except Exception:
            logger.debug("telemetry emit failed", exc_info=True)

    async def start(self) -> None:
        # Pipeline 3 ops + publish into 1 round-trip — at crore-scale this
        # saves ~5-10ms per call setup × millions of calls.
        try:
            r = await self._r()
            async with r.pipeline(transaction=False) as p:
                p.sadd("calls:active", self.call_id)
                p.hset(
                    f"call:{self.call_id}:meta",
                    mapping={
                        "room": self._room,
                        "direction": self._direction,
                        "status": "live",
                        "started_at": str(time.time()),
                    },
                )
                p.publish(
                    "calls:events",
                    json.dumps({"type": "start", "call_id": self.call_id}),
                )
                await p.execute()
        except Exception:
            logger.debug("telemetry start failed", exc_info=True)
        await db.upsert_call(
            self.call_id, room=self._room, direction=self._direction,
            status="live",
        )

    async def turn(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # De-dupe: the same agent line can arrive from both _say() and
        # the conversation_item_added handler (and partial->final). Drop
        # an immediate repeat / prefix of the last logged turn.
        last = getattr(self, "_last_turn", None)
        if last and last[0] == role:
            a, b = last[1], text
            if a == b or a.startswith(b) or b.startswith(a):
                return
        self._last_turn = (role, text)
        # Pipeline rpush + ltrim + expire + publish into 1 round-trip.
        # 4 Redis ops per turn → 1; at 10M calls × 6 turns avg this saves
        # ~180M individual round-trips × ~2ms each = ~360k seconds total
        # network time. Real win at crore-scale.
        try:
            r = await self._r()
            key = f"call:{self.call_id}:transcript"
            async with r.pipeline(transaction=False) as p:
                p.rpush(
                    key,
                    json.dumps({"role": role, "text": text, "ts": time.time()}),
                )
                p.ltrim(key, -200, -1)
                p.expire(key, _TTL)
                p.publish(
                    "calls:events",
                    json.dumps({"type": "turn", "call_id": self.call_id}),
                )
                await p.execute()
        except Exception:
            logger.warning("telemetry redis turn failed", exc_info=True)
        # Guarantee the Call row exists first (FK), THEN persist the
        # transcript — so a turn is never silently dropped on a race.
        # Wrapped in visible logging so any DB failure is OBSERVABLE in
        # worker.err.log (the old logger.debug ate every failure
        # silently — the recurring "transcript missed" bug).
        try:
            await self._ensure_call()
            await db.insert_transcript(self.call_id, role, text)
        except Exception:
            logger.warning(
                "transcript persist FAILED call=%s role=%s len=%d",
                self.call_id, role, len(text), exc_info=True,
            )

    async def update_context(self, memory) -> None:
        """Snapshot structured memory (language/emotion/intent/name)."""
        # Pipeline hset + expire + publish into 1 round-trip.
        try:
            r = await self._r()
            async with r.pipeline(transaction=False) as p:
                p.hset(
                    f"call:{self.call_id}:meta",
                    mapping={
                        "language": memory.language,
                        "emotion": memory.emotion,
                        "intent": memory.intent,
                        "name": memory.name or "",
                    },
                )
                p.expire(f"call:{self.call_id}:meta", _TTL)
                p.publish(
                    "calls:events",
                    json.dumps({"type": "context", "call_id": self.call_id}),
                )
                await p.execute()
        except Exception:
            logger.debug("telemetry context failed", exc_info=True)
        await db.upsert_call(
            self.call_id, room=self._room, direction=self._direction,
            language=memory.language, emotion=memory.emotion,
            intent=memory.intent, caller_name=memory.name or "",
        )

    def record_latency(self, kind: str, seconds: float) -> None:
        """Accumulate a per-turn latency sample for this call. `kind` is
        one of: 'eou' (endpointing), 'llm_ttft' (LLM first token),
        'tts_ttfb' (TTS first audio), 'response' (end-to-end perceived:
        caller stops -> agent first audio). Negative/zero samples are kept
        (count) but don't move max — useful for "ttft was instant" turns.
        Pure in-memory math; persistence happens in update_metrics."""
        if kind not in self._lat or seconds is None:
            return
        try:
            s = float(seconds)
        except (TypeError, ValueError):
            return
        if s < 0:
            return
        slot = self._lat[kind]
        slot["sum"] += s
        slot["count"] += 1
        if s > slot["max"]:
            slot["max"] = s
        samp = self._samples.get(kind)
        if samp is not None and len(samp) < self._SAMPLE_CAP:
            samp.append(s)

    # Real system endpointing is bounded by max_endpointing_delay (~0.5s)
    # plus STT finalisation (~1-2s). An eou beyond this ceiling is the
    # CALLER pausing/thinking or an STT hang — NOT latency our pipeline
    # added — so it's excluded from the "responsive" number and counted
    # separately. (Live call out-913f9ad497 had a 21.95s eou = caller
    # silence; including it made avg/max meaningless.)
    _EOU_SYSTEM_CEILING_S = 3.0

    @staticmethod
    def _pct(vals_sorted: list[float], q: float) -> float:
        """Linear-interpolated percentile (q in [0,1]) of a sorted list."""
        n = len(vals_sorted)
        if n == 0:
            return 0.0
        if n == 1:
            return vals_sorted[0]
        pos = q * (n - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return vals_sorted[lo] * (1 - frac) + vals_sorted[hi] * frac

    def _latency_payload(self) -> dict[str, int]:
        """Snapshot per-call latency as ms ints. Reports BOTH the legacy
        avg/max (DB back-compat) AND robust p50/p95 percentiles, which are
        what the dashboard now shows — p50 = the typical turn the caller
        feels, p95 = the realistic tail (immune to a single caller-pause
        outlier). Endpointing additionally gets a 'responsive' p50/p95 with
        caller-pause/STT-hang turns removed, plus the count of those turns,
        so the number is 100% attributable to our pipeline."""
        out: dict[str, int] = {}
        for kind, slot in self._lat.items():
            count = int(slot["count"])
            avg_ms = round((slot["sum"] / count) * 1000) if count else 0
            max_ms = round(slot["max"] * 1000)
            out[f"avg_{kind}_ms"] = avg_ms
            out[f"max_{kind}_ms"] = max_ms
            samp = sorted(self._samples.get(kind, []))
            out[f"p50_{kind}_ms"] = round(self._pct(samp, 0.50) * 1000)
            out[f"p95_{kind}_ms"] = round(self._pct(samp, 0.95) * 1000)
        # Endpointing with caller-pause/STT-hang anomalies stripped out.
        eou = self._samples.get("eou", [])
        resp = sorted(s for s in eou if s <= self._EOU_SYSTEM_CEILING_S)
        out["p50_eou_resp_ms"] = round(self._pct(resp, 0.50) * 1000)
        out["p95_eou_resp_ms"] = round(self._pct(resp, 0.95) * 1000)
        out["caller_wait_turns"] = sum(
            1 for s in eou if s > self._EOU_SYSTEM_CEILING_S
        )
        out["responsive_turns"] = len(resp)
        return out

    async def update_metrics(self, meter) -> None:
        lat = self._latency_payload()
        # Pipeline hset + expire into 1 round-trip.
        try:
            r = await self._r()
            async with r.pipeline(transaction=False) as p:
                p.hset(
                    f"call:{self.call_id}:metrics",
                    mapping={
                        "turns": sum(meter.routes.values()),
                        "llm_calls": meter.llm_calls,
                        "kb_calls": meter.kb_calls,
                        "bypass_rate": round(meter.llm_bypass_rate, 3),
                        "routes": json.dumps(dict(meter.routes)),
                        "avg_eou_ms": lat["avg_eou_ms"],
                        "max_eou_ms": lat["max_eou_ms"],
                        "avg_llm_ttft_ms": lat["avg_llm_ttft_ms"],
                        "max_llm_ttft_ms": lat["max_llm_ttft_ms"],
                        "avg_tts_ttfb_ms": lat["avg_tts_ttfb_ms"],
                        "max_tts_ttfb_ms": lat["max_tts_ttfb_ms"],
                        # End-to-end perceived latency (live dashboard).
                        "avg_response_ms": lat["avg_response_ms"],
                        "max_response_ms": lat["max_response_ms"],
                        # Robust percentiles — what the dashboard now shows.
                        # p50 = typical turn, p95 = realistic tail, plus the
                        # caller-pause-stripped 'responsive' endpointing.
                        "p50_eou_ms": lat["p50_eou_ms"],
                        "p95_eou_ms": lat["p95_eou_ms"],
                        "p50_eou_resp_ms": lat["p50_eou_resp_ms"],
                        "p95_eou_resp_ms": lat["p95_eou_resp_ms"],
                        "caller_wait_turns": lat["caller_wait_turns"],
                        "responsive_turns": lat["responsive_turns"],
                        "p50_llm_ttft_ms": lat["p50_llm_ttft_ms"],
                        "p95_llm_ttft_ms": lat["p95_llm_ttft_ms"],
                        "p50_tts_ttfb_ms": lat["p50_tts_ttfb_ms"],
                        "p95_tts_ttfb_ms": lat["p95_tts_ttfb_ms"],
                        "p50_assembly_ms": lat["p50_assembly_ms"],
                        "p95_assembly_ms": lat["p95_assembly_ms"],
                        "p50_snapshot_db_ms": lat["p50_snapshot_db_ms"],
                        "p95_snapshot_db_ms": lat["p95_snapshot_db_ms"],
                        "p50_response_ms": lat["p50_response_ms"],
                        "p95_response_ms": lat["p95_response_ms"],
                    },
                )
                p.expire(f"call:{self.call_id}:metrics", _TTL)
                await p.execute()
        except Exception:
            logger.debug("telemetry metrics failed", exc_info=True)
        await db.upsert_call(
            self.call_id, room=self._room, direction=self._direction,
            turns=sum(meter.routes.values()), llm_calls=meter.llm_calls,
            kb_calls=meter.kb_calls,
            bypass_rate=round(meter.llm_bypass_rate, 3),
            avg_eou_ms=lat["avg_eou_ms"],
            max_eou_ms=lat["max_eou_ms"],
            avg_llm_ttft_ms=lat["avg_llm_ttft_ms"],
            max_llm_ttft_ms=lat["max_llm_ttft_ms"],
            avg_tts_ttfb_ms=lat["avg_tts_ttfb_ms"],
            max_tts_ttfb_ms=lat["max_tts_ttfb_ms"],
            avg_assembly_ms=lat["avg_assembly_ms"],
            max_assembly_ms=lat["max_assembly_ms"],
            avg_snapshot_ms=lat["avg_snapshot_db_ms"],
            max_snapshot_ms=lat["max_snapshot_db_ms"],
        )

    async def _replay_missing_transcripts(self) -> None:
        """Durable safety net: if the conversation reached Redis (always
        up — hot path) but Supabase fell behind for ANY reason (FK race,
        pool blip, silent fail), back-fill the missing tail at end. This
        is the structural guarantee that "transcript not stored" can't
        recur — Redis IS the source-of-truth buffer; Supabase is just a
        reconciliation target."""
        try:
            r = await self._r()
            items = await r.lrange(f"call:{self.call_id}:transcript", 0, -1)
            if not items:
                return
            db_count = await db.transcript_count(self.call_id)
            if len(items) <= db_count:
                return  # Supabase has them all
            await self._ensure_call()  # FK safety before back-fill
            missing = items[db_count:]
            backfilled = 0
            failed = 0
            for raw in missing:
                try:
                    t = json.loads(raw)
                    ok = await db.insert_transcript(
                        self.call_id, t.get("role", ""), t.get("text", "")
                    )
                    # Count TRUE successes only — the old code counted
                    # attempts, so logs claimed "back-filled 10" while
                    # Supabase still had 0 (cascading FK fails). bool
                    # gating makes the metric honest.
                    if ok:
                        backfilled += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                    logger.warning("replay row exception", exc_info=True)
            if backfilled or failed:
                logger.warning(
                    "transcript REPLAY for %s: back-filled=%d failed=%d "
                    "(Redis had %d, Supabase had %d before)",
                    self.call_id, backfilled, failed, len(items), db_count,
                )
        except Exception:
            logger.warning("transcript replay failed", exc_info=True)

    async def end(self) -> None:
        # Flush every pending transcript/turn write BEFORE teardown —
        # add_shutdown_callback awaits this, so the tail of the call is
        # guaranteed in Supabase even on an abrupt hangup.
        await self.flush()
        # Safety net: any turn that reached Redis but didn't reach
        # Supabase (silent FK / pool blip / etc.) — back-fill now.
        await self._replay_missing_transcripts()
        # Pipeline 5 ops at call-end into 1 round-trip.
        try:
            r = await self._r()
            async with r.pipeline(transaction=False) as p:
                p.srem("calls:active", self.call_id)
                p.hset(
                    f"call:{self.call_id}:meta",
                    mapping={
                        "status": "ended",
                        "ended_at": str(time.time()),
                    },
                )
                p.expire(f"call:{self.call_id}:meta", _TTL)
                p.publish(
                    "calls:events",
                    json.dumps({"type": "end", "call_id": self.call_id}),
                )
                await p.execute()
        except Exception:
            logger.debug("telemetry end failed", exc_info=True)
        await db.end_call(self.call_id)
