"""Worker supervisor — keeps the LiveKit agent ALWAYS registered.

The #1 production failure for this system is silent: a network / DNS /
battery-saver blip makes the worker fail `getaddrinfo`, exhaust its
reconnect retries, then sit as a ZOMBIE — process alive but NOT
registered with LiveKit Cloud. Calls then connect at the phone layer
with no agent in the room = dead air, until someone manually restarts.

This watchdog OWNS the worker as a child process. Since agent.py now
sets max_retry≈100000, the worker SELF-HEALS any network/DNS blip on its
own (reconnect backoff caps at 10s/attempt) — so a restart is wasteful
(20-45s cold model reload) and useless during an outage. The watchdog
therefore treats two failure classes very differently:

  * child exits            -> respawn immediately (process is gone).
  * HARD-DOWN: the health endpoint (GET http://127.0.0.1:<port>/)
    returns an explicit HTTP 503 (inference subprocess dead, or the
    LiveKit connection permanently failed). Unambiguous — a fresh
    process is the ONLY recovery -> kill+respawn fast (2 strikes ≈ 20s).
    An *unreachable* endpoint is deliberately NOT hard-down: during
    cold start model-loading saturates the event loop so the health
    server can't answer for 30-90s though the worker is fine and
    registering — treating that as a kill murdered healthy workers.
  * SOFT / RECONNECTING: the log shows it's not registered (or the
    probe just can't reach a still-booting/busy worker). Could be
    normal self-healing — restarting can't fix a down network and only
    adds dead air. So BE PATIENT: let it reconnect on its own, and only
    force a last-resort restart if it stays continuously down for
    SOFT_UNREG_GRACE past the startup grace (clears any stale
    resolver/socket state after a very long outage).
  * worker.err.log is truncated on every (re)start so the health
    signature only ever reflects the CURRENT worker instance, and the
    log can't grow unbounded.

Run it INSTEAD of launching the worker directly:

    python scripts/watchdog.py

Stop with Ctrl+C (it terminates the child too). For real deployment
this same role should be a service (NSSM / systemd / Docker restart
policy) — this script is the interim, dependency-free equivalent.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERR_LOG = ROOT / "worker.err.log"
OUT_LOG = ROOT / "worker.log"
WD_LOG = ROOT / "watchdog.log"

# LiveKit's built-in worker health server. agent.py pins it to
# 127.0.0.1:<LIVEKIT_WORKER_PORT> (default 8082). GET / returns 200 "OK"
# only while registered; 503 the instant the Cloud connection fails.
HEALTH_PORT = int(os.environ.get("LIVEKIT_WORKER_PORT", "8082"))
HEALTH_URL = f"http://127.0.0.1:{HEALTH_PORT}/"
HEALTH_TIMEOUT = 4           # seconds for the probe itself

CHECK_INTERVAL = 10          # seconds between health checks
STARTUP_GRACE = 90           # don't judge health until the worker has
                             # loaded models + registered. 45s was too
                             # short on this host — the worker registered
                             # but the watchdog killed it mid-boot. Model
                             # load + event-loop saturation can exceed
                             # 60s, so give it 90s.
# HARD-down (explicit HTTP 503 = inference dead / connection permanently
# failed): a fresh process is the only fix -> restart fast.
HARD_STRIKES = 2             # consecutive checks (~20s) before kill
# SOFT (alive + HTTP up, just reconnecting): the worker self-heals, so
# tolerate a long continuous outage before a last-resort restart. This
# is the fix for the kill+respawn LOOP — the watchdog was cold-
# restarting a worker every ~30s that would have reconnected by itself.
SOFT_UNREG_GRACE = 360       # seconds continuously unregistered (soft)
                             # before a last-resort kill + respawn
SOFT_HEARTBEAT = 60          # log "still reconnecting" at most this often
REGISTERED = "registered worker"
# livekit-agents logs this on EVERY failed (re)connect attempt — a
# runtime websocket drop ("worker connection closed unexpectedly")
# funnels through the same retry path, so this line reappears after the
# last "registered worker" the instant the worker loses its slot. This
# is the accurate "currently unregistered" signal and is independent of
# max_retry (the old "...after N attempts" marker only ever printed once
# the retry budget was exhausted — which, with max_retry now ~infinite,
# would essentially never fire, so a reconnecting zombie went undetected).
FATAL_MARKERS = (
    "failed to connect to livekit, retrying",
    "failed to connect to livekit after",
    "getaddrinfo failed",
)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(WD_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _rotate(path: Path, keep: int = 10) -> None:
    """Rotate `path` → `path.1`, `.1` → `.2`, … keeping the most recent
    `keep` generations. Used instead of wiping the log on each spawn so
    crash evidence (Tracebacks, timing instrumentation, last-words before
    a hang) survives the next watchdog respawn — diagnostic blind spot
    fix.

    The CURRENT-instance log (path itself) is still freshly opened by
    spawn(), so the watchdog's `process object is closed` counter and
    'registered worker' freshness checks (which scan path) still reflect
    ONLY this instance's lines, exactly as before.
    """
    try:
        if not path.exists():
            return
        # Walk DOWN from oldest to make room: keep-1 → keep (drop),
        # keep-2 → keep-1, … 1 → 2.
        oldest = path.with_suffix(path.suffix + f".{keep}")
        if oldest.exists():
            try:
                oldest.unlink()
            except Exception:
                pass
        for i in range(keep - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".{i}")
            if src.exists():
                src.rename(path.with_suffix(path.suffix + f".{i + 1}"))
        path.rename(path.with_suffix(path.suffix + ".1"))
    except Exception as e:
        # Rotation failure must NOT block worker spawn — fall back to
        # the old wipe behavior so an existing handle / locked file does
        # not stop calls from being answered.
        log(f"log rotate failed for {path.name}: {e!r} (falling back to wipe)")


def spawn() -> subprocess.Popen:
    """Start a fresh worker. Logs are ROTATED (not wiped) so the previous
    instance's stack trace + tool-timing instrumentation survive into
    `worker.log.1` / `worker.err.log.1` for post-mortem."""
    _rotate(OUT_LOG)
    _rotate(ERR_LOG)
    out = open(OUT_LOG, "w", encoding="utf-8", errors="ignore")
    err = open(ERR_LOG, "w", encoding="utf-8", errors="ignore")
    creationflags = 0
    if os.name == "nt":
        # New process group so Ctrl+C to the watchdog doesn't race the
        # child; we terminate it explicitly.
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    # UTF-8 stdout/stderr in the child so Telugu/Hindi text in log
    # messages doesn't trigger cp1252 UnicodeEncodeError on Windows —
    # those errors were masking real failures (book_appointment errors,
    # mishear-loop traces) by corrupting the log chain.
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "src.agent", "start"],
        cwd=str(ROOT),
        stdout=out,
        stderr=err,
        creationflags=creationflags,
        env=env,
    )
    log(f"worker spawned pid={p.pid}")
    return p


def _probe_hard_down() -> bool:
    """ONLY an explicit HTTP 503 counts as hard-down (LiveKit's health
    endpoint reporting: inference subprocess dead, or the connection
    permanently failed). That is unambiguous and a fresh process is the
    only fix.

    A 200 does NOT prove "registered" (with high max_retry the endpoint
    stays 200 during the whole reconnect loop) — registration is judged
    from the log instead.

    CRITICAL: an *unreachable* endpoint is NOT treated as hard-down.
    During cold start the worker loads models for 30-90s and the event
    loop is so saturated that its own aiohttp health server can't answer
    within the timeout — the worker is perfectly fine and about to
    register. Treating that as a fast hard-kill made the watchdog
    murder healthy, already-registering workers in a respawn loop. So
    unreachable -> defer to the log/SOFT path (a genuinely wedged loop
    drops the LiveKit ws too, which the log's reconnect signal catches,
    and the SOFT grace still bounds it).

    ALSO hard-down: the inference subprocess silently dies (LiveKit's
    aiohttp health server keeps returning 200, but every health probe
    triggers `process object is closed`). Once enough of those errors
    accumulate in the log, the agent can no longer detect turns / speak
    — callers experience ghosting + slow responses. Detected by log-grep
    threshold (cheaper than a probe that returns 200 anyway)."""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=HEALTH_TIMEOUT) as r:
            if r.status == 503:
                return True
    except urllib.error.HTTPError as e:
        if e.code == 503:
            return True
    except urllib.error.URLError:
        pass  # unreachable: slow boot or busy loop — NOT hard
    except Exception:
        pass  # inconclusive -> let the log decide
    # Zombie inference-subprocess detection: aiohttp returns 200 but
    # every probe raises `process object is closed` inside is_alive().
    # When this count grows past a small threshold in the CURRENT log
    # (truncated on every spawn so the count reflects this instance),
    # the worker is non-functional even though HTTP says fine — restart.
    try:
        txt = ERR_LOG.read_text(encoding="utf-8", errors="ignore")
        if txt.count("process object is closed") >= 10:
            return True
    except Exception:
        pass
    return False


def _log_unregistered() -> bool:
    """True if the worker is CURRENTLY not registered: the most recent
    connect-failure / retry line is newer than the most recent
    'registered worker' (or it never registered). A successful reconnect
    logs a fresh 'registered worker', which flips this back to healthy —
    so this tracks live state, not just a one-time startup failure."""
    try:
        txt = ERR_LOG.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    reg_idx = txt.rfind(REGISTERED)
    fatal_idx = max(txt.rfind(m) for m in FATAL_MARKERS)
    if fatal_idx == -1:
        return False
    return fatal_idx > reg_idx


def stop(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    try:
        if os.name == "nt":
            p.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            p.terminate()
        p.wait(timeout=8)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def main() -> None:
    log("watchdog start")
    p = spawn()
    started = time.time()
    hard_strikes = 0          # consecutive HARD-down checks
    soft_since = 0.0          # monotonic ts the SOFT outage began (0=none)

    def _restart(reason: str) -> None:
        nonlocal p, started, hard_strikes, soft_since
        log(reason)
        stop(p)
        p = spawn()
        started = time.time()
        hard_strikes = 0
        soft_since = 0.0

    try:
        while True:
            time.sleep(CHECK_INTERVAL)

            if p.poll() is not None:
                log(f"worker exited (code={p.returncode}) -> respawn")
                p = spawn()
                started = time.time()
                hard_strikes = 0
                soft_since = 0.0
                continue

            if time.time() - started < STARTUP_GRACE:
                hard_strikes = 0
                soft_since = 0.0
                continue  # still warming up; don't judge yet

            if _probe_hard_down():
                # Explicit HTTP 503: normally means inference subprocess
                # dead or LiveKit connection permanently failed.
                # EXCEPTION: if the worker IS currently registered with
                # LiveKit, the 503 is the known framework false-alarm
                # (inference_executor.is_alive() raises ValueError after
                # its init subprocess closes — LiveKit bug). Killing a
                # registered, call-handling worker for this is wrong.
                if not _log_unregistered():
                    hard_strikes = 0
                    soft_since = 0.0
                    continue
                hard_strikes += 1
                soft_since = 0.0
                log(f"HARD-down check {hard_strikes}/{HARD_STRIKES} "
                    "(HTTP 503)")
                if hard_strikes >= HARD_STRIKES:
                    _restart("hard-down -> kill + respawn")
            elif _log_unregistered():
                # Alive, HTTP server up, just reconnecting. The worker
                # self-heals (max_retry≈100000) — DON'T cold-restart it;
                # a restart can't fix a down network and only adds dead
                # air. Wait it out; last-resort restart only if it stays
                # down for SOFT_UNREG_GRACE.
                hard_strikes = 0
                now = time.time()
                if soft_since == 0.0:
                    soft_since = now
                    log("worker reconnecting (not registered) — letting "
                        "it self-heal, no restart")
                waited = now - soft_since
                if waited >= SOFT_UNREG_GRACE:
                    _restart(
                        f"unregistered {int(waited)}s "
                        f"(> {SOFT_UNREG_GRACE}s) — self-heal not working, "
                        "last-resort kill + respawn"
                    )
                elif (waited >= SOFT_HEARTBEAT
                      and int(waited) % SOFT_HEARTBEAT < CHECK_INTERVAL):
                    log(f"still reconnecting {int(waited)}s/"
                        f"{SOFT_UNREG_GRACE}s — worker self-healing, "
                        "holding restart")
            else:
                if hard_strikes or soft_since:
                    log("worker healthy / re-registered")
                hard_strikes = 0
                soft_since = 0.0
    except KeyboardInterrupt:
        log("watchdog stopping -> terminating worker")
        stop(p)


if __name__ == "__main__":
    main()
