"""JSON serialization roundtrip tests.

CallMemory + RuntimeConfig are written to Redis as JSON blobs and read
back across worker restarts. A subtle non-roundtripping field would
silently corrupt restored state."""

from __future__ import annotations

import json
from dataclasses import asdict

from src.memory import CallMemory
from src.runtime_config import RuntimeConfig


def test_call_memory_roundtrip_preserves_all_fields():
    m = CallMemory(
        call_id="c1",
        language="te",
        emotion="happy",
        intent="appointment",
        name="Nagasai",
        slots={"order_id": "MSP-12345"},
        summary="Caller wants booking for tomorrow 5 PM",
    )
    blob = json.dumps(asdict(m), ensure_ascii=False)
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.call_id == m.call_id
    assert restored.language == m.language
    assert restored.emotion == m.emotion
    assert restored.intent == m.intent
    assert restored.name == m.name
    assert restored.slots == m.slots
    assert restored.summary == m.summary


def test_call_memory_roundtrip_empty_slots():
    m = CallMemory(call_id="c2")
    blob = json.dumps(asdict(m))
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.slots == {}


def test_call_memory_roundtrip_none_name():
    """name defaults to None — JSON null roundtrip must preserve."""
    m = CallMemory(call_id="c3", name=None)
    blob = json.dumps(asdict(m))
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.name is None


def test_call_memory_unicode_summary_roundtrip():
    m = CallMemory(call_id="c4", summary="Caller said: మంచి అపాయింట్‌మెంట్")
    blob = json.dumps(asdict(m), ensure_ascii=False)
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.summary == m.summary
    assert "మంచి" in restored.summary


def test_call_memory_ascii_escaped_roundtrip():
    """With ensure_ascii=True (default), Telugu becomes \\uXXXX escapes
    — must still roundtrip."""
    m = CallMemory(call_id="c5", summary="మంచి")
    blob = json.dumps(asdict(m))  # default ensure_ascii=True
    assert "\\u" in blob  # confirm escapes happened
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.summary == m.summary


def test_runtime_config_roundtrip():
    """Dashboard write -> Redis cache -> Python read pattern."""
    cfg = RuntimeConfig()
    blob = json.dumps(asdict(cfg))
    parsed = json.loads(blob)
    restored = RuntimeConfig(**parsed)
    assert restored.default_language == cfg.default_language
    assert restored.min_endpointing_delay == cfg.min_endpointing_delay
    assert restored.llm_temperature == cfg.llm_temperature


def test_runtime_config_partial_fields_constructor():
    """If Supabase only returns SOME fields (older DB row missing new
    columns), constructor must accept partial init."""
    # Construct with a minimal subset.
    cfg = RuntimeConfig(default_language="te")
    assert cfg.default_language == "te"
    # Other fields use defaults.
    assert cfg.llm_temperature is not None


def test_call_memory_handles_special_chars_in_summary():
    """Summary might contain quotes, backslashes, newlines."""
    weird = 'He said "yes" and\\then \n leaving'
    m = CallMemory(call_id="c6", summary=weird)
    blob = json.dumps(asdict(m))
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.summary == weird


def test_call_memory_handles_emoji_in_summary():
    m = CallMemory(call_id="c7", summary="happy caller 😀😀")
    blob = json.dumps(asdict(m), ensure_ascii=False)
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.summary == m.summary


def test_call_memory_nested_slots_roundtrip():
    """slots dict can have nested values."""
    m = CallMemory(call_id="c8", slots={
        "order_id": "X-123",
        "items": ["a", "b", "c"],
        "amount": 1234.56,
        "active": True,
        "ref": None,
    })
    blob = json.dumps(asdict(m))
    parsed = json.loads(blob)
    restored = CallMemory(**parsed)
    assert restored.slots == m.slots
