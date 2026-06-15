"""Tail guard: never speak a half-sentence when the LLM output is
hard-stopped at the token cap (live bug 2026-06-12: reply ended at
out=156/160 with "...అండి. మీకు" then silence).

Tests drive VoiceAgent._guard_truncated_tail directly with fake chunks —
no network, no livekit session.
"""

from __future__ import annotations

import os

import pytest

from src.agent import VoiceAgent


class _Delta:
    def __init__(self, content=None):
        self.content = content
        self.role = "assistant"


class _Chunk:
    def __init__(self, content=None, id="c1"):
        self.id = id
        self.delta = _Delta(content)


async def _drive(chunks):
    async def src():
        for c in chunks:
            yield c

    out = []
    # unbound coroutine — self is unused except for logger access
    async for ch in VoiceAgent._guard_truncated_tail(None, src()):
        c = getattr(getattr(ch, "delta", None), "content", None)
        if c:
            out.append(c)
    return "".join(out)


@pytest.mark.asyncio
async def test_complete_reply_passes_through_unchanged():
    text = await _drive([_Chunk("సరే అండి. "), _Chunk("రేపు కలుద్దాం.")])
    assert text == "సరే అండి. రేపు కలుద్దాం."


@pytest.mark.asyncio
async def test_short_unterminated_tail_is_flushed_when_not_truncated():
    # Output well under the cap -> the model ended on its own; flush tail.
    text = await _drive([_Chunk("Okay sir, see you tomorrow")])
    assert text == "Okay sir, see you tomorrow"


@pytest.mark.asyncio
async def test_truncated_tail_is_dropped(monkeypatch):
    # Force a tiny cap so the output counts as "at the cap".
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "30")
    long_text = (
        "మా క్లినిక్ జూబ్లీహిల్స్ లో ఉంది అండి. మెట్రో స్టేషన్ దగ్గరే చాలా "
        "సులభంగా చేరుకోవచ్చు అండి. మీకు"
    )
    text = await _drive([_Chunk(long_text)])
    assert text.endswith("అండి.")
    assert not text.endswith("మీకు")


@pytest.mark.asyncio
async def test_tool_call_chunks_pass_through():
    class _ToolChunk:
        id = "t1"
        delta = _Delta(None)

    chunks = [_Chunk("Booking it. "), _ToolChunk(), _Chunk("Done.")]

    async def src():
        for c in chunks:
            yield c

    seen = []
    async for ch in VoiceAgent._guard_truncated_tail(None, src()):
        seen.append(ch)
    assert any(isinstance(c, _ToolChunk) for c in seen)
