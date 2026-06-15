"""Pre-warm the Redis semantic cache with top FAQ answers.

So the very first caller asking a common question (refund / payment /
delivery / pricing) gets a ~cache-latency answer instead of waiting on
an OpenAI round-trip. Edit FAQS to match your business, then run:

    python scripts/warm_cache.py
"""

from __future__ import annotations

import asyncio

from src.cache import semantic_cache

# (question phrasing, short spoken answer). Keep answers voice-shaped:
# 1-2 short sentences, conversational, no document language.
FAQS: list[tuple[str, str]] = [
    ("how long does delivery take",
     "Delivery usually takes 2 to 4 days sir."),
    ("delivery kitne din me hoga",
     "Sir delivery do se chaar din me ho jaata hai."),
    ("delivery enni rojulu padutundi",
     "Sir, delivery rendu nunchi nalugu rojulu padutundi."),
    ("how do i get a refund",
     "Refund 5 to 7 working days lo account ki vastundi sir."),
    ("refund kitne din me aata hai",
     "Sir refund paanch se saat din me aa jaata hai."),
    ("my payment failed but money was debited",
     "Don't worry sir, failed payment 24 hours lo auto refund avutundi."),
    ("payment fail ho gaya paisa kat gaya",
     "Sir tension mat lijiye, paisa 24 ghante me wapas aa jaayega."),
    ("how can i cancel my order",
     "Order dispatch avvakamunde cancel cheyochu sir, app lo."),
    ("what are your charges",
     "Sir, standard delivery free, express ki chinna charge untundi."),
]


async def _run() -> None:
    ok = 0
    for question, answer in FAQS:
        await semantic_cache.store(question, answer)
        ok += 1
        print(f"cached: {question!r}")
    print(f"\nWarmed {ok}/{len(FAQS)} FAQ entries into the semantic cache.")


if __name__ == "__main__":
    asyncio.run(_run())
