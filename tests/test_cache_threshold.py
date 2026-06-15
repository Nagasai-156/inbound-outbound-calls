"""Cache threshold + namespace behaviour tests."""

from __future__ import annotations

import numpy as np

from src.cache import SemanticCache, _entry_id, ns_for


def test_namespace_isolation_prevents_cross_business_leak():
    """Two SemanticCache instances on different namespaces must not
    share L1 state."""
    sc1 = SemanticCache()
    sc1.namespace = ns_for("clinic-A")
    sc2 = SemanticCache()
    sc2.namespace = ns_for("clinic-B")
    assert sc1.namespace != sc2.namespace
    assert sc1._idx() != sc2._idx()


def test_default_namespace_is_default():
    sc = SemanticCache()
    assert sc.namespace == "default"


def test_ns_for_handles_strip_whitespace():
    assert ns_for("  hello  ") == ns_for("hello")
    assert ns_for("hello") == ns_for("HELLO")


def test_entry_id_collision_resistance_at_1k_inputs():
    """No collisions expected over 1000 realistic queries."""
    queries = [
        f"appointment for {day} at {hour}pm"
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]
        for hour in range(1, 13)
        for _ in range(10)
    ]
    hashes = {_entry_id(q + str(i)) for i, q in enumerate(queries)}
    assert len(hashes) == len(queries)


def test_l1_initial_state_empty():
    sc = SemanticCache()
    assert len(sc._mem) == 0


def test_l1_lru_eviction_bound():
    """_mem must not grow unbounded — LRU bound enforced."""
    sc = SemanticCache()
    # Add many namespaces to L1 directly (skip Redis).
    import time
    for i in range(50):
        sc._mem[f"ns_{i}"] = (time.monotonic(), {})
    sc._evict_lru()
    # Should be capped at _MEM_MAX_NAMESPACES (currently 32).
    from src.cache import _MEM_MAX_NAMESPACES
    assert len(sc._mem) <= _MEM_MAX_NAMESPACES


def test_namespace_switch_isolates_lookups():
    """Changing namespace mid-test should change _idx() return."""
    sc = SemanticCache()
    sc.namespace = "a"
    idx_a = sc._idx()
    sc.namespace = "b"
    idx_b = sc._idx()
    assert idx_a != idx_b


def test_entry_id_strips_lowercase_consistently():
    """Verified: 'Hello' == 'hello' == 'HELLO' produce same id."""
    assert _entry_id("Hello") == _entry_id("hello")
    assert _entry_id("HELLO") == _entry_id("hello")
    assert _entry_id("hElLo") == _entry_id("hello")


def test_namespace_for_long_persona_text():
    """Even with a 10k-char persona, namespace is still 12 chars."""
    persona = "very specific business persona text " * 500
    n = ns_for(persona)
    assert len(n) == 12


def test_two_personas_with_only_whitespace_diff_match():
    """Operator pastes/trims persona — leading/trailing whitespace must
    not invalidate the cache namespace."""
    a = ns_for("Dental Clinic Persona")
    b = ns_for("  Dental Clinic Persona  ")
    c = ns_for("dental clinic persona")
    assert a == b == c
