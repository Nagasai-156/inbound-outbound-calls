import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const FIELDS = [
  "name","ttsProvider","ttsModel","defaultLanguage","ttsSpeakerTe","ttsSpeakerHi","ttsSpeakerEn",
  "ttsPace","ttsPaceTe","ttsPaceHi","ttsPaceEn",
  "autoMirrorLanguage","minEndpointingDelay","maxEndpointingDelay",
  "teluguMinEndpointingDelay","minInterruptionDuration","fillerLatencyThreshold",
  "fillerMinSttConfidence","inboundPersona","outboundPersona","businessDescription",
  "styleExamples","useCaseType","enabledTools","llmProvider","llmModel","llmTemperature",
  "sttModel","sttMode","memoryMaxTurns","llmPromptMaxTokens","cacheMinSimilarity",
  "ttsAudioCache","kbVectorStoreId",
  "apptOpenHour","apptCloseHour","apptSlotMin","apptOpenWeekdays",
];

// Numeric / boolean coercion so values arrive in the right type for
// Prisma (the client sends strings from form inputs).
const FLOATS = new Set([
  "ttsPace","ttsPaceTe","ttsPaceHi","ttsPaceEn","minEndpointingDelay",
  "maxEndpointingDelay","teluguMinEndpointingDelay","minInterruptionDuration",
  "fillerLatencyThreshold","fillerMinSttConfidence","llmTemperature","cacheMinSimilarity",
]);
const INTS = new Set([
  "memoryMaxTurns","llmPromptMaxTokens","apptOpenHour","apptCloseHour","apptSlotMin",
]);
const BOOLS = new Set(["autoMirrorLanguage","ttsAudioCache"]);

function coerce(k: string, v: unknown): unknown {
  if (FLOATS.has(k)) return parseFloat(v as string);
  if (INTS.has(k)) return parseInt(v as string, 10);
  if (BOOLS.has(k)) return v === true || v === "true" || v === 1 || v === "1";
  return v;
}

async function auth() {
  const { data: { user } } = await createClient().auth.getUser();
  return user;
}

export async function GET() {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const p = prisma as any;
  const profiles = await p.voiceConfig.findMany({ orderBy: { createdAt: "desc" } });
  return NextResponse.json({ profiles });
}

export async function POST(req: Request) {
  try {
    if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
    const body = await req.json();
    if (!body.name?.trim()) return NextResponse.json({ error: "name required" }, { status: 400 });
    const data: any = {};
    for (const k of FIELDS) {
      if (body[k] === undefined) continue;
      if (k === "name") { data.name = String(body.name).trim(); continue; }
      const v = coerce(k, body[k]);
      if ((FLOATS.has(k) || INTS.has(k)) && Number.isNaN(v)) continue;
      data[k] = v;
    }
    const p = prisma as any;
    const profile = await p.voiceConfig.create({ data });
    return NextResponse.json({ profile });
  } catch (e: any) {
    console.error("[api/profiles POST]", e);
    return NextResponse.json(
      { error: "Could not save config" },
      { status: 500 }
    );
  }
}
