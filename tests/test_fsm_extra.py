"""Additional FSM transition tests beyond the existing ones.

The existing test_pipeline.test_fsm_legal_and_illegal_transitions does
broad strokes; these target the SPECIFIC fix we just shipped:
LISTENING → SPEAKING must be ALLOWED (was rejected as illegal, causing
mid-response cutoffs / "Nagasai" single-word stubs).
"""

from __future__ import annotations

from src.fsm import ConversationFSM, State


def test_listening_to_speaking_is_now_allowed():
    """The fix: agent must be able to initiate speech without prior
    THINKING transition (filler concurrent with LLM, recovery after
    TTS error, re-prompt after long silence)."""
    fsm = ConversationFSM()
    fsm.to(State.LISTENING)
    assert fsm.state == State.LISTENING
    assert fsm.can(State.SPEAKING), "LISTENING→SPEAKING must be allowed"
    assert fsm.to(State.SPEAKING) is True
    assert fsm.state == State.SPEAKING


def test_speaking_back_to_listening_still_works():
    """After the new transition, the normal SPEAKING→LISTENING path
    must continue to function."""
    fsm = ConversationFSM()
    fsm.to(State.LISTENING)
    fsm.to(State.SPEAKING)
    assert fsm.to(State.LISTENING) is True
    assert fsm.state == State.LISTENING


def test_call_end_remains_terminal():
    """CALL_END must still be terminal — no outgoing transitions, no
    accidental re-entry into a live state."""
    fsm = ConversationFSM()
    fsm.to(State.CALL_END)
    assert fsm.state == State.CALL_END
    for target in (State.LISTENING, State.THINKING, State.SPEAKING,
                    State.INTERRUPTED, State.KB_FETCH, State.ACTION_EXECUTION):
        assert not fsm.can(target), f"CALL_END must not allow {target}"
        # to() returns False on illegal transition (logs warning).
        assert fsm.to(target) is False
        assert fsm.state == State.CALL_END


def test_barge_in_from_speaking():
    """Caller speaking while agent speaks must transition to INTERRUPTED."""
    fsm = ConversationFSM()
    fsm.to(State.LISTENING)
    fsm.to(State.SPEAKING)
    fsm.on_user_started_speaking()
    assert fsm.state == State.INTERRUPTED


def test_user_turn_committed_routes_to_thinking():
    fsm = ConversationFSM()
    fsm.to(State.LISTENING)
    fsm.on_user_turn_committed()
    assert fsm.state == State.THINKING
