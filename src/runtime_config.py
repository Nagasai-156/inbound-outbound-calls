"""RuntimeConfig — the dashboard-editable settings, loaded per call.

`config.Settings` holds infra/secrets from env (never changes at
runtime). `RuntimeConfig` holds the *operational* knobs the dashboard
edits (TTS voice, endpointing, persona, model, KB, ...). It is loaded at
the start of every call from the Supabase `AgentConfig` row, so dashboard
changes apply to the next call with no redeploy.

Resolution order (fast + resilient):
  1. Redis cache  (short TTL — avoids a DB round-trip on the hot path)
  2. Supabase Postgres `AgentConfig` row  (system of record)
  3. env defaults from `config.Settings`  (always works offline)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from src.config import settings

logger = logging.getLogger("runtime_config")

_REDIS_KEY = "agentconfig:default"
# Audit fix #3: dropped 30s → 5s. With 30s, operators saving a dashboard
# fix saw the new value take effect on the NEXT call (sometimes 4 calls
# later, depending on cache hit timing). 5s is short enough to feel
# immediate yet long enough to absorb burst lookups during call setup.
_REDIS_TTL = 5  # seconds; dashboard edits take effect within ~5s


@dataclass
class RuntimeConfig:
    # TTS voice & language
    tts_provider: str = "sarvam"  # "sarvam"
    tts_model: str = settings.tts_model
    default_language: str = "en"
    tts_speaker_te: str = "anushka"
    tts_speaker_hi: str = "anushka"
    tts_speaker_en: str = "anushka"
    tts_pace: float = 1.0
    # Per-language pace overrides. 0.0 = inherit `tts_pace` (global).
    # Telugu callers tolerate slower/measured speech; English snappier.
    tts_pace_te: float = 0.0
    tts_pace_hi: float = 0.0
    tts_pace_en: float = 0.0

    # Turn-taking & latency
    min_endpointing_delay: float = settings.min_endpointing_delay
    max_endpointing_delay: float = settings.max_endpointing_delay
    telugu_min_endpointing_delay: float = settings.telugu_min_endpointing_delay
    min_interruption_duration: float = settings.min_interruption_duration
    filler_latency_threshold: float = settings.filler_latency_threshold
    filler_min_stt_confidence: float = settings.filler_min_stt_confidence

    # Persona & content
    # Agent's spoken name in the opener/persona. Dashboard-driven so each
    # business names its own agent — NOT hardcoded in greeting logic.
    # "Zari" is only the neutral default.
    agent_name: str = "Zari"
    inbound_persona: str = ""
    outbound_persona: str = ""
    business_description: str = ""
    # Optional per-config few-shot example. "" -> the domain-NEUTRAL
    # built-in in persona/base.py (so no campaign's example leaks into
    # another). A campaign can also carry its own example inside its
    # script/persona text.
    style_examples: str = ""
    # Use-case switch: drives the conditional persona block AND which
    # tools are exposed. "custom" (default) = neutral prompt + no
    # booking tools (degrade-safe). Per-campaign override via metadata.
    use_case_type: str = "custom"
    # Per-config tool override (CSV of tool names). Empty = use the
    # built-in use-case → tools mapping (zero regression for existing
    # configs). Non-empty = expose ONLY these tools (plus base
    # kb_search/end_call). See `src/tools.py::_NAMED_TOOLS` for valid names.
    enabled_tools: str = ""
    # When true, the persona prepends a LANGUAGE-MIRROR rule so the agent
    # immediately follows full-sentence language switches by the caller.
    # When false, the agent stays in default_language throughout.
    auto_mirror_language: bool = True

    # Caller gender — auto-detected from F0 (pitch) on the first ~2s of
    # caller audio (see src/gender.py). "unknown" until detection lands;
    # llm_node injects a gender-aware honorifics directive once known so
    # the agent stops defaulting to "sir" for female callers.
    caller_gender: str = "unknown"

    # Round 4: Sarvam TTS server-side text preprocessing. When True,
    # Sarvam normalizes numbers ("17:30" -> spoken time), dates,
    # abbreviations, and English-script proper nouns embedded in Indic
    # sentences before synthesis. Costs ~0ms — done server-side in the
    # same TTS call — and meaningfully cleans up "Lakshmi" / "10/12/2025"
    # / "INR 25000" pronunciation. Dashboard-flippable per campaign.
    tts_enable_preprocessing: bool = True

    # Model & KB
    llm_provider: str = "openai"  # "openai" | "mistral" | "sarvam"
    llm_model: str = settings.llm_model
    llm_temperature: float = 0.4
    memory_max_turns: int = settings.memory_max_turns
    # Hard cap on the assembled per-turn prompt (persona + markers +
    # history). Prevents unbounded history growth from blowing past a
    # model/tier token limit (the Groq free-tier 413 dead-air bug).
    llm_prompt_max_tokens: int = settings.llm_prompt_max_tokens
    # Parallel LLM racing: N identical requests/turn, stream the fastest
    # first-token, cancel losers. Clips TTFT tail spikes. 1 = off.
    llm_race_count: int = settings.llm_race_count
    # Replay cached audio for fixed repeated phrases (fillers/canned/warm)
    # instead of re-synthesising — skips TTS first-byte latency. Default
    # off; validate on a live call before enabling.
    tts_audio_cache: bool = settings.tts_audio_cache
    kb_vector_store_id: str = settings.openai_kb_vector_store_id
    cache_min_similarity: float = settings.semantic_cache_min_similarity
    stt_model: str = settings.stt_model
    stt_mode: str = settings.stt_mode

    # Appointment grid — dashboard-editable so each business sets its
    # own hours (clinic 9-6, salon 10-8, gym 6-22). Defaults inherit
    # env so a fresh deploy with no AgentConfig row still works.
    appt_open_hour: int = settings.appt_open_hour
    appt_close_hour: int = settings.appt_close_hour
    appt_slot_min: int = settings.appt_slot_min
    appt_open_weekdays: str = settings.appt_open_weekdays

    @staticmethod
    def _normalize_lang(language: str) -> str:
        """Map 'te-IN' / 'te-mix' / 'tenglish' → 'te', same for hi/en.
        Without this, a caller passing the Sarvam locale form ('te-IN')
        silently fell back to the English speaker — latent bug surfaced
        by tests/test_runtime_config_extra. Defensive normalisation."""
        if not language:
            return "en"
        lc = language.lower()
        if lc.startswith("te") or lc == "tenglish":
            return "te"
        if lc.startswith("hi") or lc == "hinglish":
            return "hi"
        if lc.startswith("en"):
            return "en"
        return "en"

    def speaker_for(self, language: str) -> str:
        lang = self._normalize_lang(language)
        return {
            "te": self.tts_speaker_te,
            "hi": self.tts_speaker_hi,
            "en": self.tts_speaker_en,
        }.get(lang, self.tts_speaker_en)

    def pace_for(self, language: str) -> float:
        """Per-language pace if set (>0), else inherits global tts_pace."""
        lang = self._normalize_lang(language)
        per = {
            "te": self.tts_pace_te,
            "hi": self.tts_pace_hi,
            "en": self.tts_pace_en,
        }.get(lang, 0.0)
        return per if per > 0 else self.tts_pace


# Maps Prisma camelCase columns -> RuntimeConfig fields.
_COLMAP = {
    "ttsProvider": "tts_provider",
    "ttsModel": "tts_model",
    "defaultLanguage": "default_language",
    "ttsSpeakerTe": "tts_speaker_te",
    "ttsSpeakerHi": "tts_speaker_hi",
    "ttsSpeakerEn": "tts_speaker_en",
    "ttsPace": "tts_pace",
    "ttsPaceTe": "tts_pace_te",
    "ttsPaceHi": "tts_pace_hi",
    "ttsPaceEn": "tts_pace_en",
    "ttsEnablePreprocessing": "tts_enable_preprocessing",
    "minEndpointingDelay": "min_endpointing_delay",
    "maxEndpointingDelay": "max_endpointing_delay",
    "teluguMinEndpointingDelay": "telugu_min_endpointing_delay",
    "minInterruptionDuration": "min_interruption_duration",
    "fillerLatencyThreshold": "filler_latency_threshold",
    "fillerMinSttConfidence": "filler_min_stt_confidence",
    "agentName": "agent_name",
    "inboundPersona": "inbound_persona",
    "outboundPersona": "outbound_persona",
    "businessDescription": "business_description",
    # Mapped only if the column exists (the _from_supabase loop guards
    # `if col in row`), so this is safe even before the DB migration —
    # missing column just leaves the neutral built-in in effect.
    "styleExamples": "style_examples",
    "useCaseType": "use_case_type",
    "enabledTools": "enabled_tools",
    "autoMirrorLanguage": "auto_mirror_language",
    "llmProvider": "llm_provider",
    "llmModel": "llm_model",
    "llmTemperature": "llm_temperature",
    "memoryMaxTurns": "memory_max_turns",
    "llmPromptMaxTokens": "llm_prompt_max_tokens",
    "ttsAudioCache": "tts_audio_cache",
    "kbVectorStoreId": "kb_vector_store_id",
    "cacheMinSimilarity": "cache_min_similarity",
    "sttModel": "stt_model",
    "sttMode": "stt_mode",
    "apptOpenHour": "appt_open_hour",
    "apptCloseHour": "appt_close_hour",
    "apptSlotMin": "appt_slot_min",
    "apptOpenWeekdays": "appt_open_weekdays",
}


# Tight Redis timeouts so a dead Redis fails the get/set fast and we
# fall through to Supabase / env defaults instead of stalling call setup.
_REDIS_KW = dict(
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


async def _from_redis() -> RuntimeConfig | None:
    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, **_REDIS_KW)
        blob = await r.get(_REDIS_KEY)
        await r.aclose()
        if blob:
            return RuntimeConfig(**json.loads(blob))
    except Exception:
        logger.debug("runtime config: redis miss", exc_info=True)
    return None


async def _cache_to_redis(cfg: RuntimeConfig) -> None:
    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, **_REDIS_KW)
        await r.set(_REDIS_KEY, json.dumps(asdict(cfg)), ex=_REDIS_TTL)
        await r.aclose()
    except Exception:
        logger.debug("runtime config: redis cache failed", exc_info=True)


async def _from_supabase() -> RuntimeConfig | None:
    if not settings.supabase_db_url:
        return None
    try:
        import asyncpg

        from src.pg import asyncpg_args

        dsn, extra = asyncpg_args(settings.supabase_db_url)
        conn = await asyncpg.connect(dsn, timeout=5, **extra)
        try:
            row = await conn.fetchrow(
                'SELECT * FROM voiceai."AgentConfig" WHERE id = $1',
                "default",
            )
        finally:
            await conn.close()
        if not row:
            return None
        cfg = RuntimeConfig()
        for col, field in _COLMAP.items():
            if col in row and row[col] is not None:
                # Per-field guard: one malformed column must NOT discard the
                # ENTIRE dashboard config (the old single try/except around
                # the whole loop returned None on any cast error → every
                # setting silently reverted to env defaults mid-call).
                try:
                    setattr(cfg, field, type(getattr(cfg, field))(row[col]))
                except Exception:
                    logger.warning(
                        "runtime config: bad column %s=%r — keeping default",
                        col, row[col],
                    )
        return cfg
    except Exception:
        logger.info("runtime config: supabase unavailable, using defaults",
                     exc_info=True)
        return None


async def load_runtime_config() -> RuntimeConfig:
    """Load the active config (Redis -> Supabase -> env defaults)."""
    cached = await _from_redis()
    if cached is not None:
        return cached
    cfg = await _from_supabase()
    if cfg is None:
        cfg = RuntimeConfig()  # env-default fallback (always works)
    await _cache_to_redis(cfg)
    return cfg


async def invalidate_runtime_config() -> None:
    """Drop the Redis cache so the NEXT call (inbound or outbound) loads
    the freshly-saved config from Supabase immediately. Called by the
    dashboard right after a Voice & Agent save."""
    try:
        import redis.asyncio as redis

        r = redis.from_url(settings.redis_url, **_REDIS_KW)
        await r.delete(_REDIS_KEY)
        await r.aclose()
        logger.info("runtime config cache invalidated")
    except Exception as e:
        # WARNING (not DEBUG): when this fails silently the dashboard
        # operator thinks their save took effect, but the agent still
        # serves a 30s-stale config. Make the failure visible so it can
        # be diagnosed instead of mysteriously waiting for TTL expiry.
        logger.warning(
            "runtime config invalidate failed: %s — dashboard edits "
            "will take up to %ds to take effect via TTL expiry",
            e, _REDIS_TTL,
        )
