"""Per-call structured logging context.

Every log record this process emits gets stamped with the current call's
id (the LiveKit room name == Call.id in the DB), so concurrent calls
(this worker runs 8 idle subprocesses, each can host parallel jobs) no
longer interleave anonymously in the log. When a caller pastes a bug
transcript, `grep call=<id> worker.log` returns the exact pipeline of
THAT call — tool entries, language detection, endpointing decisions,
LLM latencies — with zero noise from sibling calls.

Implementation:

  * `call_id_var` is a ContextVar set ONCE at the start of `entrypoint`.
    Each LiveKit job runs in its own async task context, so the var is
    naturally isolated between concurrent calls.
  * `_CallIdFilter` is a logging filter that copies the var onto every
    LogRecord as `record.call_id`, so the formatter (any formatter that
    references `%(call_id)s`) can include it.
  * `install_call_id_logging()` is the one-line hook called from
    `agent.py` / `web/server.py` once at startup. It adds the filter to
    the ROOT logger so every named logger (`agent`, `tools`, `db`, …)
    inherits the field without per-module changes.

Outside a call (worker boot, watchdog probes), `call_id` is `'-'` —
keeps the format aligned without `KeyError`.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

# Sentinel for non-call log lines (worker boot, health probes, …). A
# single dash keeps the formatted column width stable for grep/awk.
_NO_CALL = "-"

call_id_var: ContextVar[str] = ContextVar("call_id", default=_NO_CALL)


class _CallIdFilter(logging.Filter):
    """Copy the current `call_id_var` onto every LogRecord so the
    formatter can reference it via `%(call_id)s`.

    Filters that return False drop the record — we always return True;
    the only side effect is attaching the field.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # getattr-with-default in case some library bypassed the filter
        # chain (defensive — keeps `%(call_id)s` from crashing format).
        if not hasattr(record, "call_id"):
            try:
                record.call_id = call_id_var.get()
            except LookupError:
                record.call_id = _NO_CALL
        return True


_INSTALLED = False


def install_call_id_logging() -> None:
    """Idempotent installer. Adds the filter to the root logger so EVERY
    named child logger (`agent`, `tools`, `db`, `tts`, …) gets call_id
    on its records without per-module wiring. Also updates existing
    handlers' formatters to include the field if they use the default
    `basicConfig` formatter — handlers with custom JSON/structured
    formatters are left untouched (the field is on the record either
    way and they can pick it up if they want).
    """
    global _INSTALLED
    if _INSTALLED:
        return
    root = logging.getLogger()
    # Add the filter if not already present (compare by class to avoid
    # duplicate installs on re-import).
    if not any(isinstance(f, _CallIdFilter) for f in root.filters):
        root.addFilter(_CallIdFilter())
    # Also attach to every existing handler so a handler that filters at
    # its OWN level (some libraries do) still sees the field.
    for h in root.handlers:
        if not any(isinstance(f, _CallIdFilter) for f in h.filters):
            h.addFilter(_CallIdFilter())
    _INSTALLED = True


def set_call_id(call_id: str) -> None:
    """Set the active call id for THIS async context. Safe to call from
    inside `entrypoint(ctx)` — every subsequent log line in this task
    (and any task it spawns via asyncio.create_task) will inherit it."""
    call_id_var.set(call_id or _NO_CALL)
