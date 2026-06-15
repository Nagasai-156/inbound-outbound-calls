# Realtime Multilingual AI Voice Calling System

Production-grade realtime voice agent that **answers and places phone calls** and converses
naturally in **Telugu, Hindi, English** and their code-mixed forms (Hinglish / Tenglish).

Not a chatbot — it behaves like a fast human call-center executive: sub-second *perceived*
latency, full streaming, barge-in, emotional pacing, multilingual switching mid-sentence.

## Stack

| Layer | Technology |
|---|---|
| Framework | LiveKit Agents (Python) |
| Telephony | Vobiz SIP trunk → LiveKit Cloud (inbound + outbound) |
| STT | Sarvam streaming (`saaras:v3`, `codemix` mode) |
| LLM | OpenAI `gpt-4o-mini` (streaming) |
| Knowledge base | OpenAI vector store + `file_search` |
| TTS | Sarvam streaming (`bulbul:v2`, per-language voice) |
| VAD / turn | Silero VAD + LiveKit MultilingualModel + hybrid Telugu heuristic |
| Hot path | Redis (semantic cache + live telemetry pub/sub) |
| System of record | Supabase Postgres (calls, transcripts, voice/agent config) |
| ORM / migrations | Prisma (owned by the dashboard) |
| Dashboard | Next.js 14 (App Router) + Supabase Auth + Supabase Realtime |

## Architecture

Two apps, one database.

```
┌─ Python voice agent (LiveKit/Sarvam/OpenAI) ──────────────────────────┐
│ Vobiz SIP → LiveKit Cloud → Room → Agent Worker (Conversation FSM)    │
│  caller audio → Silero VAD → Sarvam STT (codemix, partials)           │
│   → Transcript Stabilizer → Hybrid Turn Detection (Telugu heuristic)  │
│   → Fast Intent Router: canned → semantic cache → action → LLM(+KB)   │
│   → Conditional Filler + Response-Rhythm → Sarvam TTS → playback      │
│   ↘ Barge-in → FSM INTERRUPTED → cancel speculative work + flush TTS  │
│  reads RuntimeConfig  ·  writes calls+transcripts  ·  Redis hot path  │
└──────────────┬─────────────────────────────┬─────────────────────────┘
               │                             │
        Redis (cache,            Supabase Postgres (Prisma schema)
        live pub/sub)            AgentConfig · Call · Transcript
               │                             │
┌──────────────┴─────────────────────────────┴─────────────────────────┐
│ Next.js dashboard — Supabase Auth + Realtime                          │
│  Calls (live)  ·  Call detail+transcript  ·  Voice/Agent settings     │
│  Browser test client  ·  Outbound dialer  ·  Content regen            │
│  proxies LiveKit/telephony actions → Python Control API               │
└───────────────────────────────────────────────────────────────────────┘
```

Voice/agent config is edited in the dashboard (persisted via Prisma to Supabase) and the
agent reloads it at the **start of every call** (Redis-cached ~30s) — no redeploy.

See the full plan: `C:\Users\malli\.claude\plans\hai-need-to-develop-lovely-tiger.md`.

## Setup

```bash
# 1. Python 3.11+ virtual env
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -r requirements.txt

# 2. Configure credentials
copy .env.example .env            # then fill in keys

# 3. Local Redis (dev)
docker compose up -d redis

# 4. Ingest knowledge base into OpenAI vector store
python scripts/ingest_kb.py ./kb_docs
# copy the printed vector store id into OPENAI_KB_VECTOR_STORE_ID in .env

# 5. (optional) Pre-warm the semantic cache with top FAQs
python scripts/warm_cache.py

# 6. (optional) Generate DYNAMIC content pools via the LLM (offline) ->
#    Redis. Fillers/canned replies are then dynamic per business/persona
#    but still served instantly (no runtime LLM). Falls back to built-in
#    defaults if you skip this.
python scripts/gen_content.py --business "Your business" --n 12

# 7. Set up Supabase + Prisma (dashboard owns the schema/migrations)
cd dashboard
npm install
copy .env.example .env            # fill Supabase DATABASE_URL/DIRECT_URL/keys
npx prisma migrate deploy         # create AgentConfig/Call/Transcript tables
npm run db:seed                   # seed the default AgentConfig row
#   In Supabase: enable Realtime on the "Call" and "Transcript" tables.
#   Put the same Postgres URL in the root .env as SUPABASE_DB_URL.

# 8. Run the agent worker
python -m src.agent console       # talk locally, no phone
python -m src.agent start         # production worker

# 9. Python control API (LiveKit token / outbound / content regen)
uvicorn src.web.server:app --port 8000

# 10. Dashboard (Next.js)
cd dashboard && npm run dev       # http://localhost:3000

# 11. Provision Vobiz SIP trunks + dispatch rule
python -m src.telephony.sip_setup
```

