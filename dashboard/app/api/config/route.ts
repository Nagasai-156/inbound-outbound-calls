import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";
import { LLM_MODELS, LLM_PROVIDERS } from "@/lib/options";

// Server-side allowlist: ONLY values the current dashboard offers can be
// saved. A stale browser tab / external POST once wrote a dead model
// (cerebras/llama-4.1-405b) that 400-erred every LLM turn on live calls.
const VALID_LLM_MODELS = new Set<string>(LLM_MODELS.map((m) => m.value));
const VALID_LLM_PROVIDERS = new Set<string>(LLM_PROVIDERS.map((p) => p.value));

export const dynamic = "force-dynamic";

const FIELDS = [
  "ttsModel", "defaultLanguage", "ttsSpeakerTe", "ttsSpeakerHi",
  "ttsSpeakerEn", "ttsPace", "ttsPaceTe", "ttsPaceHi", "ttsPaceEn",
  "minEndpointingDelay", "maxEndpointingDelay",
  "teluguMinEndpointingDelay", "minInterruptionDuration",
  "fillerLatencyThreshold", "fillerMinSttConfidence", "inboundPersona",
  "outboundPersona", "businessDescription", "styleExamples",
  "agentName", "useCaseType", "autoMirrorLanguage", "llmProvider", "llmModel", "llmTemperature",
  "memoryMaxTurns", "llmPromptMaxTokens", "kbVectorStoreId",
  "cacheMinSimilarity", "sttModel",
  "sttMode",
  "apptOpenHour", "apptCloseHour", "apptSlotMin", "apptOpenWeekdays",
  "enabledTools", "ttsAudioCache", "ttsProvider",
] as const;

const FLOATS = new Set([
  "ttsPace", "ttsPaceTe", "ttsPaceHi", "ttsPaceEn",
  "minEndpointingDelay", "maxEndpointingDelay",
  "teluguMinEndpointingDelay", "minInterruptionDuration",
  "fillerLatencyThreshold", "fillerMinSttConfidence", "llmTemperature",
  "cacheMinSimilarity",
]);
const INTS = new Set([
  "memoryMaxTurns", "llmPromptMaxTokens",
  "apptOpenHour", "apptCloseHour", "apptSlotMin",
]);
const BOOLS = new Set(["autoMirrorLanguage", "ttsAudioCache"]);

async function requireUser() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  return user;
}

export async function GET() {
  if (!(await requireUser()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const cfg = await prisma.agentConfig.upsert({
    where: { id: "default" },
    update: {},
    create: { id: "default", updatedBy: "auto" },
  });
  return NextResponse.json({ config: cfg });
}

export async function PUT(req: Request) {
  const user = await requireUser();
  if (!user)
    return NextResponse.json({ error: "unauth" }, { status: 401 });

  const body = await req.json();
  const data: Record<string, unknown> = { updatedBy: user.email ?? "" };
  for (const f of FIELDS) {
    if (!(f in body)) continue;
    let v: unknown = body[f];
    if (FLOATS.has(f)) v = parseFloat(v as string);
    else if (INTS.has(f)) v = parseInt(v as string, 10);
    else if (BOOLS.has(f)) {
      // Boolean("false") === true — so coerce strings/numbers explicitly
      // (a stale client sending "false" must NOT flip the flag on).
      v = v === true || v === "true" || v === 1 || v === "1";
    }
    if (FLOATS.has(f) || INTS.has(f)) {
      if (Number.isNaN(v)) continue; // ignore bad numeric input
    }
    data[f] = v;
  }
  if (data.llmModel !== undefined && !VALID_LLM_MODELS.has(String(data.llmModel)))
    return NextResponse.json(
      { error: `invalid llmModel "${data.llmModel}" — pick one from the dashboard list` },
      { status: 400 },
    );
  if (data.llmProvider !== undefined && !VALID_LLM_PROVIDERS.has(String(data.llmProvider)))
    return NextResponse.json(
      { error: `invalid llmProvider "${data.llmProvider}" — valid: ${[...VALID_LLM_PROVIDERS].join(", ")}` },
      { status: 400 },
    );
  const cfg = await prisma.agentConfig.update({
    where: { id: "default" },
    data,
  });
  // Bust the agent's runtime-config cache so the NEXT call (inbound or
  // outbound) uses these saved settings immediately, not 30s later.
  try {
    const py = process.env.PYTHON_API_URL ?? "http://localhost:8000";
    const apiKey = process.env.CONTROL_API_KEY ?? "";
    await fetch(`${py}/api/config/reload`, {
      method: "POST",
      headers: { ...(apiKey ? { "X-API-Key": apiKey } : {}) },
    });
  } catch {
    /* non-fatal: cache still expires by TTL */
  }
  return NextResponse.json({ config: cfg });
}
