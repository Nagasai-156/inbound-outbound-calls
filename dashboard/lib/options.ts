// Valid, curated option lists for every enumerable setting. The settings
// form uses these for dropdowns so the client can never enter an invalid
// model/voice/mode.

export type Opt = { value: string; label: string };

// Only the models the Sarvam plugin actually accepts.
export const TTS_MODELS: Opt[] = [
  { value: "bulbul:v2", label: "Bulbul v2 (stable)" },
  { value: "bulbul:v3-beta", label: "Bulbul v3 (beta, best quality)" },
];

// Cartesia uses voice IDs, not model names like Sarvam
// These are the TESTED voices that work with Telugu/Hindi/English
// Only 3 voices are currently tested and verified
// Source: scripts/probe_cartesia.py, src/pipeline/tts_cartesia.py
export const CARTESIA_VOICES: Opt[] = [
  { value: "79a125e8-cd45-4c13-8a67-188112f4dd22", label: "British Lady — female, professional" },
  { value: "a0e99841-438c-4a64-b679-ae501e7d6091", label: "Barbershop Man — male, casual" },
  { value: "248be419-c632-4f23-adf1-5324ed7dbf1d", label: "Classy British Man — male, authoritative" },
];

// Speakers are NOT shared across models. Each model only accepts its
// own set (Sarvam rejects mismatches with HTTP 400).
export const SPEAKERS_BY_MODEL: Record<string, Opt[]> = {
  "bulbul:v2": [
    { value: "anushka", label: "Anushka — female, warm" },
    { value: "manisha", label: "Manisha — female, clear" },
    { value: "vidya", label: "Vidya — female, calm" },
    { value: "arya", label: "Arya — female, bright" },
    { value: "abhilash", label: "Abhilash — male, neutral" },
    { value: "karun", label: "Karun — male, deep" },
    { value: "hitesh", label: "Hitesh — male, energetic" },
  ],
  "bulbul:v3-beta": [
    { value: "ritu", label: "Ritu — female, support" },
    { value: "pooja", label: "Pooja — female, support" },
    { value: "simran", label: "Simran — female, support" },
    { value: "kavya", label: "Kavya — female, support" },
    { value: "shreya", label: "Shreya — female, support" },
    { value: "ishita", label: "Ishita — female, support" },
    { value: "priya", label: "Priya — female, support" },
    { value: "shubh", label: "Shubh — male, support" },
    { value: "rahul", label: "Rahul — male, support" },
    { value: "amit", label: "Amit — male, support" },
    { value: "ratan", label: "Ratan — male, support" },
    { value: "rohan", label: "Rohan — male, support" },
    { value: "dev", label: "Dev — male, support" },
    { value: "manan", label: "Manan — male, support" },
    { value: "sumit", label: "Sumit — male, support" },
    { value: "neha", label: "Neha — female, creator" },
    { value: "roopa", label: "Roopa — female, creator" },
    { value: "aditya", label: "Aditya — male, creator" },
    { value: "kabir", label: "Kabir — male, creator" },
    { value: "varun", label: "Varun — male, creator" },
    { value: "advait", label: "Advait — male, creator" },
    { value: "ashutosh", label: "Ashutosh — male, creator" },
    { value: "aayan", label: "Aayan — male, creator" },
  ],
};

export function speakersFor(model: string): Opt[] {
  return SPEAKERS_BY_MODEL[model] || SPEAKERS_BY_MODEL["bulbul:v2"];
}

// Back-compat alias (defaults to v2 list) for any remaining import.
export const SPEAKERS = SPEAKERS_BY_MODEL["bulbul:v2"];

// Short sample line per language for voice preview.
export const PREVIEW_TEXT: Record<string, string> = {
  en: "Hello sir, how can I help you today?",
  hi: "Namaste sir, main aapki kaise madad karun?",
  te: "Namaskaram sir, nenu meeku ela help cheyyanu?",
};

// The agent ALWAYS code-mixes English into the chosen Indic base
// (built into the persona) — so "Telugu" really means Telugu+English
// (Tenglish). Labels say so explicitly to avoid the "where is the
// combination option?" confusion. value stays en/hi/te (drives STT/TTS).
export const LANGUAGES: Opt[] = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi + English (Hinglish)" },
  { value: "te", label: "Telugu + English (Tenglish)" },
];

// Catalog of agent tools the dashboard can enable per-config.
// Names MUST match `_NAMED_TOOLS` keys in src/tools.py. kb_search +
// end_call are base tools — always available, not listed here.
export const AGENT_TOOLS: Array<{ value: string; label: string; hint: string }> = [
  { value: "check_appointment_slots", label: "Check appointment slots",
    hint: "Read free/booked slots for a date. Required before book_appointment." },
  { value: "book_appointment", label: "Book appointment",
    hint: "Insert a row in the Appointment table. Needs check_appointment_slots." },
  { value: "my_appointment", label: "Lookup caller's appointments",
    hint: "List the caller's upcoming bookings by phone. Needed for reschedule/cancel." },
  { value: "reschedule_appointment", label: "Reschedule appointment",
    hint: "Move an existing booking to a new day/time." },
  { value: "cancel_appointment", label: "Cancel one appointment",
    hint: "Cancel ONE booking by id." },
  { value: "cancel_all_appointments", label: "Cancel all appointments",
    hint: "Cancel ALL of this caller's upcoming bookings." },
  { value: "order_status", label: "Order status lookup",
    hint: "Look up an order by id (defers to human if no backend wired)." },
];

