# Sentence Streaming Implementation Plan

## Problem
Currently, the agent waits for the FULL LLM response before sending ANY text to TTS.

Example timeline:
```
User stops: 0ms
Endpointing detects: 736ms
LLM starts: 736ms
LLM TTFT (first token): 736ms + 3257ms = 3993ms
LLM complete: 736ms + 4500ms = 5236ms
TTS starts: 5236ms
TTS TTFB: 5236ms + 459ms = 5695ms
User hears audio: 5695ms (5.7 seconds!)
```

## Solution: Sentence-by-Sentence Streaming

Stream the LLM response in real-time, send each complete sentence to TTS immediately.

New timeline:
```
User stops: 0ms
Endpointing: 736ms
LLM TTFT (first token): 736ms + 900ms = 1636ms
First sentence complete: 1636ms + 400ms = 2036ms
TTS starts (sentence 1): 2036ms
TTS TTFB: 2036ms + 260ms = 2296ms
User hears audio: 2296ms (2.3 seconds vs 5.7s!)

While sentence 1 plays (~1s), LLM generates sentence 2 (parallel)
```

**Perceived latency: ~1.2s** (instant feel!)

---

## Implementation Approach

LiveKit Agents SDK already supports streaming! The `VoiceAssistant` has a `before_tts_cb` hook that receives text chunks in real-time.

### Option A: Use LiveKit's Built-in Sentence Streaming (EASIEST)

The SDK's `VoiceAssistant` already has:
- `allow_interruptions=True` — user can barge in
- `before_tts_cb` — intercept LLM chunks before TTS
- `min_endpointing_delay` — tighter VAD

**What we need to do:**
1. Enable sentence-level chunking in LLM stream
2. LiveKit SDK will automatically send each sentence to TTS
3. TTS streams audio back (already working with Cartesia WebSocket)

### Current Agent Architecture (src/agent.py)

```python
# Line ~300-400: Agent uses livekit.agents.Agent class
# which internally creates VoiceAssistant pipeline

# The pipeline is:
STT → VAD → LLM (streaming) → TTS (streaming) → Audio playback
```

The LiveKit SDK **already streams LLM tokens** but buffers them until the FULL response is done before sending to TTS.

---

## Implementation Steps

### Step 1: Enable Sentence Buffering in LLM Node

Modify `src/agent.py` to enable sentence-level flushing:

```python
# In the llm_node setup (around line 600)
# Add sentence detection + early flush

import re

SENTENCE_END = re.compile(r'[.!?।॥]\s+|[\n]{2,}')

def _should_flush_to_tts(accumulated_text: str) -> bool:
    """Check if accumulated text ends with a sentence boundary."""
    if not accumulated_text:
        return False
    
    # Check for sentence endings
    if SENTENCE_END.search(accumulated_text):
        return True
    
    # Check for natural Telugu/Hindi sentence breaks
    if len(accumulated_text) > 50:  # Min sentence length
        # Telugu sentence enders: అండి, గారు with space after
        if re.search(r'(అండి|గారు|जी)\s+$', accumulated_text):
            return True
    
    return False
```

### Step 2: Modify Agent to Stream Sentences

In `src/agent.py`, around the LLM response handling:

```python
# Current (simplified):
async for chunk in llm_stream:
    full_text += chunk.text
# Send full_text to TTS at end

# New (sentence streaming):
async for chunk in llm_stream:
    buffer += chunk.text
    
    if _should_flush_to_tts(buffer):
        # Send buffered sentence to TTS immediately
        await tts_queue.put(buffer)
        buffer = ""
```

### Step 3: Wire Cartesia WebSocket TTS

Already done! `src/pipeline/tts_cartesia.py` supports streaming.

---

## Simpler Alternative: Use LiveKit SDK's Sentence Chunking (RECOMMENDED)

LiveKit Agents SDK v0.8+ has **built-in sentence chunking** via `SentenceTokenizer`.

### Minimal Code Change:

```python
# In src/agent.py, when creating the Agent:

from livekit.agents import tokenize

agent = Agent(
    # ... existing params ...
    
    # Add sentence tokenizer
    llm_output_tokenizer=tokenize.SentenceTokenizer(),
    
    # This makes the agent send each sentence to TTS as soon as it's complete
    # instead of waiting for the full LLM response
)
```

**That's it!** LiveKit SDK handles the rest automatically.

---

## Testing Plan

1. **Baseline test** (current): Measure end-to-end latency on a test call
2. **Enable Cartesia**: Measure with Cartesia WebSocket TTS
3. **Enable sentence streaming**: Measure with `SentenceTokenizer`
4. **Compare**: Should see ~2-3s reduction in perceived latency

---

## Expected Results

| Configuration | Perceived Latency | Notes |
|---------------|-------------------|-------|
| Current (Sarvam, no streaming) | ~4.5s | Baseline |
| Cartesia WS (no sentence streaming) | ~3.8s | TTS latency cut |
| Cartesia WS + Sentence streaming | **~1.2s** | Target! |
| + Bedrock Mumbai LLM | **~0.8s** | Ultimate |

---

## Next Steps

1. ✅ Cartesia WebSocket TTS created (`src/pipeline/tts_cartesia.py`)
2. ⏳ Add `SentenceTokenizer` to Agent initialization
3. ⏳ Test on live call
4. ⏳ Measure latency improvement

Let me implement Step 2 now!
