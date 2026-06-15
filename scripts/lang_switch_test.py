"""Validate language switching + brevity OFFLINE — replicates llm_node's
per-turn language detection + marker injection against the live model, so
we can prove the language-lag fix works without burning a phone call.

For each caller turn (mix of Telugu/English/Hindi) it: detects the variety
the same way agent.llm_node does, injects the matching LANGUAGE-OVERRIDE +
brevity markers, calls the LLM, then checks the reply's script + length.

    python -m scripts.lang_switch_test
"""

from __future__ import annotations

import asyncio
import re

from src.agent import _detect_conversational_variety
from src.persona.outbound import outbound_prompt
from src.runtime_config import load_runtime_config

# (caller_text, expected_variety) — the switches that broke on the real call.
_TURNS = [
    ("ఆ చెప్పండి, ఎవరు మాట్లాడుతోంది?", "te-mix"),
    ("Where is your clinic located and what services do you offer?", "en"),
    ("मुझे Hindi में बताइए please, क्या services हैं?", "hi-mix"),
    ("acne treatment ela chestaru mీ clinic lo?", "te-mix"),
    ("Okay, can you tell me the timings in English?", "en"),
]

# Mirror the per-turn markers agent.llm_node injects (condensed).
_MARK = {
    "en": "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: en. Reply 100% English, ZERO Telugu/Hindi. Overrides campaign default.",
    "te-mix": "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: te-mix. Reply in Tenglish: Telugu script (తెలుగు లిపి) connectors + English script for business terms. NEVER Roman Telugu.",
    "hi-mix": "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: hi-mix. Reply in Hinglish: Devanagari (देवनागरी) connectors + English script for business terms. NEVER Roman Hindi.",
    "te": "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: te-mix. Reply in Tenglish (Telugu script + English business words).",
    "hi": "LANGUAGE-OVERRIDE-FOR-NEXT-REPLY: hi-mix. Reply in Hinglish (Devanagari + English business words).",
}
_BREVITY = ("LENGTH-FOR-NEXT-REPLY: 1-2 SHORT spoken sentences (max ~30 words), "
            "then a short follow-up question. NEVER a paragraph/list/lecture.")


def _script(s: str) -> str:
    te = bool(re.search(r"[ఀ-౿]", s))
    hi = bool(re.search(r"[ऀ-ॿ]", s))
    en = bool(re.search(r"[A-Za-z]", s))
    return ("Telugu " if te else "") + ("Hindi " if hi else "") + ("English" if en else "") or "?"


def _wc(s: str) -> int:
    return len(s.split())


async def main() -> None:
    import openai
    from src.config import settings

    cfg = await load_runtime_config()
    print(f"=== model={cfg.llm_model} · default_lang={cfg.default_language} ===\n")
    system = outbound_prompt(cfg)
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    messages = [{"role": "system", "content": system}]
    prev = cfg.default_language
    for text, expected in _TURNS:
        detected = _detect_conversational_variety(text, prev)
        # collapse pure te/hi -> mix (same product rule as llm_node)
        eff = {"te": "te-mix", "hi": "hi-mix"}.get(detected, detected)
        prev = detected
        turn = list(messages) + [
            {"role": "system", "content": _MARK.get(eff, "")},
            {"role": "system", "content": _BREVITY},
            {"role": "user", "content": text},
        ]
        try:
            r = await client.chat.completions.create(
                model="gpt-4o-mini", messages=turn, temperature=0.3,
                max_tokens=250,
            )
            reply = r.choices[0].message.content or ""
        except Exception as e:
            print(f"ERR: {e}")
            break
        messages += [{"role": "user", "content": text},
                     {"role": "assistant", "content": reply}]
        ok = "✓" if (detected == expected or eff == expected) else "✗"
        print(f"🧑 [{expected}] {text}")
        print(f"   detected={detected}  {ok}")
        print(f"🤖 [{_script(reply)} · {_wc(reply)}w] {reply[:200]}\n")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
