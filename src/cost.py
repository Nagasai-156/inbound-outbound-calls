"""Cost-optimization layer.

Two jobs:

  * per-route metering so we can see how often we avoided OpenAI (the
    whole point of the router), logged at end of call, and
  * token trimming so the LLM prompt never carries bloat — structured
    memory + a short rolling summary instead of raw history.

Kept dependency-free and side-effect-light so it can wrap any call path.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from src.router.intent_router import Route

logger = logging.getLogger("cost")


@dataclass
class CallMeter:
    """Per-call counters. One instance per call (lives on the agent)."""

    routes: Counter = field(default_factory=Counter)
    llm_calls: int = 0
    kb_calls: int = 0

    def record_route(self, route: Route) -> None:
        self.routes[route.value] += 1
        if route == Route.LLM:
            self.llm_calls += 1

    def record_kb(self) -> None:
        self.kb_calls += 1

    @property
    def llm_bypass_rate(self) -> float:
        total = sum(self.routes.values())
        if not total:
            return 0.0
        return 1.0 - (self.routes.get(Route.LLM.value, 0) / total)

    def summary(self) -> str:
        return (
            f"turns={sum(self.routes.values())} "
            f"llm={self.llm_calls} kb={self.kb_calls} "
            f"bypass={self.llm_bypass_rate:.0%} routes={dict(self.routes)}"
        )

    def log(self) -> None:
        logger.info("cost %s", self.summary())


def trim_history(messages: list, max_turns: int) -> list:
    """Keep only the last `max_turns` user/assistant exchanges.

    System messages are always preserved (persona/constraints). This is
    the cheapest, highest-leverage token cut for voice latency + spend.

    Edge case: max_turns=0 must return ONLY system messages. The naive
    `convo[-(0*2):]` is `convo[-0:]` which Python evaluates to the full
    list (slicing quirk) — the bug surfaced by tests/test_cost_meter_edge.
    """
    system = [m for m in messages if getattr(m, "role", None) == "system"]
    convo = [m for m in messages if getattr(m, "role", None) != "system"]
    if max_turns <= 0:
        return system
    return system + convo[-(max_turns * 2):]
