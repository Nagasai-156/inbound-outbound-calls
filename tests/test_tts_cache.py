"""Tests for the in-process TTS audio cache (multimodal cache).

Verifies the cache renders a phrase once, replays cached audio on
subsequent calls (no second synth), keys by voice, bounds memory (LRU),
bypasses long/dynamic text, and falls back to live synth on render
failure. Uses fakes — no live network / livekit runtime needed.
"""

from __future__ import annotations

import pytest

from src import tts_cache


# ── Fakes ────────────────────────────────────────────────────────────
class FakeFrame:
    def __init__(self, data: bytes, sr: int = 24000, ch: int = 1):
        self.data = data
        self.sample_rate = sr
        self.num_channels = ch
        self.samples_per_channel = max(1, len(data) // 2)


class FakeSynthAudio:
    def __init__(self, frame):
        self.frame = frame


class FakeChunkedStream:
    def __init__(self, frames):
        self._frames = frames
        self.closed = False

    def __aiter__(self):
        self._it = iter(self._frames)
        return self

    async def __anext__(self):
        try:
            return FakeSynthAudio(next(self._it))
        except StopIteration:
            raise StopAsyncIteration

    async def aclose(self):
        self.closed = True


class FakeTTS:
    def __init__(self, frames):
        self._frames = frames
        self.synth_calls = 0

    def synthesize(self, text):
        self.synth_calls += 1
        return FakeChunkedStream(list(self._frames))


class FakeSession:
    def __init__(self):
        self.say_calls = []

    async def say(self, text, *, audio=None, allow_interruptions=True,
                  add_to_chat_ctx=True):
        played = None
        if audio is not None:
            played = [f async for f in audio]
        self.say_calls.append(
            {"text": text, "had_audio": audio is not None, "frames": played}
        )
        return object()  # stand-in SpeechHandle


# rtc.AudioFrame is needed for _rebuild_frames. Patch the rebuild to use
# FakeFrame so we don't require a livekit runtime in CI.
@pytest.fixture(autouse=True)
def _patch_rebuild(monkeypatch):
    def _rebuild(tuples):
        return [FakeFrame(d, sr, ch) for (d, sr, ch, _spc) in tuples]
    monkeypatch.setattr(tts_cache, "_rebuild_frames", _rebuild)
    tts_cache.clear_cache()
    yield
    tts_cache.clear_cache()


@pytest.mark.asyncio
async def test_first_call_renders_and_caches():
    tts = FakeTTS([FakeFrame(b"\x01\x02"), FakeFrame(b"\x03\x04")])
    session = FakeSession()
    await tts_cache.say_cached(
        session, tts, "hmm okay andi",
        model="bulbul:v2", speaker="anushka", language="te",
    )
    assert tts.synth_calls == 1
    assert tts_cache.cache_stats()["entries"] == 1
    assert session.say_calls[0]["had_audio"] is True
    assert len(session.say_calls[0]["frames"]) == 2


@pytest.mark.asyncio
async def test_second_call_replays_without_resynth():
    tts = FakeTTS([FakeFrame(b"\x01\x02")])
    session = FakeSession()
    args = dict(model="bulbul:v2", speaker="anushka", language="te")
    await tts_cache.say_cached(session, tts, "thanks andi", **args)
    await tts_cache.say_cached(session, tts, "thanks andi", **args)
    # Rendered only once; second call served from cache.
    assert tts.synth_calls == 1
    assert len(session.say_calls) == 2
    assert all(c["had_audio"] for c in session.say_calls)


@pytest.mark.asyncio
async def test_different_voice_is_a_separate_entry():
    tts = FakeTTS([FakeFrame(b"\x01\x02")])
    session = FakeSession()
    await tts_cache.say_cached(
        session, tts, "namaste", model="bulbul:v2",
        speaker="anushka", language="hi",
    )
    await tts_cache.say_cached(
        session, tts, "namaste", model="bulbul:v2",
        speaker="vidya", language="hi",
    )
    assert tts.synth_calls == 2
    assert tts_cache.cache_stats()["entries"] == 2


@pytest.mark.asyncio
async def test_long_text_bypasses_cache():
    tts = FakeTTS([FakeFrame(b"\x01\x02")])
    session = FakeSession()
    long_text = "word " * 100  # > max_chars
    await tts_cache.say_cached(
        session, tts, long_text, model="bulbul:v2",
        speaker="anushka", language="en", max_chars=160,
    )
    # No synth via the cache, no cache entry, played via normal path.
    assert tts.synth_calls == 0
    assert tts_cache.cache_stats()["entries"] == 0
    assert session.say_calls[0]["had_audio"] is False


@pytest.mark.asyncio
async def test_empty_render_falls_back_to_live_synth():
    tts = FakeTTS([])  # provider returns no frames
    session = FakeSession()
    await tts_cache.say_cached(
        session, tts, "ok", model="bulbul:v2",
        speaker="anushka", language="en",
    )
    # Nothing cached; spoken via the normal (audio=None) path.
    assert tts_cache.cache_stats()["entries"] == 0
    assert session.say_calls[0]["had_audio"] is False


@pytest.mark.asyncio
async def test_lru_eviction_bounds_memory(monkeypatch):
    monkeypatch.setattr(tts_cache, "_MAX_ENTRIES", 3)
    tts = FakeTTS([FakeFrame(b"\x01\x02")])
    session = FakeSession()
    for i in range(5):
        await tts_cache.say_cached(
            session, tts, f"phrase {i}", model="m", speaker="s",
            language="en",
        )
    assert tts_cache.cache_stats()["entries"] <= 3


@pytest.mark.asyncio
async def test_empty_text_is_noop():
    tts = FakeTTS([FakeFrame(b"\x01")])
    session = FakeSession()
    res = await tts_cache.say_cached(
        session, tts, "   ", model="m", speaker="s", language="en",
    )
    assert res is None
    assert tts.synth_calls == 0
    assert not session.say_calls
