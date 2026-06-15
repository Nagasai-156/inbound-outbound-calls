import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";
import { LLM_MODELS, LLM_PROVIDERS } from "@/lib/options";

// Same allowlist as /api/config: only models the dashboard offers.
const VALID_LLM_MODELS = new Set<string>(LLM_MODELS.map((m) => m.value));
const VALID_LLM_PROVIDERS = new Set<string>(LLM_PROVIDERS.map((p) => p.value));

export const dynamic = "force-dynamic";

const FIELDS = [
  "name","ttsProvider","ttsModel","defaultLanguage","ttsSpeakerTe","ttsSpeakerHi","ttsSpeakerEn",
  "ttsPace","ttsPaceTe","ttsPaceHi","ttsPaceEn",
  "autoMirrorLanguage","minEndpointingDelay","maxEndpointingDelay",
  "teluguMinEndpointingDelay","minInterruptionDuration","fillerLatencyThreshold",
  "fillerMinSttConfidence","inboundPersona","outboundPersona","businessDescription",
  "styleExamples","useCaseType","enabledTools","llmProvider","llmModel","llmTemperature",
  "sttModel","sttMode","memoryMaxTurns","llmPromptMaxTokens","cacheMinSimilarity",
  "ttsAudioCache","kbVectorStoreId","apptOpenHour","apptCloseHour","apptSlotMin",
  "apptOpenWeekdays",
];

// Same coercion as profiles/route.ts POST — Prisma needs native types;
// form values arrive as strings and were being saved as strings.
const FLOATS = new Set([
  "ttsPace","ttsPaceTe","ttsPaceHi","ttsPaceEn",
  "minEndpointingDelay","maxEndpointingDelay","teluguMinEndpointingDelay",
  "minInterruptionDuration","fillerLatencyThreshold","fillerMinSttConfidence",
  "llmTemperature","cacheMinSimilarity",
]);
const INTS = new Set([
  "memoryMaxTurns","llmPromptMaxTokens",
  "apptOpenHour","apptCloseHour","apptSlotMin",
]);
const BOOLS = new Set(["autoMirrorLanguage","ttsAudioCache"]);

function coerce(k: string, v: unknown): unknown {
  if (BOOLS.has(k)) return v === true || v === "true" || v === 1 || v === "1";
  if (FLOATS.has(k)) { const n = parseFloat(v as string); return Number.isNaN(n) ? undefined : n; }
  if (INTS.has(k)) { const n = parseInt(v as string, 10); return Number.isNaN(n) ? undefined : n; }
  return v;
}

async function auth() {
  const { data: { user } } = await createClient().auth.getUser();
  return user;
}

export async function GET(_: Request, { params }: { params: { id: string } }) {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const p = prisma as any;
  const profile = await p.voiceConfig.findUnique({ where: { id: params.id } });
  if (!profile) return NextResponse.json({ error: "not found" }, { status: 404 });
  return NextResponse.json({ profile });
}

export async function PATCH(req: Request, { params }: { params: { id: string } }) {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const body = await req.json();
  const data: any = {};
  for (const k of FIELDS) {
    if (body[k] === undefined) continue;
    const v = coerce(k, body[k]);
    if (v !== undefined) data[k] = v;
  }
  if (data.name) data.name = data.name.trim();
  if (data.llmModel !== undefined && !VALID_LLM_MODELS.has(String(data.llmModel)))
    return NextResponse.json(
      { error: `invalid llmModel "${data.llmModel}" — pick one from the dashboard list` },
      { status: 400 },
    );
  if (data.llmProvider !== undefined && !VALID_LLM_PROVIDERS.has(String(data.llmProvider)))
    return NextResponse.json(
      { error: `invalid llmProvider "${data.llmProvider}"` },
      { status: 400 },
    );
  const p = prisma as any;
  try {
    const profile = await p.voiceConfig.update({ where: { id: params.id }, data });
    return NextResponse.json({ profile });
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
}

export async function DELETE(_: Request, { params }: { params: { id: string } }) {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const p = prisma as any;
  try {
    await p.voiceConfig.delete({ where: { id: params.id } });
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}

// Config fields shared by a saved profile (VoiceConfig) and the live
// AgentConfig. Applying a profile copies EXACTLY these into AgentConfig
// so the next call uses precisely the saved setup — fully dashboard-driven.
const APPLY_FIELDS = [
  "ttsProvider","ttsModel","defaultLanguage","ttsSpeakerTe","ttsSpeakerHi","ttsSpeakerEn",
  "ttsPace","ttsPaceTe","ttsPaceHi","ttsPaceEn","autoMirrorLanguage",
  "minEndpointingDelay","maxEndpointingDelay","teluguMinEndpointingDelay",
  "minInterruptionDuration","fillerLatencyThreshold","fillerMinSttConfidence",
  "inboundPersona","outboundPersona","businessDescription","styleExamples",
  "useCaseType","enabledTools","llmProvider","llmModel","llmTemperature",
  "sttModel","sttMode","memoryMaxTurns","llmPromptMaxTokens","cacheMinSimilarity",
  "ttsAudioCache","kbVectorStoreId","apptOpenHour","apptCloseHour","apptSlotMin",
  "apptOpenWeekdays",
];

// POST = "Apply this profile to the live config". Copies the profile's
// settings into AgentConfig (id="default") and busts the agent's runtime
// cache so the NEXT call uses exactly these settings — same path as a
// normal Settings save, so calls always reflect the applied profile.
export async function POST(_: Request, { params }: { params: { id: string } }) {
  const user = await auth();
  if (!user) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const p = prisma as any;
  const profile = await p.voiceConfig.findUnique({ where: { id: params.id } });
  if (!profile) return NextResponse.json({ error: "not found" }, { status: 404 });

  const data: any = { updatedBy: user.email ?? "" };
  const warnings: string[] = [];
  for (const k of APPLY_FIELDS) {
    if (profile[k] !== undefined && profile[k] !== null) data[k] = profile[k];
  }
  // A profile saved before a model was retired can carry a dead model —
  // skip it (keep the live config's model) instead of breaking calls.
  if (data.llmModel !== undefined && !VALID_LLM_MODELS.has(String(data.llmModel))) {
    warnings.push(`skipped stale llmModel "${data.llmModel}" — re-save the profile with a current model`);
    delete data.llmModel;
    delete data.llmProvider;
  } else if (data.llmProvider !== undefined && !VALID_LLM_PROVIDERS.has(String(data.llmProvider))) {
    warnings.push(`skipped stale llmProvider "${data.llmProvider}"`);
    delete data.llmProvider;
  }
  await p.agentConfig.update({ where: { id: "default" }, data });

  // Bust the agent's runtime-config cache so the applied profile takes
  // effect on the very next call (same as a Settings save).
  try {
    const py = process.env.PYTHON_API_URL ?? "http://localhost:8000";
    const apiKey = process.env.CONTROL_API_KEY ?? "";
    await fetch(`${py}/api/config/reload`, {
      method: "POST",
      headers: { ...(apiKey ? { "X-API-Key": apiKey } : {}) },
    });
  } catch {
    /* non-fatal: cache expires by TTL */
  }
  return NextResponse.json({ ok: true, applied: profile.name, warnings });
}
