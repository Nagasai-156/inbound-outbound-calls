"""Human response-rhythm engine.

Even with low latency, a *fixed* cadence reads as robotic subconsciously.
Real people vary: a tiny think-pause before answering, an occasional
micro-hesitation, a breath between sentences. This engine produces those
small, bounded, randomized delays — biased by detected emotion:

  * angry / urgent  -> snappier (shorter pauses)
  * confused / elderly -> slower, clearer (longer pauses)
  * neutral / happy -> natural mid-range

It only adds *small* delays and never enough to break the sub-second
perceived-latency target; the conditional filler covers any real wait.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

# emotion -> (pre-speech min, pre-speech max, inter-sentence min, max) secs
_PROFILE = {
    "angry":    (0.00, 0.08, 0.04, 0.10),
    "urgent":   (0.00, 0.08, 0.04, 0.10),
    "frustrated": (0.02, 0.12, 0.05, 0.12),
    "confused": (0.15, 0.35, 0.18, 0.35),
    "elderly":  (0.20, 0.40, 0.20, 0.40),
    "happy":    (0.06, 0.20, 0.10, 0.22),
    "neutral":  (0.05, 0.18, 0.08, 0.20),
}

# Occasional spoken micro-hesitation (kept rare so it stays natural).
_HESITATIONS = {
    "te": ["", "", "", "hmm,", "aa,"],
    "hi": ["", "", "", "hmm,", "matlab,"],
    "en": ["", "", "", "hmm,", "uh,"],
}


@dataclass
class ResponseRhythm:
    emotion: str = "neutral"

    def _p(self) -> tuple[float, float, float, float]:
        return _PROFILE.get(self.emotion, _PROFILE["neutral"])

    def pre_speech_delay(self) -> float:
        lo, hi, _, _ = self._p()
        return random.uniform(lo, hi)

    def inter_sentence_delay(self) -> float:
        _, _, lo, hi = self._p()
        return random.uniform(lo, hi)

    def maybe_hesitation(self, language: str) -> str:
        if self.emotion in ("angry", "urgent"):
            return ""  # don't dither at an angry caller
        lang = language if language in ("te", "hi", "en") else "en"
        return random.choice(_HESITATIONS[lang])

    async def think_pause(self) -> None:
        """Await the natural pre-speech beat before the agent replies."""
        await asyncio.sleep(self.pre_speech_delay())
