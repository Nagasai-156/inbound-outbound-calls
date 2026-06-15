# Diigoo AI Voice Calls — Complete Project Documentation

Realtime, multilingual (Telugu / Hindi / English + code-mix) AI voice calling
system. Behaves like a fast human call-center executive: sub-second perceived
latency, full streaming, barge-in, emotional pacing, mid-sentence language
switching. Inbound + outbound phone calls and a browser test client, with an
admin dashboard for live monitoring and voice/agent configuration.

---

## 1. What is actually being used (current stack)

| Concern | Technology | Where configured |
|---|---|---|
| Voice agent framework | **LiveKit Agents (Python)** | `src/agent.py` |
| Telephony | **Vobiz SIP trunk → LiveKit Cloud** (inbound + outbound, pre-provisioned trunk IDs) | `.env` `LIVEKIT_SIP_TRUNK_ID`, `LIVEKIT_OUTBOUND_TRUNK_ID` |
| Speech-to-Text | **Sarvam** streaming, `saaras:v3`, `codemix` mode | `src/pipeline/stt.py` |
| Text-to-Speech | **Sarvam** streaming, `bulbul:v2`, per-language speaker | `src/pipeline/tts.py` |
| LLM | **OpenAI `gpt-4o-mini`** (streaming) — provider switch present (`LLM_PROVIDER`) | `src/pipeline/llm.py` |
| Knowledge base | **OpenAI vector store + `file_search`** (Qdrant/fastembed env wired but not the active KB) | `src/kb.py` |
| VAD / turn-taking | **Silero VAD** + LiveKit **MultilingualModel** + custom Telugu continuation heuristic | `src/pipeline/turn.py` |
| Hot path / live data | **Redis** (semantic cache, dynamic content pools, live telemetry pub/sub, config cache) | `src/cache.py`, `src/telemetry.py` |
| System of record | **Supabase Postgres** (calls, transcripts, agent config) | `src/db.py`, `dashboard/prisma` |
| ORM + migrations | **Prisma** (owned by the dashboard) | `dashboard/prisma/schema.prisma` |
| Dashboard | **Next.js 14** (App Router) + **Supabase Auth** + **Supabase Realtime** | `dashboard/` |
| Control API | **FastAPI** (LiveKit token / outbound dial / content regen only) | `src/web/server.py` |

**Two apps, one database:**

```
Vobiz SIP ─► LiveKit Cloud ─► Room ─► Python Voice Agent (LiveKit Agents)
                                        │  Redis (cache, content, live pub/sub)
                                        │  Supabase Postgres (durable record)
                                        ▼
                              Next.js Dashboard (Auth + Realtime)
                              proxies LiveKit/telephony ► FastAPI Control API
```

---

## 2. End-to-end call flow (what happens on every call)

```
Caller speaks
  └─► LiveKit room audio
      └─► Silero VAD (voice detected, PSTN-tuned: VAD_START/STOP/MIN_VOLUME)
          └─► Sarvam STT streaming (codemix → partial transcripts, no wait for final)
              └─► Transcript Stabilizer (debounce + confidence; kills flicker)
                  └─► Hybrid Turn Detection
                      • MultilingualModel (Hindi/English contextual end-of-turn)
                      • Telugu/Tenglish continuation guard (don't cut off pauses)
                  └─► [on stable partial] Predictive Prefetch starts KB/cache early
              └─► Turn finished →
                  Fast Intent Router (first match wins):
                    1. Canned/rule   → instant (~100ms, NO LLM)
                    2. Semantic cache → Redis hit (NO LLM)
                    3. Action tool    → deterministic (order status stub)
                    4. LLM            → OpenAI gpt-4o-mini stream (+ kb_search tool)
                  └─► Conditional Filler (only if LLM/slow/low-confidence)
                       spoken via dynamic, non-repeating pool
                  └─► Response-Rhythm Engine (emotion-biased micro-pauses)
                  └─► Sarvam TTS streaming (per-language voice) → caller hears it
  Caller interrupts (barge-in)
      └─► FSM → INTERRUPTED → cancel speculative work + flush TTS (<~200ms)

Every turn: structured memory updated, telemetry → Redis (live) + Supabase (durable)
```

