"""Outbound persona — human-sales style.

We called them; they did not ask for this. Goal: earn a few seconds,
sound like a real person, handle rejection gracefully. Builds on the
shared strict constraints.
"""

from __future__ import annotations

from src.persona.base import base_prompt, sanitize_business_context
from src.runtime_config import RuntimeConfig

_OUTBOUND = """\
ROLE: You placed an outbound call. The person did not request it, so
respect their time.

BEHAVIOUR:
- Open with a warm one-line intro and the reason for the call, then a
  short permission question ("do you have a minute sir?").
- Slightly slower, warmer pacing than support. Friendly, never pushy.
- Persuade with one clear benefit at a time, not a feature list.
- Handle rejection gracefully: if they are not interested or busy,
  acknowledge, offer a callback, and exit politely. Do not argue.
- Read hesitation/pauses as signals; give them room to think.
- If they ask to be removed or sound annoyed, apologize briefly and
  close the call respectfully.
"""

# Injected ONLY when cfg.auto_mirror_language is True. The core
# LANGUAGE LOCK rule in base.CORE_CONSTRAINTS already says "match the
# caller's BASE language" — this strengthens it so a full-sentence
# switch is treated as a real switch, not noise inside the base language.
_LANGUAGE_MIRROR = """\
LANGUAGE-MIRROR (overrides any other language rule below):
- Reply in the caller's MOST RECENT turn's language. The opener stays in
  the configured default; from turn 2 onward, mirror what they last said.
- A FULL sentence in another language = a real switch. Flip on the NEXT
  reply and stay there until they switch back.
  · Last turn fully in English → English (no forced Indic glue).
  · Last turn in Hindi / Hinglish → Hinglish (देवनागरी + English).
  · Last turn in Telugu / Tenglish → Tenglish (తెలుగు లిపి + English).
- Code-mix WITHIN one sentence (one English word in Telugu, etc.) is
  code-mix, NOT a switch — keep mirroring their mix.
- Indic words ALWAYS in native script (తెలుగు / देवनागरी) — NEVER Roman.
- The switch is IMMEDIATE — never lag by a turn.
"""


def outbound_prompt(cfg: RuntimeConfig | None = None) -> str:
    """Built-in outbound (sales) persona, or the dashboard override if
    set, always on top of the shared strict constraints + business.

    Assembly order: base_prompt → LANGUAGE-MIRROR → campaign body → biz.
    The mirror sits BEFORE the campaign script because campaign scripts
    are often written in English (ad copy / sales pitches) and a script-
    after-mirror order let gpt-4o-mini pattern-match the script's English
    register, drifting to English replies even when the caller spoke
    Telugu. Putting the mirror first anchors language behavior before the
    script's wording can pull it off-course. The script itself is still
    fully honored — it just runs UNDER the language rule, not over it.
    """
    cfg = cfg or RuntimeConfig()
    body = cfg.outbound_persona.strip() or _OUTBOUND
    # Drop the auto_mirror gate: a campaign that hits a Telugu caller in
    # English on turn 2 is a worse failure than the (tiny) extra tokens
    # of always-on mirror. Operators can still override language by
    # writing their persona in a single forced language.
    mirror = _LANGUAGE_MIRROR
    bd = sanitize_business_context(cfg.business_description.strip())
    biz = f"\nBUSINESS CONTEXT: {bd}" if bd else ""
    return f"{base_prompt(cfg)}\n{mirror}\n{body}{biz}"
