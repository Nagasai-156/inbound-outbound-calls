"""In-process TTS audio cache — the "multimodal cache" optimisation.

Fixed, frequently-repeated short phrases — fillers ("hmm, okay అండి"),
canned replies (greeting / thanks / bye / "please repeat"), and warm
cache answers — are re-synthesised by the TTS provider on EVERY use,
paying the full first-byte latency (~270-460ms on Sarvam from India)
each time for audio that never changes.

This caches the rendered audio FRAMES the first time a phrase is spoken
for a given voice, then replays them via `session.say(text, audio=...)`
on subsequent uses — skipping the TTS round-trip entirely. On these
turns the only remaining latency is network playout, not synthesis.

Correctness / safety:
  * Keyed by (tts_model, speaker, language, text) so a voice/speaker
    switch never replays stale audio in the wrong voice.
  * In-process only (per worker), LRU-bounded — no serialization, no
    cross-process staleness. A warm worker handles many calls so the
    hit rate is high; a cold worker just re-renders once.
  * Frames are captured from the SAME provider stream that would have
    played, in the SAME PCM format — replay is bit-identical audio.
  * Only short phrases are cached (`max_chars`); dynamic LLM answers are
    never cached (they don't repeat).
  * Pace/emotion are intentionally NOT in the key: these phrases are
    short backchannels/acks where a fixed neutral render is fine, and
    keeping the key coarse maximises the hit rate.

This module is dependency-light and the public helper is structured for
unit testing with fakes (no live network needed).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import AsyncIterable

logger = logging.getLogger("tts_cache")

# A cached frame is the minimal reconstructable tuple:
#   (pcm_bytes, sample_rate, num_channels, samples_per_channel)
_FrameTuple = tuple[bytes, int, int, int]

# LRU bound. A pool of ~12 fillers + ~20 canned phrases × a few voices
# fits comfortably; each ~1-2s phrase is ~50-100KB, so 256 entries is
# at most ~25MB per worker.
_MAX_ENTRIES = 256

_cache: "OrderedDict[str, list[_FrameTuple]]" = OrderedDict()


def _key(model: str, speaker: str, language: str, text: str) -> str:
    return f"{model}|{speaker}|{language}|{text.strip()}"


def _frame_to_tuple(frame) -> _FrameTuple:
    """Capture the reconstructable bytes+format from an rtc.AudioFrame."""
    return (
        bytes(frame.data),
        int(frame.sample_rate),
        int(frame.num_channels),
        int(frame.samples_per_channel),
    )


def _rebuild_frames(tuples: list[_FrameTuple]) -> list:
    """Rebuild fresh rtc.AudioFrame objects from cached tuples (frames are
    consumed on playout, so we rebuild on every replay)."""
    from livekit import rtc

    return [
        rtc.AudioFrame(
            data=data,
            sample_rate=sr,
            num_channels=ch,
            samples_per_channel=spc,
        )
        for (data, sr, ch, spc) in tuples
    ]


async def _aiter(frames: list) -> AsyncIterable:
    for f in frames:
        yield f


def _store(key: str, tuples: list[_FrameTuple]) -> None:
    _cache[key] = tuples
    _cache.move_to_end(key)
    while len(_cache) > _MAX_ENTRIES:
        old, _ = _cache.popitem(last=False)
        logger.debug("tts cache evict %s", old[:40])


def cache_stats() -> dict:
    """Small introspection helper (tests / ops)."""
    return {"entries": len(_cache), "max": _MAX_ENTRIES}


def clear_cache() -> None:
    _cache.clear()


async def _render_tuples(tts, text: str) -> list[_FrameTuple]:
    """Synthesise `text` once and capture its audio frames as tuples."""
    tuples: list[_FrameTuple] = []
    stream = tts.synthesize(text)
    try:
        async for ev in stream:
            frame = getattr(ev, "frame", None)
            if frame is not None:
                tuples.append(_frame_to_tuple(frame))
    finally:
        aclose = getattr(stream, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:
                pass
    return tuples


async def say_cached(
    session,
    tts,
    text: str,
    *,
    model: str,
    speaker: str,
    language: str,
    allow_interruptions: bool = True,
    add_to_chat_ctx: bool = True,
    max_chars: int = 160,
):
    """Speak `text`, replaying cached audio if we've rendered this exact
    phrase+voice before; otherwise render once, cache it, and play.

    Returns the SpeechHandle from `session.say`. Raises only if BOTH the
    cache path AND the fallback fail — callers should still guard.

    On a miss the phrase is rendered to completion before playback (no
    streaming), which costs the normal synthesis time ONCE per phrase per
    worker; every subsequent use of that phrase is then synthesis-free.
    Long/dynamic text (> `max_chars`) bypasses the cache entirely and is
    spoken via the normal streaming path.
    """
    text = (text or "").strip()
    if not text:
        return None

    # Don't cache long/dynamic content — only fixed short phrases repeat.
    if len(text) > max_chars:
        return await session.say(
            text,
            allow_interruptions=allow_interruptions,
            add_to_chat_ctx=add_to_chat_ctx,
        )

    key = _key(model, speaker, language, text)
    tuples = _cache.get(key)
    if tuples is not None:
        _cache.move_to_end(key)  # LRU bump
    else:
        tuples = await _render_tuples(tts, text)
        if tuples:
            _store(key, tuples)

    if not tuples:
        # Render produced nothing (provider hiccup) — fall back to the
        # normal streaming path so the agent still speaks.
        return await session.say(
            text,
            allow_interruptions=allow_interruptions,
            add_to_chat_ctx=add_to_chat_ctx,
        )

    frames = _rebuild_frames(tuples)
    return await session.say(
        text,
        audio=_aiter(frames),
        allow_interruptions=allow_interruptions,
        add_to_chat_ctx=add_to_chat_ctx,
    )
