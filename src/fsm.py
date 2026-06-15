"""Conversation State Machine.

Without an explicit FSM, realtime voice pipelines hit race conditions:
overlapping TTS, partial-STT arriving while the agent is speaking, double
barge-in. This module is the single source of truth for "what is the call
doing right now" and guards every transition.

It is transport-agnostic: `agent.py` binds AgentSession events to these
transitions; tests drive it directly.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger("fsm")


class State(str, Enum):
    GREETING = "GREETING"
    LISTENING = "LISTENING"
    THINKING = "THINKING"          # router/LLM/KB working
    SPEAKING = "SPEAKING"          # TTS playing
    INTERRUPTED = "INTERRUPTED"    # caller barged in
    KB_FETCH = "KB_FETCH"
    ACTION_EXECUTION = "ACTION_EXECUTION"
    CALL_END = "CALL_END"


# Allowed transitions. Anything not listed is rejected (and logged) so
# illegal concurrency is caught instead of silently corrupting the call.
_ALLOWED: dict[State, set[State]] = {
    State.GREETING: {State.LISTENING, State.SPEAKING, State.CALL_END},
    # LISTENING→SPEAKING added: the agent can initiate speech without a
    # prior caller turn (filler fires concurrent with LLM, re-prompt
    # after long silence, recovery after TTS error). The previous strict
    # rule rejected ~4 transitions per call as "illegal" and suppressed
    # those utterances mid-response — the "Nagasai" single-word stubs in
    # transcripts. Overlap-TTS protection still holds because SPEAKING
    # can only re-enter LISTENING/INTERRUPTED/CALL_END.
    State.LISTENING: {State.THINKING, State.SPEAKING, State.INTERRUPTED, State.CALL_END},
    State.THINKING: {
        State.KB_FETCH,
        State.ACTION_EXECUTION,
        State.SPEAKING,
        State.INTERRUPTED,
        State.LISTENING,
        State.CALL_END,
    },
    State.KB_FETCH: {State.SPEAKING, State.THINKING, State.INTERRUPTED, State.CALL_END},
    State.ACTION_EXECUTION: {
        State.SPEAKING,
        State.THINKING,
        State.INTERRUPTED,
        State.CALL_END,
    },
    State.SPEAKING: {State.LISTENING, State.INTERRUPTED, State.CALL_END},
    State.INTERRUPTED: {State.LISTENING, State.THINKING, State.CALL_END},
    State.CALL_END: set(),
}


class ConversationFSM:
    def __init__(self, on_transition: Optional[Callable[[State, State], None]] = None):
        self._state = State.GREETING
        self._since = time.monotonic()
        self._on_transition = on_transition

    @property
    def state(self) -> State:
        return self._state

    @property
    def seconds_in_state(self) -> float:
        return time.monotonic() - self._since

    def can(self, target: State) -> bool:
        return target in _ALLOWED.get(self._state, set())

    def to(self, target: State) -> bool:
        """Attempt a transition. Returns False (and logs) if illegal so
        callers can no-op instead of crashing the call."""
        if target == self._state:
            return True
        if not self.can(target):
            logger.warning("illegal transition %s -> %s (ignored)", self._state, target)
            return False
        prev, self._state = self._state, target
        self._since = time.monotonic()
        logger.debug("fsm %s -> %s", prev, target)
        if self._on_transition:
            self._on_transition(prev, target)
        return True

    # ─── Convenience hooks bound to AgentSession events ──────────
    def on_user_started_speaking(self) -> None:
        # Caller talking while agent speaks/thinks => barge-in.
        if self._state in (State.SPEAKING, State.THINKING, State.KB_FETCH,
                            State.ACTION_EXECUTION):
            self.to(State.INTERRUPTED)
        elif self._state in (State.GREETING, State.LISTENING):
            self.to(State.LISTENING)

    def on_user_turn_committed(self) -> None:
        if self._state in (State.LISTENING, State.INTERRUPTED, State.GREETING):
            self.to(State.THINKING)

    def on_agent_started_speaking(self) -> None:
        self.to(State.SPEAKING)

    def on_agent_stopped_speaking(self) -> None:
        if self._state == State.SPEAKING:
            self.to(State.LISTENING)

    def on_call_ended(self) -> None:
        self.to(State.CALL_END)
