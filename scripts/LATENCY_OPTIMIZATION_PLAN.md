# Complete Latency Optimization Plan
## Target: Sub-1s Perceived Response Time

---

## Current Baseline (from CallDetail metrics)

```
Endpointing:  736ms avg (942ms max)
LLM TTFT:     3257ms avg (11917ms max!) ← BIGGEST BOTTLENECK
TTS TTFB:     459ms avg (702ms max)
──────────────────────────────────────
TOTAL:        ~4.5s average, 13.6s worst
```

---

## Phase 1: LLM → AWS Bedrock Mumbai ⭐ BIGGEST WIN

### Current Problem:
- `gpt-4o-mini` hosted in US (Virginia)
- India ↔ US round-trip = high latency
- Non-deterministic throttling (11.9s spikes documented May 2026)

### Solution:
- **AWS Bedrock Nova Lite** in `ap-south-1` (Mumbai)
- India-hosted = cut network latency ~50-70%
- More consistent (no OpenAI throttle storms)

### Expected Results:
```
Current LLM:  3257ms avg → 11917ms spike
Target LLM:   800-1200ms avg → 2000ms max
SAVINGS:      ~2000-2500ms (2-2.5 seconds!)
```

### Implementation:
1. ✅ Bedrock API key added to `.env`
2. ✅ Probe completed (Nova works, TTFT ~1.8s in us-east-1)
3. ⏳ **TODO**: Switch region to ap-south-1 (Mumbai)
4. ⏳ **TODO**: Enable model access in Bedrock console (ap-south-1)
5. ⏳ **TODO**: Wire `bedrock/nova-lite` into `src/pipeline/llm.py`
6. ⏳ **TODO**: Update AgentConfig → `llm_model = bedrock/apac.amazon.nova-lite-v1:0`

### Files to modify:
- `src/pipeline/llm.py` — add Bedrock client with bearer token
- `scripts/fix_llm_model.py` — update to set bedrock model
- `.env` — AWS_REGION=ap-south-1

---

## Phase 2: TTS → Cartesia WebSocket ⭐ MEDIUM WIN

### Current:
- Sarvam Bulbul v2: 460ms TTFB (HTTP)

### Solution:
- **Cartesia Sonic 3.5** WebSocket streaming
- Real-time audio chunks (no wait for full generation)

### Tested Results:
```
Sarvam HTTP:        460ms TTFB
Cartesia WebSocket: 260ms TTFB
SAVINGS:            200ms (43% faster)
```

### Implementation:
1. ✅ Cartesia API key added
2. ✅ WebSocket probe successful (260ms measured)
3. ⏳ **TODO**: Build Cartesia TTS plugin in `src/pipeline/tts.py`
4. ⏳ **TODO**: Wire into agent (`cartesia/` prefix like `sarvam/`)
5. ⏳ **TODO**: Test on live call (quality check)

### Files to modify:
- `src/pipeline/tts.py` — add CartesiaTTS class (WebSocket-based)
- `src/config.py` — already has cartesia_api_key field ✅

---

## Phase 3: Sentence Streaming 🔥 GAME CHANGER

### Current Problem:
- Agent waits for FULL LLM response
- Then sends complete text to TTS
- User hears NOTHING during 3+ seconds

### Solution:
- Stream LLM response sentence-by-sentence
- Send FIRST sentence to TTS immediately
- Parallel generation: LLM generates sentence 2 while TTS plays sentence 1

### Example:
```python
# Current (sequential):
LLM: "Sure, I can help. First, let me check..." [3s wait]
TTS: [starts after 3s] [plays in 1s]
User hears audio: 4s total

# Sentence streaming (parallel):
LLM: "Sure, I can help." [0.8s]
TTS: [starts immediately] [plays in 0.3s]
LLM: "First, let me check..." [parallel, 0.7s]
User hears audio: 1.1s total (3x faster perceived!)
```

### Expected Savings:
- **Perceived latency cut: 400-800ms** (feels instant)