// Use-case drives the agent's scoped behaviour block AND which tools it
// gets (booking tools ONLY for appointment-family). Must match
// USE_CASE_BLOCKS / _USE_CASE_TOOLS keys in the Python backend.
export const USE_CASES: Opt[] = [
  { value: "custom", label: "Custom / general (no booking tools)" },
  { value: "appointment", label: "Appointment booking" },
  { value: "reschedule", label: "Reschedule / cancel a booking" },
  { value: "reminder", label: "Reminder (confirm/reschedule)" },
  { value: "sales", label: "Sales / outreach" },
  { value: "leadgen", label: "Lead generation" },
  { value: "survey", label: "Survey" },
  { value: "feedback", label: "Feedback / CSAT" },
  { value: "support", label: "Customer support" },
  { value: "collections", label: "Collections / payment follow-up" },
];

export const STT_MODELS: Opt[] = [
  { value: "saaras:v3", label: "Saaras v3 (best, code-mix)" },
  { value: "saaras:v2.5", label: "Saaras v2.5" },
  { value: "saarika:v2.5", label: "Saarika v2.5" },
];

export const STT_MODES: Opt[] = [
  { value: "codemix", label: "Code-mix (Telugu/Hindi/English mixed)" },
  { value: "transcribe", label: "Transcribe (single language)" },
  { value: "translate", label: "Translate to English" },
  { value: "verbatim", label: "Verbatim" },
  { value: "translit", label: "Transliterate" },
];

// ─── TTS Provider Options ─────────────────────────────────────────
export const TTS_PROVIDERS: Opt[] = [
  { value: "sarvam", label: "Sarvam Bulbul (Proven Telugu quality, 460ms)" },
];

// Helper function to get TTS models/voices based on provider
export function ttsModelsFor(provider: string): Opt[] {
  return TTS_MODELS; // Sarvam Bulbul models
}

// ─── LLM Provider Options ─────────────────────────────────────────
export const LLM_PROVIDERS: Opt[] = [
  { value: "mistral", label: "⭐ Mistral API (PAID tier — fastest ~340ms, no 429)" },
  { value: "bedrock", label: "⭐ AWS Bedrock (Mumbai — India-hosted, sub-700ms, no 429)" },
  { value: "gemini", label: "Google Gemini (best Telugu script, ~750ms — free tier)" },
  { value: "xai", label: "xAI Grok (non-reasoning, ~1.2s)" },
  { value: "openai", label: "OpenAI (US region, ~1.2s)" },
];

// ─── LLM Models by Provider ───────────────────────────────────────
export const LLM_MODELS: Opt[] = [
  // AWS Bedrock — India-hosted (Mumbai, prefix: bedrock/). Backend calls
  // the ap-south-1 OpenAI-compatible endpoint. India RTT → ~500-700ms TTFT
  // (vs ~1.2s US OpenAI) with NO free-tier 429s. Verified Tenglish + booking
  // tool-calling. Ministral 14B = best Tenglish + clean tool args.
  { value: "bedrock/mistral.ministral-3-14b-instruct", label: "⭐ Mistral Ministral 14B — Bedrock Mumbai (best Tenglish + books, ~626ms)" },
  { value: "bedrock/mistral.ministral-3-8b-instruct", label: "Mistral Ministral 8B — Bedrock Mumbai (faster ~504ms, lighter)" },
  { value: "bedrock/qwen.qwen3-32b-v1:0", label: "Qwen3 32B — Bedrock Mumbai (fastest ~477ms, raw tool args)" },
  // OpenAI tier — higher quality, ~1s TTFT (US compute floor). Pick these
  // when booking-reasoning quality matters more than raw speed.
  { value: "gpt-4o-mini", label: "GPT-4o mini (fast, cheap, great Tenglish)" },
  { value: "gpt-4.1-mini", label: "GPT-4.1 mini" },
  { value: "gpt-4.1-nano", label: "GPT-4.1 nano (fastest OpenAI, variable)" },
  { value: "gpt-4o", label: "GPT-4o (highest quality, higher latency)" },
  { value: "gpt-4.1", label: "GPT-4.1 (highest quality, higher latency)" },
  // Mistral La Plateforme (prefix: mistral/). Backend strips the prefix
  // and calls api.mistral.ai via the OpenAI-compatible surface. NOW ON
  // PAID TIER — the free-tier 429 spikes that caused 2-4s lag are gone.
  // Quality/latency notes from live Tenglish long-turn testing.
  { value: "mistral/mistral-small-latest", label: "⭐ Mistral Small (RECOMMENDED — fastest ~340ms, long turns ✓, books)" },
  { value: "mistral/mistral-medium-latest", label: "Mistral Medium (richer answers, slower ~1s)" },
  { value: "mistral/mistral-large-latest", label: "🏆 Mistral Large (best quality, slower ~1.2s)" },
  { value: "mistral/ministral-8b-latest", label: "Ministral 8B (fast, lighter — weaker Telugu on long turns)" },
  { value: "mistral/ministral-3b-latest", label: "Ministral 3B (fastest, lightest — weaker on long turns)" },
  { value: "mistral/mistral-tiny-latest", label: "Mistral Tiny (fast, but tends to reply in English)" },

  // Google Gemini (prefix: gemini/). Backend calls the
  // generativelanguage.googleapis.com OpenAI-compatible endpoint.
  // Verified live 2026-06-15; dead/429 variants intentionally omitted.
  // NOTE: Gemini key is on the FREE tier — enable billing for production
  // reliability (free tier 429s on heavy models).
  { value: "gemini/gemini-2.5-flash-lite", label: "⭐ Gemini 2.5 Flash-Lite (BEST Telugu script, ~750ms)" },
  { value: "gemini/gemini-flash-lite-latest", label: "Gemini Flash-Lite Latest (alias of best, ~750ms)" },
  { value: "gemini/gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite (newest, slower ~950ms)" },

  // xAI Grok (prefix: xai/). Backend calls api.x.ai. ONLY the
  // non-reasoning variant is voice-fit — reasoning Grok adds 6s+ of
  // think time. Verified live 2026-06-15.
  { value: "xai/grok-4.20-0309-non-reasoning", label: "⭐ Grok 4.20 non-reasoning (voice pick, ~1.2s)" },
  { value: "xai/grok-3-mini", label: "Grok 3 Mini (lighter, ~2.8s)" },
];

