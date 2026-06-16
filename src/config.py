"""Centralized configuration loaded from environment / .env.

Every other module imports `settings` from here so credentials and tuning
knobs live in exactly one place. Tuning defaults encode the latency targets
from the architecture plan (sub-second perceived response).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── LiveKit Cloud ───────────────────────────────────────────
    livekit_url: str = Field(default="", alias="LIVEKIT_URL")
    livekit_api_key: str = Field(default="", alias="LIVEKIT_API_KEY")
    livekit_api_secret: str = Field(default="", alias="LIVEKIT_API_SECRET")
    # Pre-created trunks (no need to run sip_setup if these are set).
    livekit_sip_trunk_id: str = Field(
        default="", alias="LIVEKIT_SIP_TRUNK_ID"
    )
    livekit_sip_domain: str = Field(default="", alias="LIVEKIT_SIP_DOMAIN")

    # ─── Sarvam STT / TTS ────────────────────────────────────────
    sarvam_api_key: str = Field(default="", alias="SARVAM_API_KEY")
    sarvam_tts_url: str = Field(
        default="https://api.sarvam.ai/text-to-speech",
        alias="SARVAM_TTS_URL",
    )
    sarvam_stt_url: str = Field(
        default="https://api.sarvam.ai/speech-to-text",
        alias="SARVAM_STT_URL",
    )
    stt_model: str = Field(default="saaras:v3", alias="STT_MODEL")
    stt_mode: str = Field(default="codemix", alias="STT_MODE")
    # Sarvam's SERVER-side VAD decides when the caller stopped (END_SPEECH),
    # and only then flushes the FINAL transcript. The conservative default
    # waited up to ~2s on some turns (live call out-5f46afed54: eou/
    # transcription_delay=2.03s) — that was the felt "dead gap", not the
    # LLM. high_vad_sensitivity makes Sarvam declare end-of-speech sooner →
    # earlier flush → faster final. Env-revertible: set STT_HIGH_VAD_SENSITIVITY
    # =false + restart if it ever clips trailing Telugu words. The LiveKit
    # per-language endpointing floor (Telugu 0.25s) still backstops listening.
    stt_high_vad_sensitivity: bool = Field(
        default=True, alias="STT_HIGH_VAD_SENSITIVITY"
    )
    tts_model: str = Field(default="bulbul:v2", alias="TTS_MODEL")

    # ─── LLM + KB ────────────────────────────────────────────────
    # Default provider (fallback for all languages)
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    # Mistral La Plateforme — selected via `mistral/<model>`, e.g.
    # `mistral/mistral-small-latest`.
    mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")
    # Google Gemini (best Telugu script in testing) via the OpenAI-
    # compatible endpoint. Free tier rate-limits — enable billing or use
    # Vertex Mumbai for production.
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    # xAI Grok — OpenAI-compatible. grok-4.20-non-reasoning tested
    # consistent ~600ms from EC2 + good Telugu. US-hosted.
    xai_api_key: str = Field(default="", alias="XAI_API_KEY")
    # Groq — OpenAI-compatible, runs Llama on LPU chips. Selected via
    # `groq/<model>` prefix (e.g. groq/llama-3.3-70b-versatile). Probe
    # 2026-06: TTFT p50 ~291ms from India + 6/6 reschedule tool-calls in
    # Telugu — faster than Bedrock Mumbai despite US hosting. US-hosted
    # (no India residency) + free/dev-tier rate limits at scale.
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    # ─── AWS Bedrock (Claude / Nova — India Mumbai region option) ─
    # Bearer token from Bedrock console → API keys. Selected via
    # `bedrock/<model>` prefix (e.g. bedrock/claude-3-5-haiku). Probe
    # with scripts/probe_bedrock.py. For India latency, use ap-south-1
    # region + apac.* inference profiles.
    aws_bearer_token_bedrock: str = Field(
        default="", alias="AWS_BEARER_TOKEN_BEDROCK"
    )
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")
    # Accept the project's DEFAULT_LLM_MODEL as well as LLM_MODEL.
    # Standardized on OpenAI gpt-4o-mini: fast, cheap, strong Tenglish/
    # Hinglish. The multi-provider switch in pipeline/llm.py stays in
    # place (a model-name prefix still routes to Mistral/Cerebras/Sarvam
    # if ever explicitly selected) but OpenAI is the default.
    llm_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("DEFAULT_LLM_MODEL", "LLM_MODEL"),
    )
    openai_kb_vector_store_id: str = Field(
        default="", alias="OPENAI_KB_VECTOR_STORE_ID"
    )
    embedding_model: str = Field(
        default="text-embedding-3-small", alias="EMBEDDING_MODEL"
    )

    # ─── Qdrant (optional vector KB) ─────────────────────────────
    qdrant_url: str = Field(default="", alias="QDRANT_URL")
    qdrant_api_key: str = Field(default="", alias="QDRANT_API_KEY")
    fastembed_cache_path: str = Field(
        default="", alias="FASTEMBED_CACHE_PATH"
    )

    # ─── Supabase (Postgres system of record + auth/storage) ─────
    # Python connects with asyncpg using whichever of DATABASE_URL /
    # SUPABASE_DB_URL is set.
    supabase_db_url: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "SUPABASE_DB_URL"),
    )
    supabase_url: str = Field(default="", alias="SUPABASE_URL")
    supabase_service_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY"
        ),
    )
    supabase_anon_key: str = Field(default="", alias="SUPABASE_ANON_KEY")
    supabase_storage_bucket: str = Field(
        default="knowledge-base", alias="SUPABASE_STORAGE_BUCKET"
    )

    # ─── Redis (semantic cache + per-call state) ─────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    semantic_cache_ttl_seconds: int = Field(default=86_400, alias="CACHE_TTL")
    semantic_cache_min_similarity: float = Field(
        default=0.92, alias="CACHE_MIN_SIMILARITY"
    )
    # KB retrieval floor (below = "not covered"); kept low for cross-
    # lingual recall, the grounded prompt is the real gate.
    kb_min_score: float = Field(default=0.20, alias="KB_MIN_SCORE")
    # Only cache a KB answer when retrieval was CONFIDENT — stops a
    # weakly-grounded answer being propagated to many callers.
    kb_cache_min_score: float = Field(
        default=0.45, alias="KB_CACHE_MIN_SCORE"
    )

    # ─── Vobiz SIP trunk ─────────────────────────────────────────
    vobiz_auth_id: str = Field(default="", alias="VOBIZ_AUTH_ID")
    vobiz_auth_token: str = Field(default="", alias="VOBIZ_AUTH_TOKEN")
    vobiz_sip_password: str = Field(default="", alias="VOBIZ_SIP_PASSWORD")
    vobiz_api_url: str = Field(
        default="https://api.vobiz.ai", alias="VOBIZ_API_URL"
    )
    vobiz_sip_domain: str = Field(default="", alias="VOBIZ_SIP_DOMAIN")
    vobiz_inbound_did: str = Field(default="", alias="VOBIZ_INBOUND_DID")
    # Outbound trunk id: project uses LIVEKIT_OUTBOUND_TRUNK_ID.
    outbound_trunk_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "LIVEKIT_OUTBOUND_TRUNK_ID", "OUTBOUND_TRUNK_ID"
        ),
    )

    # ─── Agent ───────────────────────────────────────────────────
    agent_name: str = Field(default="ai-voice-agent", alias="AGENT_NAME")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    worker_port: int = Field(default=8082, alias="LIVEKIT_WORKER_PORT")
    # ─── Control API auth ────────────────────────────────────────
    # Shared secret the Next.js dashboard sends as the `X-API-Key`
    # header on every server-to-server proxy call. The control API
    # (src/web/server.py) places OUTBOUND CALLS, runs bulk campaigns and
    # mints LiveKit tokens — unauthenticated, anyone who can reach
    # port 8000 could spam-dial and burn money. When this is set the API
    # enforces it; when empty the API logs a loud warning but still
    # serves (backward-compat so existing local deploys don't break).
    # SET THIS IN PRODUCTION — same value in the root .env (Python) and
    # dashboard/.env (CONTROL_API_KEY, read by the Next proxy).
    control_api_key: str = Field(default="", alias="CONTROL_API_KEY")
    # How many times livekit-agents may retry the Cloud websocket before
    # it gives up. The library default (16) is the documented root cause
    # of dead-air: a DNS/network blip exhausts 16 retries, the worker
    # then sits as a ZOMBIE (process alive, NOT registered) and every
    # call lands on silence until a manual/watchdog restart. Effectively
    # unbounded so the worker self-heals the instant connectivity returns
    # instead of surrendering; the watchdog's active health probe is the
    # backstop for a worker that's stuck not-registered.
    worker_max_retry: int = Field(
        default=100_000, alias="LIVEKIT_WORKER_MAX_RETRY"
    )
    # Number of warm subprocess workers kept ready to accept LiveKit jobs.
    # Dev mode default is 0 -> every call spawns from scratch -> bursts
    # queue/drop and only the first call's transcript lands in DB.
    # Increased from 8 to 16 for sub-500ms target - handles 16 truly-concurrent
    # campaign calls with zero cold-start cost. Scale up for bigger campaigns
    # (each warm process holds models in memory; ~250-400 MB each).
    worker_num_idle_processes: int = Field(
        default=16, alias="LIVEKIT_WORKER_NUM_IDLE_PROCESSES"
    )

    # ─── VAD tuning (PSTN echo suppression) ──────────────────────
    vad_start_secs: float = Field(default=0.25, alias="VAD_START_SECS")
    vad_stop_secs: float = Field(default=0.30, alias="VAD_STOP_SECS")
    vad_min_volume: float = Field(default=0.65, alias="VAD_MIN_VOLUME")

    # ─── Latency / turn-taking tuning (seconds) ──────────────────
    # MultilingualModel covers Hi/En; Telugu/Tenglish falls back to these.
    # Reduced from 0.3 to 0.15 for sub-500ms target (OmniDimension-style)
    min_endpointing_delay: float = Field(default=0.15, alias="MIN_ENDPOINTING_DELAY")
    # CEILING the EOT model waits when it's unsure the caller is done.
    # Reduced from 1.0 to 0.5 for sub-500ms target. Still tolerates
    # mid-thought pauses while capping worst-case dead air at ~500ms.
    max_endpointing_delay: float = Field(default=0.5, alias="MAX_ENDPOINTING_DELAY")
    # Telugu pauses are a bit longer than English — reduced from 0.45 to 0.25
    # for faster response while still accommodating natural pauses.
    telugu_min_endpointing_delay: float = Field(
        default=0.25, alias="TELUGU_MIN_ENDPOINTING_DELAY"
    )
    min_interruption_duration: float = Field(
        default=0.2, alias="MIN_INTERRUPTION_DURATION"
    )

    # ─── Filler trigger thresholds ───────────────────────────────
    # Emit a filler only if the real answer is expected to take longer than
    # this, or STT confidence is below the floor, or route is LLM/KB.
    filler_latency_threshold: float = Field(
        default=0.3, alias="FILLER_LATENCY_THRESHOLD"
    )
    filler_min_stt_confidence: float = Field(
        default=0.55, alias="FILLER_MIN_STT_CONFIDENCE"
    )

    # ─── Transcript stabilizer ───────────────────────────────────
    # Reduced from 2 to 1 for faster response (accept first stable partial)
    stabilizer_min_stable_partials: int = Field(
        default=1, alias="STABILIZER_MIN_STABLE_PARTIALS"
    )
    # Reduced from 0.12 to 0.05 for sub-500ms target (50ms vs 120ms)
    stabilizer_debounce_seconds: float = Field(
        default=0.05, alias="STABILIZER_DEBOUNCE_SECONDS"
    )
    stabilizer_min_token_confidence: float = Field(
        default=0.5, alias="STABILIZER_MIN_TOKEN_CONFIDENCE"
    )

    # ─── Memory ──────────────────────────────────────────────────
    memory_max_turns: int = Field(default=6, alias="MEMORY_MAX_TURNS")

    # ─── Prompt token budget (hard cap on the per-turn LLM prompt) ──
    # Bounds the assembled prompt (persona + per-turn markers + chat
    # history) so it can NEVER grow past a model/tier limit. Real calls
    # showed the prompt climbing 7.6k→12.9k tokens across one call as raw
    # history accumulated, blowing past Groq's free-tier 12k cap → 413 →
    # dead air. 8000 keeps the full persona + markers + several recent
    # turns while leaving ~4k headroom under a 12k cap for the completion
    # and for burst TPM. Lower it for stricter tiers, raise it on a
    # higher-limit plan. System messages are never trimmed.
    llm_prompt_max_tokens: int = Field(
        default=8000, alias="LLM_PROMPT_MAX_TOKENS"
    )

    # Per-reply output cap. Telugu script costs ~1-2 tokens/char — 160
    # hard-stopped replies mid-answer on live calls. Read via settings
    # (NOT os.environ — .env loads into pydantic only, so an os.environ
    # read silently ignored the .env value: live bug 2026-06-12 where
    # out=160 persisted after .env said 320).
    llm_max_output_tokens: int = Field(
        default=320, alias="LLM_MAX_OUTPUT_TOKENS"
    )

    # ─── Parallel LLM racing (kill TTFT tail-latency spikes) ─────
    # Fire N identical LLM requests per turn and stream whichever returns
    # its first token soonest, cancelling the losers. Does NOT lower the
    # median — it clips the long tail (measured spikes to 3-4s on the same
    # prompt) so turns feel CONSISTENT. Cost ~Nx tokens on racing turns
    # (cheap on gpt-4o-mini). 1 = OFF (single request, default). 2 = race
    # two. Fully fallback-safe: any racing error degrades to one stream.
    llm_race_count: int = Field(default=1, alias="LLM_RACE_COUNT")

    # ─── TTS audio cache (multimodal cache) ──────────────────────
    # Replay cached audio for fixed repeated phrases (fillers, canned
    # greeting/thanks/bye/repeat, warm answers) instead of re-synthesising
    # them — saves the full TTS first-byte latency (~270-460ms) on those
    # turns. In-process, per-voice keyed. Default OFF: it changes the
    # audio path, so validate on one live call (confirm fillers/canned
    # sound identical and barge-in still cuts them) before enabling in
    # production via this flag or the dashboard.
    tts_audio_cache: bool = Field(default=False, alias="TTS_AUDIO_CACHE")

    # ─── Real-time backchanneling (active-listening acks) ────────
    # Humans murmur "హా… అవును… mhm…" WHILE the other person is still
    # talking — it's the single strongest "this is a real person" signal
    # on a call. When ON, the agent emits ONE short, cached ack mid-way
    # through a LONG caller utterance (never on short turns, never twice
    # in the same utterance, cooldown-gated so it's occasional not
    # spammy). Audio is replayed from the TTS cache (~instant) and fed to
    # the echo guard so it's never mis-heard as caller speech.
    # Default OFF: it speaks while the caller holds the floor, so on a
    # half-duplex PSTN line it must be validated on one live call before
    # production (confirm it doesn't talk over the caller / cause echo).
    backchannel_enabled: bool = Field(default=False, alias="BACKCHANNEL_ENABLED")
    # Min words in the caller's running utterance before an ack is worth
    # it (short replies need no "mhm").
    backchannel_min_words: int = Field(default=8, alias="BACKCHANNEL_MIN_WORDS")
    # Min seconds the caller must have been talking in this utterance.
    backchannel_min_seconds: float = Field(
        default=2.0, alias="BACKCHANNEL_MIN_SECONDS"
    )
    # Min seconds between two acks (across utterances) — keeps it occasional.
    backchannel_cooldown_seconds: float = Field(
        default=6.0, alias="BACKCHANNEL_COOLDOWN_SECONDS"
    )

    # ─── Telegram admin alerts (booking events) ─────────────────
    # Empty (default) = notifications disabled, every send() is a silent
    # no-op so the worker can run without Telegram setup. Set both via
    # .env to flip on:
    #   1. Create bot via @BotFather → paste token below
    #   2. Get your numeric chat id via @userinfobot → paste below
    #   3. Send the bot a /start so it can DM you
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_admin_chat_id: str = Field(
        default="", alias="TELEGRAM_ADMIN_CHAT_ID"
    )

    # ─── Appointment booking hours (configurable, no code edit) ──
    # The structured grid the agent can actually BOOK. Change via env
    # to match the real business. NOTE: the dashboard mirrors these in
    # dashboard/app/api/appointments/route.ts — keep them in sync.
    appt_open_hour: int = Field(default=9, alias="APPT_OPEN_HOUR")
    # Business timezone for ALL appointment date/slot logic. Servers
    # commonly run UTC; without pinning this, "today"/"tomorrow" and the
    # same-day past-slot filter used the server clock — near the day
    # boundary that resolved the wrong calendar day and hid/showed wrong
    # slots (e.g. 3 PM IST = 09:30 UTC). Default Asia/Kolkata (IST, no
    # DST). India deploys need no tzdata — the clock falls back to a
    # fixed +5:30 offset if zoneinfo is unavailable.
    appt_timezone: str = Field(default="Asia/Kolkata", alias="APPT_TIMEZONE")
    appt_close_hour: int = Field(default=18, alias="APPT_CLOSE_HOUR")
    appt_slot_min: int = Field(default=30, alias="APPT_SLOT_MIN")
    # Comma list of open weekdays, Mon=0..Sun=6 (default Mon-Sat).
    appt_open_weekdays: str = Field(
        default="0,1,2,3,4,5", alias="APPT_OPEN_WEEKDAYS"
    )

    # ─── Phase 1+2 Optimizations ─────────────────────────────────
    # Enable sentence streaming (Telugu-aware)
    enable_sentence_streaming: bool = Field(
        default=True, alias="ENABLE_SENTENCE_STREAMING"
    )
    
    # Enable LLM response caching for common intents
    enable_llm_response_cache: bool = Field(
        default=True, alias="ENABLE_LLM_RESPONSE_CACHE"
    )
    llm_response_cache_ttl: int = Field(
        default=3600, alias="LLM_RESPONSE_CACHE_TTL"  # 1 hour
    )
    
    # Enable TTS pre-rendering for ultra-common phrases
    enable_tts_prerendering: bool = Field(
        default=True, alias="ENABLE_TTS_PRERENDERING"
    )
    
    # Gemini API key (for testing/comparison)
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    @property
    def livekit_configured(self) -> bool:
        return bool(
            self.livekit_url and self.livekit_api_key and self.livekit_api_secret
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton so .env is parsed once per process."""
    return Settings()


settings = get_settings()
