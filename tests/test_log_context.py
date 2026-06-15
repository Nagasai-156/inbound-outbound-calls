"""Per-call log context (`call_id` stamping) tests."""

from __future__ import annotations

import asyncio
import logging

import pytest

from src.log_context import (
    call_id_var,
    set_call_id,
    install_call_id_logging,
    _CallIdFilter,
    _NO_CALL,
)


def test_default_call_id_is_dash():
    """Outside a call, sentinel is '-' (keeps grep column-aligned)."""
    # In a brand-new context.
    assert call_id_var.get() == _NO_CALL


def test_set_call_id_in_context():
    set_call_id("test-call-123")
    assert call_id_var.get() == "test-call-123"
    # Reset for other tests.
    set_call_id("-")


def test_set_call_id_empty_resets_to_dash():
    set_call_id("real-id")
    set_call_id("")
    assert call_id_var.get() == "-"


def test_set_call_id_none_resets_to_dash():
    set_call_id("real-id")
    set_call_id(None)
    assert call_id_var.get() == "-"


def test_call_id_filter_stamps_record():
    set_call_id("filter-test")
    f = _CallIdFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=None, exc_info=None,
    )
    f.filter(record)
    assert record.call_id == "filter-test"
    set_call_id("-")


def test_call_id_filter_preserves_existing():
    """If a record already has call_id (e.g. set explicitly), don't
    overwrite."""
    f = _CallIdFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=None, exc_info=None,
    )
    record.call_id = "preset"
    f.filter(record)
    assert record.call_id == "preset"


def test_call_id_filter_always_returns_true():
    """The filter is for ENRICHMENT only — must never DROP records."""
    f = _CallIdFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=None, exc_info=None,
    )
    assert f.filter(record) is True


def test_install_call_id_logging_idempotent():
    """Calling install twice must not double-install the filter."""
    install_call_id_logging()
    install_call_id_logging()
    root = logging.getLogger()
    filters = [f for f in root.filters if isinstance(f, _CallIdFilter)]
    # Exactly one filter of our class on root.
    assert len(filters) == 1


@pytest.mark.asyncio
async def test_call_id_isolated_per_async_task():
    """Two concurrent tasks must each see their own call_id (ContextVar
    isolates per-task)."""
    async def child(cid: str, results: list):
        set_call_id(cid)
        await asyncio.sleep(0.01)
        results.append(call_id_var.get())

    r1, r2 = [], []
    await asyncio.gather(child("call-A", r1), child("call-B", r2))
    assert r1 == ["call-A"]
    assert r2 == ["call-B"]
    set_call_id("-")