// Return ONLY the LLM models that belong to the given provider. The
// backend routes purely off the model NAME (the `llmProvider` field is
// not persisted), so the dashboard must keep model+provider consistent:
// changing the provider auto-picks llmModelsFor(provider)[0], and the
// model dropdown only lists that provider's models.
export function llmModelsFor(provider: string): Opt[] {
  return LLM_MODELS.filter((m) => {
    const v = m.value.toLowerCase();
    if (provider === "bedrock") return v.startsWith("bedrock/");
    if (provider === "mistral") return v.startsWith("mistral/");
    if (provider === "gemini") return v.startsWith("gemini/");
    if (provider === "xai") return v.startsWith("xai/");
    if (provider === "openai") {
      return v.startsWith("gpt-");
    }
    return true;
  });
}

// Slider-style numeric fields: [key, label, min, max, step, help]
export const NUMERIC_FIELDS: Record<
  string,
  [string, number, number, number, string]
> = {
  ttsPace: ["Speaking pace", 0.5, 2, 0.05, "1.0 = normal speed"],
  ttsPaceTe: ["TTS pace (Telugu)", 0, 2, 0.05, "0 = inherit global pace"],
  ttsPaceHi: ["TTS pace (Hindi)", 0, 2, 0.05, "0 = inherit global pace"],
  ttsPaceEn: ["TTS pace (English)", 0, 2, 0.05, "0 = inherit global pace"],
  minEndpointingDelay: ["Min endpointing delay (s)", 0.1, 2, 0.05, "How fast we treat a pause as end-of-turn"],
  maxEndpointingDelay: ["Max endpointing delay (s)", 1, 6, 0.1, "Hard cap before responding"],
  teluguMinEndpointingDelay: ["Telugu min endpointing (s)", 0.2, 2.5, 0.05, "Telugu pauses are longer"],
  minInterruptionDuration: ["Min interruption duration (s)", 0.05, 1, 0.05, "Speech length to count as barge-in"],
  fillerLatencyThreshold: ["Filler latency threshold (s)", 0.1, 1.5, 0.05, "Emit filler if slower than this"],
  fillerMinSttConfidence: ["Filler min STT confidence", 0, 1, 0.05, "Filler if STT confidence below this"],
  llmTemperature: ["LLM temperature", 0, 1.2, 0.05, "Lower = more consistent"],
  memoryMaxTurns: ["Memory turns", 2, 20, 1, "Conversation turns kept in context"],
  llmPromptMaxTokens: ["Prompt token cap", 2000, 16000, 500, "Hard cap on the per-turn LLM prompt. Bounds history growth so latency stays flat and the request never exceeds the model/tier token limit (prevents Groq free-tier 12k 413 failures). 8000 is safe under a 12k cap."],
  cacheMinSimilarity: ["Cache match threshold", 0.7, 0.99, 0.01, "Higher = stricter cache hits"],
  apptOpenHour: ["Open hour", 0, 23, 1, "When the business opens (24h). e.g. 9 = 9 AM, 6 = 6 AM."],
  apptCloseHour: ["Close hour", 1, 24, 1, "When the business closes (24h, exclusive). e.g. 18 = 6 PM, 22 = 10 PM."],
  apptSlotMin: ["Slot duration (min)", 5, 120, 5, "Each booking slot length in minutes (e.g. 30 = half-hourly, 60 = hourly)."],
};
