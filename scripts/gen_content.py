"""Offline LLM content generation -> Redis.

Generates large, natural, business/persona-specific pools of FILLERS and
CANNED replies in Telugu, Hindi and English, and writes them to Redis.
The voice agent then serves these instantly at call time with anti-repeat
rotation — dynamic content, ZERO runtime LLM latency.

Re-run whenever the business/persona changes; no code edits needed.

    python scripts/gen_content.py
    python scripts/gen_content.py --business "Acme food delivery" --n 12
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from openai import AsyncOpenAI

from src.config import settings
from src.content import (
    CANNED_KEY,
    DEFAULT_CANNED,
    FILLER_KEY,
    LANGS,
)

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("gen_content")

_LANG_NAME = {"te": "Telugu", "hi": "Hindi", "en": "Indian English"}

_INTENT_BRIEF = {
    "greeting": "open the call warmly and invite the caller to speak",
    "affirm": "acknowledge / agree briefly",
    "deny": "politely accept a 'no' and move on",
    "thanks": "respond to a thank-you",
    "bye": "close the call politely",
    "repeat": "ask the caller to repeat because audio was unclear",
}

_SYS = (
    "You write lines for a human phone call-center executive. Lines must "
    "be SHORT (max ~8 words), spoken, warm, non-robotic, and never formal. "
    "Use natural code-mixing where it sounds human. Return ONLY a JSON "
    "array of strings, no prose."
)


async def _gen(client: AsyncOpenAI, prompt: str, fallback: list[str]) -> list[str]:
    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _SYS},
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = text[text.find("[") : text.rfind("]") + 1]
        out = [str(x).strip() for x in json.loads(text) if str(x).strip()]
        return out or fallback
    except Exception:
        logger.warning("generation failed; keeping defaults", exc_info=True)
        return fallback


async def _run(business: str, n: int) -> None:
    import redis.asyncio as redis

    client = AsyncOpenAI(api_key=settings.openai_api_key or None)
    r = redis.from_url(settings.redis_url, decode_responses=True)
    biz = f" The business is: {business}." if business else ""

    for lang in LANGS:
        ln = _LANG_NAME[lang]
        fillers = await _gen(
            client,
            f"Generate {n} distinct natural FILLER acknowledgements in {ln} "
            f"a support agent says while looking something up "
            f'(like "okay sir, one second...").{biz}',
            [],
        )
        if fillers:
            await r.set(FILLER_KEY.format(lang=lang), json.dumps(fillers,
                                                                 ensure_ascii=False))
            print(f"filler:{lang} -> {len(fillers)} lines")

        for intent, brief in _INTENT_BRIEF.items():
            fb = DEFAULT_CANNED.get(intent, {}).get(lang, [])
            lines = await _gen(
                client,
                f"Generate {n} distinct natural lines in {ln} for a support "
                f"agent to {brief}.{biz}",
                fb,
            )
            await r.set(
                CANNED_KEY.format(intent=intent, lang=lang),
                json.dumps(lines, ensure_ascii=False),
            )
            print(f"canned:{intent}:{lang} -> {len(lines)} lines")

    print("\nDone. The agent will load these from Redis on next start.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--business", default="", help="short business description")
    ap.add_argument("--n", type=int, default=10, help="variants per pool")
    args = ap.parse_args()
    asyncio.run(_run(args.business, args.n))