Latency strategy: nothing waits for "final" anything. STT partials, LLM token
stream, TTS chunk stream all run in parallel. The router avoids the LLM for most
turns; the filler covers real LLM latency; predictive prefetch warms answers
before the caller even finishes.

---

## 3. Backend — every module and what it does

### Orchestration
- **`src/agent.py`** — the entrypoint/worker. Builds the LiveKit `AgentSession`
  (STT, LLM, TTS, VAD, turn detection), wires the FSM, router, fillers, rhythm,
  memory, telemetry, cancellation, predictive prefetch, echo/duplex, resilience,
  and per-call config. Inbound vs outbound persona chosen from job metadata.
- **`src/config.py`** — all env/secret loading (one place). Reads your env
  variable names directly (`DATABASE_URL`, `LIVEKIT_*`, `VOBIZ_*`, `SUPABASE_*`,
  `VAD_*`, `DEFAULT_LLM_MODEL`, …) via alias fallbacks.
- **`src/runtime_config.py`** — the dashboard-editable settings, loaded **per
  call**: Redis cache → Supabase `AgentConfig` → env defaults. Lets the
  dashboard change voice/agent behaviour with no redeploy.
- **`src/fsm.py`** — conversation state machine (`GREETING, LISTENING, THINKING,
  SPEAKING, INTERRUPTED, KB_FETCH, ACTION_EXECUTION, CALL_END`) with guarded
  transitions to prevent overlapping-TTS / partial-during-speak race conditions.

### Speech pipeline (`src/pipeline/`)
- **`stt.py`** — Sarvam STT factory (`saaras:v3`, `codemix`) — mixed-language
  transcription, streaming partials.
- **`tts.py`** — Sarvam TTS factory (`bulbul:v2`), per-language speaker + pace;
  `retune_tts` switches voice mid-call when caller changes language.
- **`llm.py`** — OpenAI LLM factory (`gpt-4o-mini`, streaming, temperature).
- **`turn.py`** — Silero VAD loader (PSTN tuned), MultilingualModel turn
  detector, the Telugu continuation heuristic (`looks_incomplete`), and
  per-language endpointing delays.
- **`stabilizer.py`** — transcript stabilizer: a token must persist across N
  partials + clear a confidence floor + survive debounce before it's released
  downstream. Kills partial-driven hallucination.

### Fast Intent Router (`src/router/`)
- **`classifier.py`** — zero-network language + intent detector (Telugu/Hindi/
  English/mixed), marks trivial turns. The "don't overuse GPT" guardrail.
- **`canned.py`** — instant rule responses for greetings/yes/no/thanks/bye/
  repeat, language-matched, anti-repeat rotation.
- **`intent_router.py`** — orchestrates canned → semantic cache → action → LLM.
  Returns whether the turn was resolved without the LLM.

### Realism
- **`filler.py`** — conditional filler (only when LLM/slow/low-confidence — NOT
  every turn) drawn from a dynamic, non-repeating pool.
- **`rhythm.py`** — human response-rhythm engine: small randomized pre-speech /
  inter-sentence pauses, emotion-biased (angry→snappy, confused→slower).
- **`persona/base.py`, `inbound.py`, `outbound.py`** — strict persona prompts
  (≤12 words/sentence, ≤2 sentences, mirror language/emotion, never read docs).
  Inbound = support; outbound = sales. Dashboard can override + inject business
  context.

### Knowledge, cache, memory, cost
- **`kb.py`** — `kb_answer`: OpenAI Responses `file_search` over the vector
  store; returns a short conversational answer (never document text), writes
  the answer back to the semantic cache.
