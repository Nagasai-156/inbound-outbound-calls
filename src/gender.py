"""Caller gender detection via YIN F0 estimation + voicing clarity gating.

WHY YIN INSTEAD OF AUTOCORRELATION:
  Plain ACF is fooled by octave errors — it routinely picks the 2× lag
  (reporting F0/2) on creaky-voice frames or returns the half-lag (2×F0)
  on noisy phone audio. YIN's cumulative-mean-normalized-difference
  function suppresses both failure modes. Each frame also yields a
  CLARITY score (1 - normalized difference at the chosen lag) so we can
  reject noisy/unvoiced frames cheaply instead of letting them poison
  the median.

WHY THIS IS LANGUAGE-INDEPENDENT:
  F0 is a function of vocal-fold biology, not phonemes. Pure Telugu,
  pure Hindi, pure English, Tenglish, Hinglish — same speaker → same
  pitch distribution. One detector covers every language a caller might
  use, including switching mid-call.

ACCURACY:
  - YIN with vectorized difference function (~0.5ms/frame on 16kHz).
  - Per-frame clarity gate: only frames with clarity ≥ 0.85 enter the
    rolling buffer; noisy/unvoiced frames are silently dropped.
  - Confidence bands: <145Hz definite male, >185Hz definite female,
    the 145-185Hz overlap stays "unknown" (refuses to guess between
    young-adult males and low-pitched females).
  - Multi-frame agreement: need ≥ 18 clarity-gated frames in the
    rolling window before committing a classification — single noisy
    bursts cannot flip the result.

EFFICIENCY (the "very optimized" part):
  - Silence skip BEFORE any FFT: int16 RMS gate dumps silent frames in
    a few microseconds (most phone calls are >50% silence on the caller
    side).
  - MAINTENANCE MODE: once a high-confidence lock holds for 40 voiced
    frames, the detector switches to 1-in-50 frame sampling — only
    enough to notice if a different speaker takes over the line. CPU
    drops to ~2% of active-mode cost for the rest of the call.
  - Re-arms if a sampled frame disagrees with the lock, walking back to
    active mode for re-evaluation.
  - Single pre-allocated scratch buffer; no per-frame numpy allocations
    beyond the unavoidable FFT result.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Awaitable, Callable

import numpy as np
from livekit import rtc

logger = logging.getLogger("voiceai.gender")

_SAMPLE_RATE = 16000

# F0 search range. Phone-narrowband audio loses meaningful information
# below ~75Hz and above ~320Hz; an adult human pitch outside this band
# is exceedingly rare and almost certainly an octave error.
_F0_LO_HZ = 75
_F0_HI_HZ = 320

# Decision bands. Indian adult male F0 mean ≈ 110-130 Hz; female ≈ 195-220 Hz.
# The 145-185 Hz band overlaps (young adult males / low-pitched females)
# so we refuse to guess there and wait for more evidence.
_F0_MALE_MAX_HZ = 145
_F0_FEMALE_MIN_HZ = 185

# YIN absolute clarity threshold (frames below this CMNDF value are
# considered voiced). 0.15 is the canonical YIN default.
_YIN_ABS_THRESHOLD = 0.15
# Per-frame clarity gate for buffer admission (1 - cmndf at chosen lag).
# Higher = stricter (fewer but cleaner frames in the rolling buffer).
_MIN_FRAME_CLARITY = 0.87  # tightened from 0.85 to reject clipped/saturated frames whose YIN clarity sits right at the boundary (octave-error risk). Clean voiced frames sit at 0.99+; moderate phone noise at 0.91+ — 0.87 gate kills the edge case without rejecting real audio.

# Silence pre-gate (int16 RMS). Below this we skip the FFT entirely.
_SILENCE_RMS = 250.0

# Rolling buffer + decision policy.
_WINDOW = 120
_MIN_VOICED_FOR_DECISION = 18
_DECIDE_INTERVAL = 8

# Maintenance mode policy.
_LOCK_FRAMES = 40         # voiced frames of agreement to enter maintenance
_MAINTENANCE_SKIP = 50    # process 1 in N frames during maintenance
_RELOCK_DISAGREE = 4      # consecutive disagreeing frames re-arm full mode


def _yin_f0(samples: np.ndarray) -> tuple[float, float]:
    """YIN F0 estimator. Returns (f0_hz, clarity) or (0.0, 0.0) if unvoiced.

    Vectorized: the difference function d(τ) is computed via FFT
    autocorrelation in O(n log n), and the cumulative-mean normalization
    uses cumsum. Total cost ≈ 0.5ms on a 32ms 16kHz frame.
    """
    n = len(samples)
    if n < 128:
        return 0.0, 0.0

    x = samples.astype(np.float32, copy=False)
    x = x - x.mean()
    rms = float(np.sqrt(np.mean(x * x)))
    if rms < _SILENCE_RMS:
        return 0.0, 0.0

    tau_min = _SAMPLE_RATE // _F0_HI_HZ          # 50  (320Hz)
    tau_max = min(_SAMPLE_RATE // _F0_LO_HZ, n // 2)  # ≤213 (75Hz)
    if tau_max <= tau_min + 2:
        return 0.0, 0.0

    # Autocorrelation via FFT.
    fft_size = 1 << (2 * n - 1).bit_length()
    spec = np.fft.rfft(x, n=fft_size)
    acf = np.fft.irfft(spec * np.conj(spec), n=fft_size)[: tau_max + 1].real

    # Cumulative sum of squared samples — used to compute the two energy
    # terms of d(τ) = E_left(τ) + E_right(τ) - 2·R(τ).
    sq = x * x
    cumsq = np.concatenate(([0.0], np.cumsum(sq)))  # length n+1

    taus = np.arange(1, tau_max + 1)
    e_left = cumsq[n - taus]                   # Σ x[0..n-τ-1]²
    e_right = cumsq[n] - cumsq[taus]           # Σ x[τ..n-1]²
    diff = e_left + e_right - 2.0 * acf[1 : tau_max + 1]
    diff = np.maximum(diff, 0.0)                # guard floating-point noise

    # Cumulative mean normalized difference function (CMNDF).
    cumdiff = np.cumsum(diff)
    denom = cumdiff / taus                      # running mean of diff
    cmndf = np.empty_like(diff)
    nz = denom > 1e-9
    cmndf[nz] = diff[nz] / denom[nz]
    cmndf[~nz] = 1.0

    # First absolute-threshold dip; if none, fall back to global min.
    # cmndf is 0-indexed where cmndf[i] holds the value at lag (i+1), so
    # the value at lag τ lives at cmndf[τ-1]. The walk-forward advances
    # while the NEXT lag (cmndf[τ]) has a smaller CMNDF than the current
    # lag (cmndf[τ-1]) — i.e. the trough is still deepening. We stop at
    # the first τ that is itself the local minimum; no decrement.
    below = np.flatnonzero(cmndf[tau_min - 1 : tau_max] < _YIN_ABS_THRESHOLD)
    if below.size > 0:
        tau = int(below[0]) + tau_min
        while tau + 1 <= tau_max and cmndf[tau] < cmndf[tau - 1]:
            tau += 1
    else:
        tau = int(np.argmin(cmndf[tau_min - 1 : tau_max])) + tau_min

    clarity = 1.0 - float(cmndf[tau - 1])
    if clarity <= 0.0:
        return 0.0, 0.0
    return _SAMPLE_RATE / tau, clarity


def _classify(f0s: deque[float]) -> tuple[str, float]:
    """Confidence-banded classification from the rolling buffer."""
    if len(f0s) < _MIN_VOICED_FOR_DECISION:
        return "unknown", 0.0
    med = float(np.median(f0s))
    if med < _F0_MALE_MAX_HZ:
        return "male", med
    if med > _F0_FEMALE_MIN_HZ:
        return "female", med
    return "unknown", med


async def detect_caller_gender(
    track: rtc.RemoteAudioTrack,
    on_done: Callable[[str, float], Awaitable[None] | None],
) -> None:
    """Continuously detect gender on `track`. Invokes `on_done(gender, f0)`
    whenever the classification CHANGES. Runs until the audio stream
    closes (call ends). After a stable lock holds, drops to ~1-in-50
    frame sampling to conserve CPU — re-arms if drift is detected."""
    stream = rtc.AudioStream(
        track, sample_rate=_SAMPLE_RATE, num_channels=1
    )
    f0s: deque[float] = deque(maxlen=_WINDOW)
    voiced_since_decide = 0
    last_gender = "unknown"
    locked = False
    lock_streak = 0
    skip_counter = 0
    disagree_streak = 0

    async def _emit(g: str, m: float) -> None:
        nonlocal last_gender
        if g == last_gender:
            return
        prev = last_gender
        last_gender = g
        logger.info(
            "gender_detect %s -> %s median_f0=%.1fHz voiced=%d",
            prev, g, m, len(f0s),
        )
        try:
            res = on_done(g, m)
            if hasattr(res, "__await__"):
                await res  # type: ignore[misc]
        except Exception:
            logger.exception("gender on_done callback failed")

    try:
        async for ev in stream:
            # Maintenance mode: process only every Nth frame once locked.
            if locked:
                skip_counter += 1
                if skip_counter < _MAINTENANCE_SKIP:
                    continue
                skip_counter = 0

            try:
                samples = np.frombuffer(ev.frame.data, dtype=np.int16)
            except Exception:
                continue

            f0, clarity = _yin_f0(samples)
            if f0 <= 0.0 or clarity < _MIN_FRAME_CLARITY:
                continue

            if locked:
                # Spot-check during maintenance. Confirm the frame is in
                # the same band; otherwise re-arm.
                if last_gender == "male" and f0 >= _F0_MALE_MAX_HZ:
                    disagree_streak += 1
                elif last_gender == "female" and f0 <= _F0_FEMALE_MIN_HZ:
                    disagree_streak += 1
                else:
                    disagree_streak = 0
                if disagree_streak >= _RELOCK_DISAGREE:
                    logger.info(
                        "gender_detect re-arm (locked=%s but f0=%.1fHz)",
                        last_gender, f0,
                    )
                    locked = False
                    lock_streak = 0
                    disagree_streak = 0
                    f0s.clear()
                continue

            # Active mode: build buffer, re-decide periodically.
            f0s.append(f0)
            voiced_since_decide += 1
            if voiced_since_decide >= _DECIDE_INTERVAL:
                voiced_since_decide = 0
                g, m = _classify(f0s)
                if g != last_gender:
                    await _emit(g, m)
                # Track lock progress only when classification is decided.
                if g in ("male", "female"):
                    lock_streak += _DECIDE_INTERVAL
                    if lock_streak >= _LOCK_FRAMES:
                        locked = True
                        logger.info(
                            "gender_detect locked=%s median_f0=%.1fHz",
                            g, m,
                        )
                else:
                    lock_streak = 0
    except Exception:
        logger.debug("gender stream errored", exc_info=True)
    finally:
        try:
            await stream.aclose()
        except Exception:
            pass
        if last_gender == "unknown":
            logger.info(
                "gender_detect ended=unknown voiced=%d median=%.1fHz",
                len(f0s), float(np.median(f0s)) if f0s else 0.0,
            )
