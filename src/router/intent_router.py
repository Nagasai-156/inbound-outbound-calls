"""Fast Intent Router — central dispatch.

Every finalized user turn flows through, in order; first match wins:

    1. Canned/rule      -> ~100ms, no LLM
    2. Semantic cache    -> Redis, no LLM        (impl injected in Phase 8)
    3. Action tool       -> deterministic intents (impl injected later)
    4. LLM path          -> gpt-4o-mini + kb_search

This is the single biggest cost/latency/hallucination reducer: most
turns never reach OpenAI. Cache + action resolvers are injected as async
callables so this module has no hard dependency on Redis/OpenAI and stays
unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional

from src.router.canned import canned_response
from src.router.classifier import Classification, classify

# query -> resolved short answer (or None to fall through)
CacheResolver = Callable[[str], Awaitable[Optional[str]]]
ActionResolver = Callable[[str, Classification], Awaitable[Optional[str]]]


class Route(str, Enum):
    CANNED = "canned"
    CACHE = "cache"
    ACTION = "action"
    LLM = "llm"


@dataclass
class RouteResult:
    route: Route
    classification: Classification
    answer: Optional[str] = None  # set for CANNED/CACHE/ACTION; None -> LLM

    @property
    def resolved_without_llm(self) -> bool:
        return self.route != Route.LLM and self.answer is not None


class IntentRouter:
    def __init__(
        self,
        cache_resolver: Optional[CacheResolver] = None,
        action_resolver: Optional[ActionResolver] = None,
    ) -> None:
        self._cache = cache_resolver
        self._action = action_resolver

    def set_cache_resolver(self, resolver: CacheResolver) -> None:
        self._cache = resolver

    def set_action_resolver(self, resolver: ActionResolver) -> None:
        self._action = resolver

    async def route(
        self, text: str, call_language: str | None = None
    ) -> RouteResult:
        cls = classify(text)

        # 1. Canned/rule — only SAFE intents (thanks/bye/repeat), in the
        # CALL's configured language (not the classifier's guess).
        canned = canned_response(cls, call_language)
        if canned is not None:
            return RouteResult(Route.CANNED, cls, canned)

        # 2. Semantic cache — ONLY for FAQ-type intents. The cache lookup
        # embeds the query via an OpenAI call; doing that on every
        # conversational turn adds a network round-trip (= dead air).
        # Skip it for chit-chat/unknown and go straight to the LLM.
        _FAQ = {"order_status", "payment_issue", "refund"}
        if self._cache is not None and cls.intent in _FAQ:
            try:
                hit = await self._cache(text)
            except Exception:
                hit = None
            if hit:
                return RouteResult(Route.CACHE, cls, hit)

        # 3. Deterministic action intents (order status, etc.).
        if self._action is not None and cls.intent in (
            "order_status",
            "payment_issue",
            "refund",
        ):
            try:
                acted = await self._action(text, cls)
            except Exception:
                acted = None
            if acted:
                return RouteResult(Route.ACTION, cls, acted)

        # 4. Fall through to the LLM (+ kb_search tool).
        return RouteResult(Route.LLM, cls, None)
