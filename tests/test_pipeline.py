"""Cross-component smoke tests: FSM, fillers, memory, cost, cancellation."""

import asyncio

import pytest

from src.cancellation import CancellationRegistry
from src.cost import CallMeter, trim_history
from src.filler import pick_filler, should_filler
from src.fsm import ConversationFSM, State
from src.memory import CallMemory, detect_emotion, extract_name
from src.router.intent_router import Route


# ── FSM ─────────────────────────────────────────────────────────────
def test_fsm_legal_and_illegal_transitions():
    fsm = ConversationFSM()
    assert fsm.state == State.GREETING
    assert fsm.to(State.LISTENING)
    assert fsm.to(State.THINKING)
    assert fsm.to(State.SPEAKING)
    # SPEAKING -> KB_FETCH is illegal and must be rejected, not crash.
    assert not fsm.to(State.KB_FETCH)
    assert fsm.state == State.SPEAKING


def test_fsm_barge_in_path_and_hook():
    seen = []
    fsm = ConversationFSM(on_transition=lambda a, b: seen.append(b))
    fsm.to(State.LISTENING)
    fsm.to(State.THINKING)
    fsm.to(State.SPEAKING)
    fsm.on_user_started_speaking()        # barge-in
    assert fsm.state == State.INTERRUPTED
    assert State.INTERRUPTED in seen


# ── Fillers ─────────────────────────────────────────────────────────
def test_filler_only_when_justified():
    # LLM turns always get a filler (covers 1-3s LLM latency).
    # Canned/cache turns are instant — no filler.
    assert should_filler(Route.LLM)
    assert not should_filler(Route.CANNED)
    assert not should_filler(Route.CACHE)
    assert should_filler(Route.LLM, elapsed_seconds=999)
    assert should_filler(Route.CACHE, stt_confidence=0.1)


def test_filler_language_and_nonempty():
    assert pick_filler("te")
    assert pick_filler("hi")
    assert pick_filler("en")


# ── Memory ──────────────────────────────────────────────────────────
def test_emotion_and_name_extraction():
    assert detect_emotion("this is the worst service, useless") == "angry"
    assert detect_emotion("thanks, great help") == "happy"
    assert extract_name("naa peru Ravi") == "Ravi"
    assert extract_name("nothing here") is None


def test_memory_prompt_is_compact():
    m = CallMemory(call_id="c1")
    m.update_from_turn("mera refund kaha hai", "hi", "refund")
    block = m.as_prompt()
    assert "language=hi" in block and "intent=refund" in block
    assert len(block) < 400


# ── Cost ────────────────────────────────────────────────────────────
def test_meter_bypass_rate():
    mt = CallMeter()
    mt.record_route(Route.CANNED)
    mt.record_route(Route.CACHE)
    mt.record_route(Route.LLM)
    assert mt.llm_calls == 1
    assert 0.66 <= mt.llm_bypass_rate <= 0.67


def test_trim_history_keeps_system_and_last_turns():
    class M:
        def __init__(self, role):
            self.role = role

    msgs = [M("system")] + [M("user"), M("assistant")] * 5
    trimmed = trim_history(msgs, max_turns=2)
    assert trimmed[0].role == "system"
    assert len(trimmed) == 1 + 4


# ── Cancellation ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cancellation_registry_cancels_inflight():
    reg = CancellationRegistry()

    async def slow():
        await asyncio.sleep(5)

    reg.spawn(slow())
    await asyncio.sleep(0)            # let it start
    assert reg.cancel_generation() == 1
    assert reg.cancel_generation() == 0   # idempotent
