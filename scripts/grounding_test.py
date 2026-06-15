"""Validate the anti-fabrication fix: ask the specifics that are NOT in
BUSINESS CONTEXT (doctor education, years, certifications) and confirm
the agent DEFERS instead of inventing ("renowned institutions" etc.).
Also asks an IN-CONTEXT question to confirm it still answers confidently.
"""

from __future__ import annotations

import asyncio

from src.persona.outbound import outbound_prompt
from src.runtime_config import load_runtime_config

_Q = [
    ("where did the doctors complete their education?", "DEFER (not in context)"),
    ("how many years of experience does Dr Anjali have?", "DEFER (not in context)"),
    ("what is the consultation fee?", "ANSWER (Rs 800 — in context)"),
    ("what services do you offer?", "ANSWER (in context)"),
]


async def main() -> None:
    import openai
    from src.config import settings

    cfg = await load_runtime_config()
    system = outbound_prompt(cfg)
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    print(f"=== anti-fabrication check · {cfg.llm_model} ===\n")
    for q, expect in _Q:
        msgs = [
            {"role": "system", "content": system},
            {"role": "system", "content": "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: en. Reply in English."},
            {"role": "user", "content": q},
        ]
        try:
            r = await client.chat.completions.create(
                model="gpt-4o-mini", messages=msgs, temperature=0.3, max_tokens=180,
            )
            reply = r.choices[0].message.content or ""
        except Exception as e:
            print("ERR:", e)
            break
        print(f"🧑 {q}\n   [expect: {expect}]")
        print(f"🤖 {reply}\n")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
