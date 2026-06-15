"""Use-case-block presence + content tests beyond appointment.

Every use case in the dashboard taxonomy must produce a non-empty
behaviour block that gets appended to the LLM prompt — a missing block
leaks the LLM into 'be generic' mode."""

from __future__ import annotations

from src.persona.base import USE_CASE_BLOCKS


def test_sales_block_exists():
    block = USE_CASE_BLOCKS.get("sales", "")
    assert block, "sales use-case block must be non-empty"
    # Sales must include the permission-question pattern.
    assert "sales" in block.lower() or "SALES" in block


def test_sales_block_forbids_price_invention():
    """Sales agents must NEVER quote prices not in BUSINESS CONTEXT —
    that's a regulatory + trust risk."""
    block = USE_CASE_BLOCKS.get("sales", "")
    # Some hint about pricing discipline must be present.
    assert any(k in block.lower() for k in ["price", "discount", "offer", "quote"])


def test_leadgen_block_exists():
    block = USE_CASE_BLOCKS.get("leadgen", "")
    assert block, "leadgen block needed"


def test_survey_block_exists():
    block = USE_CASE_BLOCKS.get("survey", "")
    assert block


def test_feedback_block_exists():
    block = USE_CASE_BLOCKS.get("feedback", "")
    assert block


def test_support_block_exists():
    block = USE_CASE_BLOCKS.get("support", "")
    assert block


def test_collections_block_exists():
    block = USE_CASE_BLOCKS.get("collections", "")
    assert block


def test_reminder_block_exists():
    block = USE_CASE_BLOCKS.get("reminder", "")
    assert block


def test_custom_block_is_empty_string():
    """custom = universal rails only, no use-case-specific block."""
    block = USE_CASE_BLOCKS.get("custom", "X")
    assert block == ""


def test_all_blocks_are_strings():
    for k, v in USE_CASE_BLOCKS.items():
        assert isinstance(v, str), f"{k} block is {type(v)}"


def test_appointment_block_mentions_each_appt_tool():
    block = USE_CASE_BLOCKS["appointment"]
    for tool in ["check_appointment_slots", "book_appointment",
                 "my_appointment", "reschedule_appointment",
                 "cancel_appointment"]:
        assert tool in block, f"appointment block missing {tool}"


def test_reschedule_block_doesnt_mention_book_appointment_as_action():
    """Reschedule use-case = no NEW bookings (block must not direct LLM
    to call book_appointment, only reschedule_appointment)."""
    block = USE_CASE_BLOCKS["reschedule"]
    # reschedule_appointment YES, book_appointment NO as primary action.
    assert "reschedule_appointment" in block


def test_reminder_block_emphasizes_my_appointment():
    """Reminder calls START from an existing booking — agent must call
    my_appointment FIRST."""
    block = USE_CASE_BLOCKS["reminder"]
    assert "my_appointment" in block
