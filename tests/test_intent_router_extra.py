"""Intent router Route enum + classification interaction tests."""

from __future__ import annotations

from src.router.intent_router import Route


def test_route_enum_has_canonical_values():
    """The Route enum drives meter accounting and bypass-rate math.
    Adding/removing values changes every downstream calculation.
    Note: KB calls are tracked separately on CallMeter.kb_calls, NOT
    as a Route value — they happen *during* an LLM route (via the
    kb_search tool)."""
    expected = {"canned", "cache", "action", "llm"}
    actual = {r.value for r in Route}
    missing = expected - actual
    assert not missing, f"Route enum missing values: {missing}"


def test_route_llm_is_distinct():
    """LLM is the one route that ISN'T counted as bypass — verify
    it's not aliased to something else."""
    assert Route.LLM.value == "llm"


def test_route_canned_is_distinct():
    assert Route.CANNED.value == "canned"


def test_route_cache_is_distinct():
    assert Route.CACHE.value == "cache"


def test_all_route_values_lowercase():
    """Convention check — Redis keys use lowercase route names."""
    for r in Route:
        assert r.value == r.value.lower()


def test_all_route_values_unique():
    values = [r.value for r in Route]
    assert len(values) == len(set(values))
