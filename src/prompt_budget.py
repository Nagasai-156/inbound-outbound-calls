"""Hard per-turn LLM prompt token budget.

Two real, observed production failures this prevents:

  1. Groq free-tier 413 dead-air. On real calls the LLM prompt grew
     turn-over-turn (unbounded chat history — `cost.trim_history` was
     never wired into the live path) from ~7.6k to ~12.9k tokens,
     blowing past the 12k tokens-per-minute cap → 4 failed retries →
     ~15s of dead air → dropped call (see worker.err.log.8).

  2. Compounding TTFT. Every extra ~1k prompt tokens adds measurable
     prefill latency. An unbounded prompt makes the agent get SLOWER
     the longer the caller talks — the opposite of what a good call
     needs. Bounding the prompt keeps TTFT flat across a long call.

Strategy (loss-minimising): keep ALL system messages (the persona +
the per-turn injected markers carry every behavioural guarantee) and as
many of the MOST-RECENT conversational turns as fit under the budget.
The OLDEST raw turns are dropped first — and that loses very little,
because `CallMemory` already preserves the durable gist (name, intent,
emotion, slots, rolling summary) as a compact system line.

Token counting uses tiktoken (`cl100k_base`) which tokenises Telugu /
Devanagari accurately (multiple tokens per glyph), with a char/4
fallback if tiktoken is unavailable. The count is an estimate — exact
per-model tokenisation varies (Groq Llama ≠ OpenAI BPE) — but it is
consistent and conservative enough to keep us safely under hard caps.
"""

from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger("prompt_budget")

# Per-message structural overhead (role tags, delimiters) — mirrors
# OpenAI's documented ~4-token-per-message accounting so our estimate
# tracks the provider's billed prompt size closely.
_PER_MSG_OVERHEAD = 4


@lru_cache(maxsize=4)
def _encoder(model: str | None = None):
    """Cached tiktoken encoder. cl100k_base is a good cross-model
    approximation (used by gpt-4o family; reasonable for Llama/Sarvam).
    Returns None if tiktoken can't load, so callers fall back to char/4."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # pragma: no cover - tiktoken always present via openai
        logger.debug("tiktoken unavailable; using char/4 token estimate")
        return None


def count_tokens(text: str, model: str | None = None) -> int:
    """Estimate the token count of a plain string."""
    if not text:
        return 0
    enc = _encoder(model)
    if enc is None:
        return max(1, len(text) // 4)
    try:
        return len(enc.encode(text))
    except Exception:  # pragma: no cover - defensive
        return max(1, len(text) // 4)


def _item_text(item) -> str:
    """Best-effort plain-text extraction from any ChatContext item
    (ChatMessage / FunctionCall / FunctionCallOutput), across livekit
    plugin versions, for token estimation only."""
    # ChatMessage exposes a joined text_content.
    txt = getattr(item, "text_content", None)
    if isinstance(txt, str) and txt:
        return txt
    content = getattr(item, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return " ".join(c for c in content if isinstance(c, str))
    # FunctionCall: name + arguments. FunctionCallOutput: output.
    parts: list[str] = []
    for attr in ("name", "arguments", "output"):
        v = getattr(item, attr, None)
        if isinstance(v, str) and v:
            parts.append(v)
    if parts:
        return " ".join(parts)
    return str(content or "")


def item_tokens(item, model: str | None = None) -> int:
    """Estimate the token cost of a single ChatContext item."""
    return count_tokens(_item_text(item), model) + _PER_MSG_OVERHEAD


def _is_system(item) -> bool:
    return getattr(item, "role", None) == "system"


def enforce_prompt_budget(
    chat_ctx,
    max_tokens: int,
    *,
    model: str | None = None,
    keep_recent_msgs: int = 4,
) -> int:
    """Trim `chat_ctx.items` IN PLACE until the estimated prompt fits
    `max_tokens`, dropping the OLDEST non-system items first.

    Guarantees:
      * Every system message is kept (persona + per-turn markers — these
        encode the behavioural rails, never droppable).
      * The most-recent `keep_recent_msgs` conversational items are kept
        even if that exceeds the budget (a turn must always see the
        immediate exchange; better a slightly-large prompt than amnesia).
      * Original ordering is preserved (the language markers are placed
        at specific positions on purpose — we never reorder, only drop).
      * A kept suffix never starts with an orphaned tool output whose
        matching call was dropped (would confuse the model) — such a
        leading orphan is dropped too.

    Returns the number of items dropped (0 if already within budget).
    `chat_ctx` MUST already be a fork/copy — this mutates it.
    """
    if max_tokens <= 0:
        return 0
    items = chat_ctx.items
    n = len(items)
    if n == 0:
        return 0

    tokens = [item_tokens(it, model) for it in items]
    total = sum(tokens)
    if total <= max_tokens:
        return 0

    # Droppable = non-system items, oldest first. Protect the most-recent
    # `keep_recent_msgs` of them so the immediate exchange always survives.
    droppable = [i for i in range(n) if not _is_system(items[i])]
    protected = set(droppable[-keep_recent_msgs:]) if keep_recent_msgs else set()

    keep = [True] * n
    dropped = 0
    for i in droppable:
        if total <= max_tokens:
            break
        if i in protected:
            continue
        keep[i] = False
        total -= tokens[i]
        dropped += 1

    if not dropped:
        return 0

    new_items = [items[i] for i in range(n) if keep[i]]

    # Heal an orphaned leading tool output (FunctionCallOutput whose
    # FunctionCall we just dropped). Identify tool outputs structurally:
    # they have an `output`/`call_id` attr and no chat role.
    while new_items:
        head = new_items[0]
        is_orphan_output = (
            not _is_system(head)
            and getattr(head, "role", None) not in ("user", "assistant")
            and (hasattr(head, "output") or hasattr(head, "call_id"))
        )
        if is_orphan_output:
            new_items.pop(0)
            dropped += 1
        else:
            break

    chat_ctx.items[:] = new_items
    logger.info(
        "prompt budget: trimmed %d old item(s) -> ~%d tokens (cap=%d)",
        dropped, total, max_tokens,
    )
    return dropped
