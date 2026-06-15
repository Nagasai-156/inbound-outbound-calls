// Per-call cost estimate (INR).
//
// We don't persist exact token/character counts per call, so this is a
// DATA-DRIVEN ESTIMATE from call duration + turn count using each
// provider's published rate. Exact billing comes from each provider's
// own dashboard (OpenAI / Sarvam / LiveKit / Vobiz) — this gives the
// operator a realistic per-call number to reason about unit economics.
//
// Rates verified Jun 2026. Update here if a provider changes pricing.
export const COST_RATES = {
  sttPerMin: 0.5, // Sarvam Saaras: ₹30/hour
  ttsPer10kChars: 30, // Sarvam Bulbul v3 (v2 = 15)
  ttsCharsPerAgentTurn: 160, // avg spoken reply length (chars)
  livekitPerMin: 0.85, // LiveKit Cloud ~$0.01/agent-min
  telephonyPerMin: 0.6, // Vobiz India outbound (carrier-dependent)
  llmPerTurn: 0.05, // gpt-4o-mini, cached + shrunk prompt (tiny)
};

export type CostBreakdown = {
  total: number;
  stt: number;
  tts: number;
  llm: number;
  livekit: number;
  telephony: number;
  durationMin: number;
};

export function estimateCallCost(call: {
  startedAt?: string | Date | null;
  endedAt?: string | Date | null;
  turns?: number | null;
  llmCalls?: number | null;
  ttsModel?: string | null;
}): CostBreakdown {
  const start = call.startedAt ? new Date(call.startedAt).getTime() : 0;
  const end = call.endedAt ? new Date(call.endedAt).getTime() : Date.now();
  const durationMin = start ? Math.max(0, (end - start) / 60000) : 0;
  const turns = Math.max(0, call.turns ?? 0);
  const agentTurns = turns; // ~1 agent reply per caller turn
  const llmCalls = Math.max(0, call.llmCalls ?? turns);

  // v2 is half the price of v3-beta.
  const ttsRate =
    call.ttsModel === "bulbul:v2"
      ? COST_RATES.ttsPer10kChars / 2
      : COST_RATES.ttsPer10kChars;

  const stt = durationMin * COST_RATES.sttPerMin;
  const ttsChars = agentTurns * COST_RATES.ttsCharsPerAgentTurn;
  const tts = (ttsChars / 10000) * ttsRate;
  const llm = llmCalls * COST_RATES.llmPerTurn;
  const livekit = durationMin * COST_RATES.livekitPerMin;
  const telephony = durationMin * COST_RATES.telephonyPerMin;
  const total = stt + tts + llm + livekit + telephony;

  return { total, stt, tts, llm, livekit, telephony, durationMin };
}

export function inr(n: number): string {
  return "₹" + n.toFixed(2);
}
