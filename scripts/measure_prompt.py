"""Measure the token size of each persona piece so we know exactly
where the ~12.9k-token prompt comes from. Read-only; deletes nothing."""

from __future__ import annotations

from src.persona import base
from src.prompt_budget import count_tokens


def t(label: str, text: str) -> int:
    n = count_tokens(text or "")
    print(f"{label:<32} {n:>6} tok  ({len(text or '')} chars)")
    return n


def main() -> None:
    print("=== Persona piece token sizes (cl100k_base estimate) ===")
    core = t("CORE_CONSTRAINTS", base.CORE_CONSTRAINTS)
    style = t("_BUILTIN_STYLE_EXAMPLES", base._BUILTIN_STYLE_EXAMPLES)
    appt = t("_APPOINTMENT_BLOCK", base.USE_CASE_BLOCKS["appointment"])

    # Full assembled appointment persona (what a booking call actually sends).
    class _Cfg:
        use_case_type = "appointment"
        style_examples = ""
        business_description = ""

    full = base.base_prompt(_Cfg())
    print("-" * 60)
    t("FULL appointment base_prompt", full)
    print("-" * 60)
    print(f"core+style+appt subtotal: {core + style + appt} tok")


if __name__ == "__main__":
    main()
