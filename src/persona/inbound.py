"""Inbound persona — support style.

Caller initiated the call with a problem. Goal: understand fast, resolve
fast, stay calm. Builds on the shared strict constraints.
"""

from __future__ import annotations

from src.persona.base import base_prompt, sanitize_business_context
from src.runtime_config import RuntimeConfig

_INBOUND = """\
ROLE: You answered an incoming support call. The caller has a problem
(order status, payment, refund, general help).

BEHAVIOUR:
- Open by listening, not pitching. One short greeting, then let them talk.
- Acknowledge the problem in their language before solving it.
- Drive to resolution quickly; don't make them repeat themselves.
- If you must check something, say so briefly ("one second sir") and
  continue — never go silent.
- Stay calm and warm even if the caller is angry; match their urgency
  with speed, not volume.
"""


def inbound_prompt(cfg: RuntimeConfig | None = None) -> str:
    """Built-in inbound persona, or the dashboard override if set, always
    on top of the shared strict constraints + any business context."""
    cfg = cfg or RuntimeConfig()
    body = cfg.inbound_persona.strip() or _INBOUND
    bd = sanitize_business_context(cfg.business_description.strip())
    biz = f"\nBUSINESS CONTEXT: {bd}" if bd else ""
    return f"{base_prompt(cfg)}\n{body}{biz}"
