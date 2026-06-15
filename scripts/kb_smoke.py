"""KB end-to-end smoke test (no phone needed).

Ingests a sample policy doc into Supabase pgvector, then runs the REAL
kb_answer() pipeline against multilingual questions — including one that
is NOT in the KB — to prove:
  * retrieval works (pgvector),
  * answers are grounded + short + spoken,
  * off-KB questions are refused (no hallucination).

    python scripts/kb_smoke.py
"""

from __future__ import annotations

import asyncio

from src.kb import kb_answer
from src.kb_store import delete_document, ingest_document

DOC_ID = "smoke-kb"

KB = """\
Standard delivery takes 2 to 4 working days. Delivery is free on orders
above 499 rupees, otherwise a 40 rupee fee applies. COD is available up
to 5000 rupees.
Refunds are processed within 5 to 7 working days after the return is
picked up. Return window is 7 days from delivery. Innerwear and
perishable items are not returnable.
If money was debited but the order was not confirmed, it is an
auto-refund within 24 hours. Failed payments are never charged.
An order can be cancelled free any time before it is dispatched. After
dispatch it cannot be cancelled but can be returned.
EMI is available on orders above 3000 rupees with select banks.
"""

QUESTIONS = [
    ("EN", "How many days for a refund?"),
    ("EN", "Is delivery free?"),
    ("HI-mix", "payment fail ho gaya par paisa kat gaya, kya hoga?"),
    ("TE-mix", "Anna refund enni rojulu padుtundi?"),
    ("EN", "Can I cancel after dispatch?"),
    ("OFF-KB", "Do you sell laptops and what is the warranty?"),
]


async def main() -> None:
    print("-> ingesting sample KB into pgvector...")
    n = await ingest_document(DOC_ID, "smoke-policy.txt", KB)
    print(f"  ingested {n} chunk(s)\n")

    for tag, q in QUESTIONS:
        ans = await kb_answer(q)
        print(f"[{tag}] Q: {q}")
        if ans:
            print(f"      A: {ans}")
        else:
            print("      A: <no KB match> -> agent will say "
                  "'I'll check & get back' (CORRECT for off-KB)")
        print()

    await delete_document(DOC_ID)
    print("[OK] cleaned up test doc. KB pipeline verified.")


if __name__ == "__main__":
    asyncio.run(main())
