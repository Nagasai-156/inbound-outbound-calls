"""Persona rule presence tests.

The persona prompt is the LLM's primary behavior contract. We've added
several critical rules this session (VERBAL-CHECK-COMMITMENT, ONE-
QUESTION-PER-TURN, etc.). These tests ensure those rules are actually
present in the assembled prompt — so a future refactor that drops a
section is caught immediately.
"""

from __future__ import annotations

from src.persona.base import base_prompt, USE_CASE_BLOCKS
from src.runtime_config import RuntimeConfig


def test_verbal_check_commitment_rule_present():
    """Agent must not say 'checking' without a same-turn tool call."""
    p = base_prompt(RuntimeConfig())
    assert "VERBAL-CHECK-COMMITMENT" in p
    # Must list the trigger phrases the LLM should recognize.
    assert "checking" in p.lower()
    assert "let me check" in p.lower()
    # Must reference at least one Indic trigger.
    assert "ఒక్క నిమిషం" in p or "చెక్ చేస్తాను" in p


def test_action_hallucination_rule_present():
    """Already-existing rule: never say 'booked' without book_appointment
    firing first. Regression guard."""
    p = base_prompt(RuntimeConfig())
    assert "ACTION-HALLUCINATION" in p
    assert "book_appointment" in p


def test_one_question_per_turn_rule_in_appointment_block():
    """The appointment-flow rule preventing multi-question stacking."""
    appt = USE_CASE_BLOCKS.get("appointment", "")
    assert appt, "appointment use-case block must exist"
    assert "ONE-QUESTION-PER-TURN" in appt
    # Anti-example must be present so the LLM has a concrete pattern.
    assert "ఏ డాక్టర్" in appt


def test_table_grounding_law_in_appointment_block():
    """Booking truth must come from the tool, never memory."""
    appt = USE_CASE_BLOCKS["appointment"]
    assert "TABLE-GROUNDING-LAW" in appt
    assert "check_appointment_slots" in appt


def test_cancel_flow_present_in_appointment_block():
    """Cancel intent must be a discrete rule (not a sub-bullet)."""
    appt = USE_CASE_BLOCKS["appointment"]
    assert "CANCEL flow" in appt
    assert "cancel_all_appointments" in appt
    assert "cancel_appointment" in appt


def test_reschedule_block_has_table_grounding():
    resched = USE_CASE_BLOCKS["reschedule"]
    assert "TABLE-GROUNDING-LAW" in resched
    assert "my_appointment" in resched


def test_reminder_block_calls_my_appointment_first():
    rem = USE_CASE_BLOCKS["reminder"]
    assert "my_appointment" in rem
    assert "REMINDER" in rem
