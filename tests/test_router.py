"""Fast Intent Router + classifier + canned responses.

Verifies the cost guardrail: trivial turns never reach the LLM, cache
hits short-circuit, novel turns fall through to LLM.
"""

import pytest

from src.agent import _detect_conversational_variety
from src.router.canned import canned_response
from src.router.classifier import classify, detect_language
from src.router.intent_router import IntentRouter, Route


def test_language_detection():
    assert detect_language("Hello anna order status cheppandi") in ("te", "mixed")
    assert detect_language("haan bhai mera order kaha hai") in ("hi", "mixed")
    assert detect_language("Can you help me with payment issue?") == "en"


def test_trivial_intents_are_flagged():
    assert classify("hello").is_trivial
    assert classify("thank you").is_trivial
    assert classify("haan").is_trivial
    assert not classify("my payment failed and money was debited").is_trivial


def test_canned_only_for_safe_intents():
    # Greetings/affirm are NO LONGER canned: a generic "hello sir" reply
    # overrides the call's script/persona (real production failure). Only
    # conversation-ending / clarification intents shortcut the LLM.
    assert canned_response(classify("thank you")) is not None
    assert canned_response(classify("hello")) is None
    assert canned_response(classify("what is your refund policy")) is None


@pytest.mark.asyncio
async def test_greeting_routes_to_llm_to_stay_on_script():
    # The persona-driven LLM handles greetings IN the call's language and
    # ON the call's goal — a canned greeting derailed scripted calls.
    r = await IntentRouter().route("hello")
    assert r.route == Route.LLM
    assert not r.resolved_without_llm


@pytest.mark.asyncio
async def test_canned_uses_call_language_not_classifier():
    # "thanks" in a Telugu call must reply in Telugu even though the
    # classifier may read the English word as en.
    r = await IntentRouter().route("thanks", call_language="te")
    assert r.route == Route.CANNED and r.answer
    assert r.answer in (
        "నో ప్రాబ్లం అండి, గ్లాడ్ టు హెల్ప్!",
        "అయ్యో, పర్లేదు అండి, నో ప్రాబ్లం!",
        "పర్లేదు అండి, రెడీగా ఉంటాను ఎప్పుడైనా!",
        "నో ప్రాబ్లం అండి, రెడీగా ఉంటాను!"
    )


@pytest.mark.asyncio
async def test_cache_hit_short_circuits():
    async def cache(_q):
        return "Refund 5 to 7 days sir."

    router = IntentRouter(cache_resolver=cache)
    r = await router.route("how long does refund take")
    assert r.route == Route.CACHE
    assert r.answer == "Refund 5 to 7 days sir."


@pytest.mark.asyncio
async def test_novel_question_falls_through_to_llm():
    r = await IntentRouter().route("explain your enterprise SLA terms")
    assert r.route == Route.LLM
    assert not r.resolved_without_llm


@pytest.mark.asyncio
async def test_canned_does_not_repeat_back_to_back():
    router = IntentRouter()
    # "thanks" is a SAFE canned intent with a multi-line pool -> rotation
    seen = {
        (await router.route("thank you", call_language="te")).answer
        for _ in range(6)
    }
    assert len(seen) > 1


def test_detect_conversational_variety():
    # 1. Pure Telugu & Tenglish
    assert _detect_conversational_variety("సరే అండి, రేపు కలుద్దాం", "te") == "te"
    assert _detect_conversational_variety("సరే అండి, consulting time ఏంటి?", "te") == "te-mix"

    # 2. Pure Hindi & Hinglish
    assert _detect_conversational_variety("हाँ भाई, कल मिलेंगे", "hi") == "hi"
    assert _detect_conversational_variety("हाँ भाई, appointment cancel करो", "hi") == "hi-mix"

    # 3. Pure English
    assert _detect_conversational_variety("Can we reschedule my consultation?", "te") == "en"

    # 4. High-stability bypass: short acks do NOT switch languages, they keep the active conversational variety!
    assert _detect_conversational_variety("ok", "te-mix") == "te-mix"
    assert _detect_conversational_variety("సరే", "te-mix") == "te-mix"
    assert _detect_conversational_variety("yes", "hi-mix") == "hi-mix"
    assert _detect_conversational_variety("ఆ", "te") == "te"
