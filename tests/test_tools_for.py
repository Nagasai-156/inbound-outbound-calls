"""tools_for() tool gating tests — per-use-case + dashboard override.

The agent's tool set per call is decided by `tools_for(use_case, enabled)`.
A misconfigured gate could either (a) give a SURVEY agent booking tools
(catastrophic — it could book appointments it shouldn't) or (b) deny
an appointment campaign its booking tools (caller can never book)."""

from __future__ import annotations

from src.tools import (
    tools_for,
    kb_search,
    end_call,
    check_appointment_slots,
    book_appointment,
    my_appointment,
    reschedule_appointment,
    cancel_appointment,
    cancel_all_appointments,
    order_status,
    _BASE_TOOLS,
    _USE_CASE_TOOLS,
    _NAMED_TOOLS,
)


# ─── _BASE_TOOLS contract ──────────────────────────────────────────


def test_kb_search_is_base():
    """Every call needs kb_search for grounded answers."""
    assert kb_search in _BASE_TOOLS


def test_end_call_is_base():
    """Every call needs end_call to hang up cleanly."""
    assert end_call in _BASE_TOOLS


def test_base_tools_only_contains_base_two():
    """Base tools must NOT include any booking/order tools — those are
    use-case-gated. A regression that adds booking to base would let a
    survey campaign book appointments."""
    assert len(_BASE_TOOLS) == 2


# ─── tools_for use-case map ────────────────────────────────────────


def test_appointment_use_case_has_all_appt_tools():
    tools = tools_for("appointment")
    for t in (check_appointment_slots, book_appointment, my_appointment,
              reschedule_appointment, cancel_appointment,
              cancel_all_appointments):
        assert t in tools


def test_appointment_use_case_has_base_tools():
    tools = tools_for("appointment")
    assert kb_search in tools
    assert end_call in tools


def test_reminder_use_case_gets_appt_tools():
    """Reminders may need to reschedule/cancel — same toolset as
    appointment."""
    tools = tools_for("reminder")
    assert book_appointment in tools or check_appointment_slots in tools


def test_reschedule_use_case_excludes_book():
    """Reschedule = no new bookings — only my_appointment + reschedule
    + cancel."""
    tools = tools_for("reschedule")
    assert book_appointment not in tools
    assert reschedule_appointment in tools


def test_sales_use_case_has_NO_booking_tools():
    """Sales calls MUST NOT have booking tools — they'd hallucinate
    bookings and the user would be surprised."""
    tools = tools_for("sales")
    assert book_appointment not in tools
    assert check_appointment_slots not in tools


def test_survey_use_case_has_NO_booking_or_order_tools():
    tools = tools_for("survey")
    assert book_appointment not in tools
    assert order_status not in tools


def test_leadgen_use_case_has_NO_booking_tools():
    tools = tools_for("leadgen")
    assert book_appointment not in tools


def test_feedback_use_case_minimal_tools():
    tools = tools_for("feedback")
    # Only base tools.
    assert len(tools) == len(_BASE_TOOLS)


def test_custom_use_case_gets_order_status_only_for_extra():
    """Custom = safest default: kb_search + end_call + order_status.
    No booking."""
    tools = tools_for("custom")
    assert order_status in tools
    assert book_appointment not in tools


def test_unknown_use_case_falls_back_to_custom():
    """Operator typo'd a non-existent use_case → safe custom behaviour."""
    tools = tools_for("xyz-not-a-real-use-case")
    custom_tools = tools_for("custom")
    assert tools == custom_tools


def test_none_use_case_falls_back_to_custom():
    assert tools_for(None) == tools_for("custom")


def test_empty_use_case_falls_back_to_custom():
    assert tools_for("") == tools_for("custom")


def test_use_case_normalised_to_lowercase():
    """Dashboard could send "Appointment" with caps; tools_for must
    handle case-insensitively."""
    assert tools_for("APPOINTMENT") == tools_for("appointment")
    assert tools_for("Appointment") == tools_for("appointment")


# ─── enabled override ──────────────────────────────────────────────


def test_enabled_override_exposes_only_named_tools():
    """Dashboard 'enabledTools' multi-select must override use-case map
    completely (still keeps base tools)."""
    tools = tools_for("appointment", enabled="order_status")
    assert order_status in tools
    # Booking tools should NOT be present, even though use_case=appointment.
    assert book_appointment not in tools
    assert check_appointment_slots not in tools
    # But base tools are always there.
    assert kb_search in tools


def test_enabled_csv_with_multiple_tools():
    tools = tools_for("custom", enabled="book_appointment,check_appointment_slots,my_appointment")
    assert book_appointment in tools
    assert check_appointment_slots in tools
    assert my_appointment in tools


def test_enabled_silently_drops_unknown_names():
    """Operator typos in enabledTools CSV must not crash a call."""
    tools = tools_for("appointment", enabled="book_appointment,nonexistent_tool")
    assert book_appointment in tools


def test_enabled_with_whitespace_handled():
    tools = tools_for("appointment", enabled="  book_appointment ,  order_status  ")
    assert book_appointment in tools
    assert order_status in tools


def test_empty_enabled_string_uses_use_case_map():
    """enabledTools="" must fall through to the use-case default."""
    tools_empty = tools_for("appointment", enabled="")
    tools_default = tools_for("appointment", enabled=None)
    assert tools_empty == tools_default


def test_whitespace_only_enabled_uses_use_case_map():
    tools_ws = tools_for("appointment", enabled="   ")
    tools_default = tools_for("appointment", enabled=None)
    assert tools_ws == tools_default


# ─── _NAMED_TOOLS contract ────────────────────────────────────────


def test_named_tools_has_all_publicly_documented():
    """Every tool that the dashboard offers in `AGENT_TOOLS` must have
    a matching entry in _NAMED_TOOLS for the enabledTools CSV to work."""
    expected = {
        "check_appointment_slots", "book_appointment", "my_appointment",
        "reschedule_appointment", "cancel_appointment",
        "cancel_all_appointments", "order_status",
    }
    actual = set(_NAMED_TOOLS.keys())
    missing = expected - actual
    assert not missing, f"_NAMED_TOOLS missing: {missing}"


def test_named_tools_excludes_base():
    """kb_search and end_call must NOT be in _NAMED_TOOLS — they're
    base-always tools, dashboard shouldn't be able to disable them."""
    assert "kb_search" not in _NAMED_TOOLS
    assert "end_call" not in _NAMED_TOOLS


# ─── _USE_CASE_TOOLS contract ─────────────────────────────────────


def test_every_dashboard_use_case_has_a_block():
    """Use cases offered in dashboard.lib.options.USE_CASES must each
    have a tool list defined."""
    dashboard_use_cases = {
        "appointment", "reminder", "reschedule",
        "sales", "leadgen", "survey", "feedback", "support",
        "collections", "custom",
    }
    for uc in dashboard_use_cases:
        assert uc in _USE_CASE_TOOLS, f"Missing _USE_CASE_TOOLS[{uc!r}]"