- **`cache.py`** — Redis semantic cache: embeds the question, cosine-matches
  cached FAQ answers; threshold from RuntimeConfig.
- **`content.py`** — dynamic content store: filler/canned pools loaded from
  Redis (generated offline by the LLM), falls back to built-in defaults.
- **`memory.py`** — structured per-call memory `{language, emotion, intent,
  name, slots}` + rolling summary; Redis-backed with local fallback.
- **`cost.py`** — per-call route metering (LLM bypass rate) + history token
  trimming.

### Speed / robustness
- **`predictive.py`** — speculative KB/cache prefetch on stabilized partials;
  serves a warm answer if the final transcript confirms the intent.
- **`cancellation.py`** — on barge-in: cancel speculative tasks + flush TTS
  (idempotent), so no orphaned LLM cost or stale audio.
- **`audio.py`** — AEC/noise-cancellation at the LiveKit edge, `EchoGuard`
  (drops the agent's own TTS echo, half-duplex fallback), `AdaptiveBuffer`
  (widens jitter buffer on poor links).

### Telephony (`src/telephony/`)
- **`sip_setup.py`** — verifies your existing LiveKit trunks + creates the
  inbound dispatch rule pointing at the agent.
- **`outbound.py`** — `place_call(number)`: dispatches the agent into a room
  (tagged `outbound`) and dials via the Vobiz outbound trunk.
- **`resilience.py`** — STT stream restart, TTS fallback voice, link-degradation
  handling, SIP-drop → `CALL_END`.

### Persistence & telemetry
- **`db.py`** — asyncpg pool to Supabase; upserts `Call`, inserts `Transcript`,
  ends calls. Degrades to no-op if DB down.
- **`pg.py`** — sanitizes the Supabase/PgBouncer DSN for asyncpg
  (`pgbouncer=true&sslmode=require` → `ssl=True, statement_cache_size=0`).
- **`telemetry.py`** — per call: Redis (live SSE pub/sub for the dashboard) +
  Supabase (durable calls/transcripts/metrics).

### Control API (`src/web/server.py`)
Thin FastAPI used only for things needing the Python LiveKit/Sarvam SDKs:
- `POST /api/token` — LiveKit join token + agent dispatch (browser test client)
- `POST /api/outbound` — place an outbound call
- `POST /api/content/generate` — regenerate dynamic content pools (LLM→Redis)
- `GET /healthz`

### Scripts (`scripts/`)
- **`ingest_kb.py`** — upload KB docs to an OpenAI vector store.
- **`warm_cache.py`** — pre-seed the Redis semantic cache with top FAQs.
- **`gen_content.py`** — LLM generates business/persona-specific filler & canned
  pools offline → Redis (dynamic content, zero runtime LLM latency).

---

## 4. Feature list (everything implemented)

**Conversation quality**
- Streaming STT→LLM→TTS, parallel, never blocking
- Multilingual: Telugu, Hindi, English + Hinglish/Tenglish, mid-sentence switch
- Hybrid turn detection incl. Telugu pause/continuation guard
- Barge-in with token-level cancellation + TTS flush (<~200ms)
- Conditional + dynamic non-repeating fillers
- Human response-rhythm (emotion-biased pacing)
- Separate inbound (support) vs outbound (sales) personas, strict constraints
- Transcript stabilizer (no partial-flicker hallucination)
- Predictive answer prefetch on partials

**Cost / latency**
- Fast Intent Router: most turns never hit the LLM
- Redis semantic cache with TTL + write-back
- Offline LLM-generated dynamic content pools
- Structured memory + history token trimming
- Per-call cost metering (LLM bypass rate)

**Telephony**
- Inbound (Vobiz DID → LiveKit dispatch → agent)
- Outbound dialer (`place_call`)
- Uses pre-provisioned LiveKit trunks
- Resilience: STT restart, TTS fallback, echo/duplex handling, call-drop

**Platform**
- Per-call RuntimeConfig from Supabase (dashboard-editable, no redeploy)
- Durable calls + transcripts in Supabase
- Live telemetry via Redis pub/sub → dashboard SSE/Realtime
- Dashboard: auth, live calls, transcripts, voice/agent settings editor,
  browser test client, outbound dialer, content regeneration

---

## 5. Data model (Supabase, Prisma `dashboard/prisma/schema.prisma`)

- **`AgentConfig`** (single `default` row) — all dashboard-editable knobs: TTS
  model/speakers/pace, default language, endpointing/interruption/filler
  thresholds, persona overrides, business description, LLM model/temperature,
  memory turns, KB vector store id, cache similarity, STT model/mode.
- **`Call`** — id (= LiveKit room), direction, status, language, emotion,
  intent, callerName, turns, llmCalls, kbCalls, bypassRate, started/endedAt.
- **`Transcript`** — callId, role (user/agent), text, ts.

Realtime on `Call` + `Transcript` powers the live dashboard (no polling).

---

## 6. Dashboard (`dashboard/`, Next.js 14)

- **Auth** — Supabase email/password; middleware gates every route.
- **Calls** (`/`) — live + recent calls, language/emotion/intent/turns/LLM-bypass;
  Supabase Realtime updates.
- **Call detail** (`/calls/[id]`) — full transcript + context, live.
- **Voice & Agent settings** (`/settings`) — full editor for the entire
  `AgentConfig`; saved via Prisma; agent applies it on the next call (~30s).
- **Test client** (`/test`) — talk to the agent in the browser (no phone);
  outbound dialer; dynamic-content regeneration trigger.
- API routes proxy LiveKit/telephony actions to the Python Control API.

---

## 7. Configuration system

Two layers:
1. **`.env` (infra/secrets, static)** — DB, Redis, LiveKit, Sarvam, OpenAI,
   Vobiz, Supabase, VAD tuning. Read by `src/config.py`. Your variable names
   are supported directly.
2. **`AgentConfig` (operational, live-editable)** — edited in the dashboard,
   stored in Supabase, loaded per call by `src/runtime_config.py` (Redis-cached
   ~30s). Changes apply without restarting the agent.

---

## 8. How to run

```bash
pip install -r requirements.txt
docker compose up -d redis

cd dashboard
npm install
npx prisma migrate deploy        # create tables in Supabase
npm run db:seed                  # default AgentConfig row
npm run seed:admin               # admin@diigoo.ai dashboard login
cd ..

python -m src.agent start                       # voice agent worker
uvicorn src.web.server:app --port 8000          # control API (new terminal)
cd dashboard && npm run dev                     # dashboard (new terminal)
```

Dashboard: `http://localhost:3000` → `admin@diigoo.ai` / `Admin@123456`.
Manual one-time step: in Supabase, enable **Realtime** on the `Call` and
`Transcript` tables (Database → Replication).

Tests: `pytest` (31 passing — router, turn, stabilizer, content,
runtime-config, pipeline).

---

## 9. Status & pending

**Done & verified (offline):** all backend modules, 31/31 tests pass, full
compile, env wired to your variable names, asyncpg/PgBouncer DSN fix, VAD
tuning, existing-trunk usage, dashboard code complete.

**Pending (needs live infra, not code):**
- `prisma migrate deploy` + enable Supabase Realtime on the two tables
- First live LiveKit/Sarvam run to confirm exact plugin call signatures
- `npm install` in `dashboard/`
- KB documents to ingest (`scripts/ingest_kb.py`)
- Real order/payment backend (currently a stub in `src/tools.py`)
- Live-call tuning (endpointing, Telugu heuristic, cache threshold)
- **Rotate the secrets shared in chat**

**Decisions taken (using provided env):**
- KB = OpenAI `file_search` (Qdrant/fastembed env wired but not the active KB)
- LLM = OpenAI `gpt-4o-mini` (`LLM_PROVIDER` switch present; Groq/Bedrock keys
  wired, multi-provider implementation not built)
