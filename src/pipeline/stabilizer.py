"""Realtime transcript stabilizer.

Sarvam interim transcripts flicker: "naa or" -> "naa order" -> "naa
order sta". Feeding raw partials to the router/LLM causes hallucination
and wasted speculative work. This sits between STT and everything
downstream and only releases a token once it has:

  1. persisted unchanged across N consecutive partials, AND
  2. cleared the per-token confidence floor (when STT provides scores),
     AND
  3. survived a short debounce window.

Only the *stable prefix* drives the router and predictive prefetch; the
final transcript is still authoritative for the actual answer. The
debounce is tuned (config) so we keep most of the partial-speed
advantage while killing the flicker.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.config import settings


@dataclass
class _TokenTrack:
    token: str
    count: int
    first_seen: float


@dataclass
class TranscriptStabilizer:
    min_stable_partials: int = field(
        default_factory=lambda: settings.stabilizer_min_stable_partials
    )
    debounce_seconds: float = field(
        default_factory=lambda: settings.stabilizer_debounce_seconds
    )
    min_confidence: float = field(
        default_factory=lambda: settings.stabilizer_min_token_confidence
    )

    _stable: list[str] = field(default_factory=list)
    _tracks: list[_TokenTrack] = field(default_factory=list)
    # Average per-word confidence of the most recent FINAL transcript
    # (set by the transcription handler on is_final=True). Default 1.0
    # means "treat as full confidence" — only down-gated when Sarvam
    # actually provides scores on the final event. The mishear gate in
    # VoiceAgent.on_user_turn_completed reads this to force a "please
    # repeat" path when confidence is low even if the text LOOKS
    # grammatical.
    last_final_avg_confidence: float = 1.0

    @property
    def stable_text(self) -> str:
        return " ".join(self._stable)

    def reset(self) -> None:
        """Call at end of a user turn so the next turn starts clean."""
        self._stable.clear()
        self._tracks.clear()

    def push(
        self,
        interim: str,
        confidences: list[float] | None = None,
        now: float | None = None,
    ) -> str:
        """Feed an interim transcript. Returns the *newly* stabilized
        suffix (empty string if nothing newly stabilized this push)."""
        now = time.monotonic() if now is None else now
        words = (interim or "").strip().split()
        n_stable = len(self._stable)

        # Already-stable prefix must still match; if STT rewrote it,
        # trust the newer hypothesis and roll back the divergent tail.
        for i in range(min(n_stable, len(words))):
            if words[i] != self._stable[i]:
                self._stable = self._stable[:i]
                self._tracks.clear()
                n_stable = i
                break

        pending = words[n_stable:]
        newly: list[str] = []

        for idx, w in enumerate(pending):
            track = self._tracks[idx] if idx < len(self._tracks) else None
            if track is None or track.token != w:
                track = _TokenTrack(token=w, count=1, first_seen=now)
                if idx < len(self._tracks):
                    self._tracks[idx] = track
                    del self._tracks[idx + 1 :]  # divergence -> drop tail
                else:
                    self._tracks.append(track)
            else:
                track.count += 1

            conf_ok = (
                confidences is None
                or (n_stable + idx) >= len(confidences)
                or confidences[n_stable + idx] >= self.min_confidence
            )
            stable_enough = (
                track.count >= self.min_stable_partials
                and (now - track.first_seen) >= self.debounce_seconds
                and conf_ok
            )
            if stable_enough:
                self._stable.append(w)
                newly.append(w)
            else:
                break  # can't stabilize a token before the one before it

        # Drop the just-stabilized tokens from the FRONT of _tracks in
        # ONE step, AFTER the loop. The old code did `self._tracks.pop(0)`
        # INSIDE the loop while still indexing `self._tracks[idx]` by the
        # original position — so after the first token stabilized, every
        # later token in the SAME push was read from a shifted index,
        # didn't match, and got a fresh count=1 track (its accumulated
        # count discarded). Net effect: at most ~1 token could stabilize
        # per push and the stable prefix lagged, starving the predictive
        # prefetch the stabilizer exists to feed. Removing them once here
        # keeps the remaining unstable tail correctly aligned with the
        # next push's `pending`.
        if newly:
            del self._tracks[: len(newly)]

        return " ".join(newly)
