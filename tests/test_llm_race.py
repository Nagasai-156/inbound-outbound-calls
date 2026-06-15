"""Tests for the parallel LLM racing primitive (src/llm_race.py)."""

from __future__ import annotations

import asyncio

import pytest

from src.llm_race import race_async_gens


class _Gen:
    """Fake async generator: yields `items`, with `delay` before the
    FIRST item (to control who wins the race). Tracks whether it was
    closed so we can assert losers are cleaned up."""

    def __init__(self, items, first_delay=0.0, name=""):
        self._items = list(items)
        self._first_delay = first_delay
        self.name = name
        self.closed = False
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i == 0 and self._first_delay:
            await asyncio.sleep(self._first_delay)
        if self._i >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._i]
        self._i += 1
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        self.closed = True


async def _collect(gens):
    return [x async for x in race_async_gens(gens)]


def test_fastest_first_token_wins():
    fast = _Gen(["A1", "A2", "A3"], first_delay=0.0, name="fast")
    slow = _Gen(["B1", "B2"], first_delay=0.1, name="slow")
    out = asyncio.run(_collect([slow, fast]))
    assert out == ["A1", "A2", "A3"]  # fast winner streamed fully
    assert slow.closed is True        # loser closed


def test_single_gen_passthrough():
    only = _Gen(["X1", "X2"], name="only")
    out = asyncio.run(_collect([only]))
    assert out == ["X1", "X2"]


def test_empty_winner_falls_to_other():
    empty = _Gen([], first_delay=0.0, name="empty")          # ends immediately
    real = _Gen(["R1", "R2"], first_delay=0.05, name="real")
    out = asyncio.run(_collect([empty, real]))
    assert out == ["R1", "R2"]
    assert empty.closed is True


def test_first_pull_error_is_not_winner():
    boom = _Gen([RuntimeError("first-token fail")], first_delay=0.0, name="boom")
    good = _Gen(["G1", "G2"], first_delay=0.05, name="good")
    out = asyncio.run(_collect([boom, good]))
    assert out == ["G1", "G2"]
    assert boom.closed is True


def test_all_empty_yields_nothing():
    a = _Gen([], name="a")
    b = _Gen([], name="b")
    out = asyncio.run(_collect([a, b]))
    assert out == []          # caller falls back to single stream
    assert a.closed and b.closed


def test_no_gens():
    assert asyncio.run(_collect([])) == []