## Dashboard (Next.js + Supabase + Prisma)

`dashboard/` — auth-gated admin console (Supabase email/password):

- **Calls** — live + recent calls, language / emotion / intent / turns /
  LLM-bypass; updates via **Supabase Realtime** (no polling needed).
- **Call detail** — full transcript + context, live.
- **Voice & Agent settings** — edit TTS voice/language/pace, turn-taking
  & latency, persona overrides, business description, model & KB; saved
  via Prisma to Supabase, applied by the agent on the next call.
- **Test client** — talk to the agent from the browser (no phone).
- **Outbound dialer** + **dynamic-content regeneration** (proxied to the
  Python control API).

The Python agent persists calls/transcripts to the same Supabase DB and
reads the dashboard-edited config per call.

## Testing

```bash
pytest                            # 31 tests: router / turn / stabilizer /
                                  # content / runtime-config / pipeline
python -m src.agent console       # talk to the agent locally, no telephony
cd dashboard && npm run build     # typecheck + build the dashboard
```

## Build phases

Implemented incrementally; each phase independently testable.

- **v1–v3** (13 phases): scaffold → core pipeline → FSM/turn → stabilizer → router →
  personas → fillers/rhythm → KB/cache/cost → memory → cancellation/predictive →
  audio/echo → telephony/resilience → hardening.
- **v4**: dynamic LLM-generated content pools (offline → Redis), call telemetry.
- **v5**: Supabase Postgres + Prisma system-of-record, dashboard-editable RuntimeConfig
  applied per call, Next.js dashboard (Supabase Auth + Realtime), Python control API.

## Production deploy (Supabase + LiveKit + Vobiz)

1. Provision a Supabase project; copy the connection string into `.env`
   as `SUPABASE_DB_URL` AND `DATABASE_URL` AND `DIRECT_URL`.
2. `cd dashboard && npm install`
3. `npx prisma db push` — creates the `voiceai` schema:
   `AgentConfig` / `Call` / `Transcript` / `Appointment` / `KbDocument` /
   `Campaign*` / `VoiceConfig`.
4. `npm run db:seed` — seeds the default `AgentConfig` row (id=`default`).
5. (optional) `npm run seed:admin` — creates the `admin@diigoo.ai` login.
6. `python scripts/ingest_kb.py docs/` → sets `OPENAI_KB_VECTOR_STORE_ID`
   in `.env`.
7. In the Supabase console, enable **Realtime** on `voiceai.Call` and
   `voiceai.Transcript` (Database → Replication). Without this the
   dashboard falls back to 5s polling.
8. Start the three production processes (see table below).

### Three-process supervision (no Docker required)

| Process     | Command                                                    | Supervisor                                  |
|-------------|------------------------------------------------------------|---------------------------------------------|
| Worker      | `python scripts/watchdog.py`                               | Windows Task (`setup_watchdog_task.ps1`)    |
| Control API | `uvicorn src.web.server:app --host 0.0.0.0 --port 8000`    | NSSM service `DiigooCtrlApi`                |
| Dashboard   | `cd dashboard && npm run start -- -p 3000`                 | NSSM service `DiigooDashboard`              |

Redis: `docker compose up -d redis` (already in `docker-compose.yml`).
Supabase Postgres: managed (no local container).

#### NSSM install (one-time, admin PowerShell)

```powershell
# Control API
nssm install DiigooCtrlApi "C:\Python313\python.exe" -m uvicorn src.web.server:app --host 0.0.0.0 --port 8000
nssm set     DiigooCtrlApi AppDirectory "D:\diigoo\ai calls"
nssm set     DiigooCtrlApi AppStdout    "D:\diigoo\ai calls\ctrlapi.log"
nssm set     DiigooCtrlApi AppStderr    "D:\diigoo\ai calls\ctrlapi.err.log"
nssm start   DiigooCtrlApi

# Dashboard (build first: `cd dashboard && npm run build`)
nssm install DiigooDashboard "C:\Program Files\nodejs\npm.cmd" run start -- -p 3000
nssm set     DiigooDashboard AppDirectory "D:\diigoo\ai calls\dashboard"
nssm set     DiigooDashboard AppStdout    "D:\diigoo\ai calls\dashboard\dashboard.log"
nssm set     DiigooDashboard AppStderr    "D:\diigoo\ai calls\dashboard\dashboard.err.log"
nssm start   DiigooDashboard
```

Linux production: replace NSSM with systemd unit files (one per process).

### Verifying a fresh deploy

- Dashboard `/settings` loads + edits `AgentConfig` (round-trip to Supabase).
- Kill the Control API process → NSSM restarts it within ~5 s.
- Kill the worker child → `scripts/watchdog.py` respawns it (~15 s
  to LiveKit re-registration).
- Place an outbound test call from `/test`; transcript appears live.