### Implementation:
1. ⏳ Modify `llm_node` in `src/agent.py`
2. ⏳ Yield partial LLM chunks (on sentence boundaries)
3. ⏳ Buffer TTS synthesis (don't wait for full text)
4. ⏳ Handle interruptions mid-stream

### Complexity:
- **Medium-High** — requires careful buffering logic
- LiveKit Agents SDK supports streaming, but needs testing

---

## Phase 4: Endpointing Optimization (Already 80% done)

### Current:
- Telugu: 0.15s, max 0.38s, min 0.08s
- Avg: 736ms

### Possible Further Tuning:
```python
# Aggressive (risk: cut off slow speakers)
VAD_START_SECS = 0.20  # current 0.25
VAD_STOP_SECS = 0.25   # current 0.30
# Target: 600ms avg
```

### Expected Savings:
- ~100-150ms

### Risk:
- Cut off words if user speaks slowly
- Already tuned tight — diminishing returns

---

## Phase 5: Parallel LLM Racing (Advanced, optional)

### Concept:
- Send SAME request to 2 LLM endpoints simultaneously
- Use whichever responds first (discard the slower)

### Example:
- Race: Bedrock Mumbai + Groq paid
- Take fastest response

### Expected Savings:
- Clips tail latency spikes
- ~200-400ms on bad moments

### Cost:
- **2x LLM cost** (both requests charged)

### Status:
- Code exists in `src/llm_race.py` (tested, works)
- Currently disabled (`LLM_RACE_COUNT=1`)
- Only worth it if Bedrock Mumbai still has >1.5s spikes

---

## EXPECTED FINAL RESULTS

| Component | Current | After Optimization | Savings |
|-----------|---------|-------------------|---------|
| **Endpointing** | 736ms | 600ms | 136ms |
| **LLM TTFT** | 3257ms | 900ms | 2357ms ⭐ |
| **TTS TTFB** | 459ms | 260ms | 199ms |
| **Sentence streaming** | N/A | -400ms (perceived) | 400ms |
| **TOTAL PERCEIVED** | **4.5s** | **~800-1000ms** | **3.5s cut!** |

### Worst-case handling:
- Current worst: 13.6s (unusable)
- After optimization: ~2.5s (acceptable)

---

## IMPLEMENTATION PRIORITY (Recommended Order)

### Week 1: **Bedrock Mumbai** (highest ROI)
- Switch LLM to ap-south-1
- Test TTFT (should be 800-1200ms)
- Deploy to production

### Week 2: **Cartesia WebSocket**
- Wire WebSocket TTS
- A/B test quality vs Sarvam
- Deploy if quality acceptable

### Week 3: **Sentence Streaming** (if still needed)
- Only if Phases 1+2 don't hit <1.5s target
- Higher complexity, test thoroughly

---

## Cost Impact

### Current (1 min call, 7 turns):
```
STT (Sarvam):  ₹1.32
LLM (OpenAI):  ₹0.35
TTS (Sarvam):  ₹3.36
Total:         ₹5.03
```

### After optimization:
```
STT (Sarvam):   ₹1.32  (no change)
LLM (Bedrock):  ₹0.25  (cheaper!)
TTS (Cartesia): ₹7.00  (2x more expensive)
Total:          ₹8.57  (+70% cost)
```

### ROI Analysis:
- Latency: 4.5s → 0.8s (5.6x faster)
- Cost: ₹5 → ₹8.50 (+70%)
- **Value**: Sub-1s = near-human feel = higher conversion rate
- If conversion improves >20%, cost justified

---

## Next Steps (YOUR CHOICE)

1. **Conservative** (low risk, medium win):
   - Phase 1 only (Bedrock Mumbai)
   - Keep Sarvam TTS
   - Expected: 4.5s → 2.0s
   - Cost: same or slightly cheaper

2. **Aggressive** (higher cost, maximum UX):
   - Phase 1 + 2 (Bedrock + Cartesia)
   - Expected: 4.5s → 1.2s
   - Cost: +70%

3. **Nuclear** (all optimizations):
   - Phase 1 + 2 + 3 (+ sentence streaming)
   - Expected: 4.5s → 0.8s (near-instant)
   - Cost: +70%, higher complexity

---

## Files Ready to Modify

When you decide, I'll implement:

1. `src/pipeline/llm.py` — Bedrock integration
2. `src/pipeline/tts.py` — Cartesia WebSocket
3. `src/agent.py` — Sentence streaming (if needed)
4. `scripts/fix_llm_model.py` — Deployment script
5. `.env` — Region + keys

**ఏది కావాలి చెప్పండి — I'll code it immediately!**
