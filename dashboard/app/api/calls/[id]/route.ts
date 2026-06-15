import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";
import { getRedis } from "@/lib/redis";

export const dynamic = "force-dynamic";

export async function GET(
  _req: Request,
  { params }: { params: { id: string } }
) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "unauth" }, { status: 401 });

  const call = await prisma.call.findUnique({ where: { id: params.id } });

  // DB row exists → return DB + transcript (normal path)
  if (call) {
    const transcript = await prisma.transcript.findMany({
      where: { callId: params.id },
      orderBy: { ts: "asc" },
      select: { role: true, text: true, ts: true },
      take: 500,
    });
    let suggestion = null;
    let applied = false;
    try {
      const r = getRedis();
      const rawSug = await r.get(`callerprofile:suggested:${params.id}`);
      if (rawSug) {
        suggestion = JSON.parse(rawSug);
      }
      const isApplied = await r.get(`callerprofile:applied:${params.id}`);
      if (isApplied) {
        applied = true;
      }
    } catch (err) {
      console.error("failed to fetch suggestion from Redis", err);
    }
    return NextResponse.json({ call, transcript, suggestion, applied });
  }

  // DB row missing → call may be live but DB persistence is lagging.
  // Fall back to Redis (the hot-path store that's always written first).
  try {
    const r = getRedis();
    const [meta, raw, metrics] = await Promise.all([
      r.hgetall(`call:${params.id}:meta`),
      r.lrange(`call:${params.id}:transcript`, 0, 499),
      r.hgetall(`call:${params.id}:metrics`),
    ]);
    if (meta && meta.room) {
      const transcript = raw.map((s) => {
        try {
          const t = JSON.parse(s);
          const tsNum = Number(t.ts);
          return {
            role: t.role,
            text: t.text,
            ts: Number.isFinite(tsNum) ? new Date(tsNum * 1000).toISOString() : "",
          };
        } catch {
          return { role: "agent", text: s, ts: "" };
        }
      });
      // Shape matches the DB call object so CallDetail renders normally
      const liveCall = {
        id: params.id,
        room: meta.room ?? params.id,
        direction: meta.direction ?? "outbound",
        status: meta.status ?? "live",
        language: meta.language ?? "",
        emotion: meta.emotion ?? "",
        intent: meta.intent ?? "",
        callerName: meta.name ?? "",
        turns: Number(metrics?.turns ?? transcript.filter((t) => t.role === "user").length),
        llmCalls: Number(metrics?.llm_calls ?? 0),
        kbCalls: Number(metrics?.kb_calls ?? 0),
        bypassRate: metrics?.bypass_rate != null ? Number(metrics.bypass_rate) : null,
        // Latency aggregates — match the Call row shape so CallDetail
        // can render the same panel for live and ended calls.
        avgEouMs: Number(metrics?.avg_eou_ms ?? 0),
        maxEouMs: Number(metrics?.max_eou_ms ?? 0),
        avgLlmTtftMs: Number(metrics?.avg_llm_ttft_ms ?? 0),
        maxLlmTtftMs: Number(metrics?.max_llm_ttft_ms ?? 0),
        avgTtsTtfbMs: Number(metrics?.avg_tts_ttfb_ms ?? 0),
        maxTtsTtfbMs: Number(metrics?.max_tts_ttfb_ms ?? 0),
        // Robust percentiles (preferred by the UI when present): p50 =
        // typical turn, p95 = realistic tail. Endpointing also carries a
        // caller-pause-stripped 'responsive' view + the excluded count.
        p50EouMs: Number(metrics?.p50_eou_ms ?? 0),
        p95EouMs: Number(metrics?.p95_eou_ms ?? 0),
        p50EouRespMs: Number(metrics?.p50_eou_resp_ms ?? 0),
        p95EouRespMs: Number(metrics?.p95_eou_resp_ms ?? 0),
        callerWaitTurns: Number(metrics?.caller_wait_turns ?? 0),
        responsiveTurns: Number(metrics?.responsive_turns ?? 0),
        p50LlmTtftMs: Number(metrics?.p50_llm_ttft_ms ?? 0),
        p95LlmTtftMs: Number(metrics?.p95_llm_ttft_ms ?? 0),
        p50TtsTtfbMs: Number(metrics?.p50_tts_ttfb_ms ?? 0),
        p95TtsTtfbMs: Number(metrics?.p95_tts_ttfb_ms ?? 0),
        p50AssemblyMs: Number(metrics?.p50_assembly_ms ?? 0),
        p95AssemblyMs: Number(metrics?.p95_assembly_ms ?? 0),
        p50SnapshotMs: Number(metrics?.p50_snapshot_db_ms ?? 0),
        p95SnapshotMs: Number(metrics?.p95_snapshot_db_ms ?? 0),
        p50ResponseMs: Number(metrics?.p50_response_ms ?? 0),
        p95ResponseMs: Number(metrics?.p95_response_ms ?? 0),
        startedAt: meta.started_at ? new Date(Number(meta.started_at) * 1000) : new Date(),
        endedAt: null,
      };
      let suggestion = null;
      let applied = false;
      try {
        const rawSug = await r.get(`callerprofile:suggested:${params.id}`);
        if (rawSug) {
          suggestion = JSON.parse(rawSug);
        }
        const isApplied = await r.get(`callerprofile:applied:${params.id}`);
        if (isApplied) {
          applied = true;
        }
      } catch {}
      return NextResponse.json({ call: liveCall, transcript, suggestion, applied });
    }
  } catch {
    // Redis unreachable — fall through to 404
  }

  return NextResponse.json({ error: "not found" }, { status: 404 });
}

export async function POST(
  req: Request,
  { params }: { params: { id: string } }
) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "unauth" }, { status: 401 });

  try {
    const r = getRedis();
    const rawSug = await r.get(`callerprofile:suggested:${params.id}`);
    if (!rawSug) {
      return NextResponse.json({ error: "Suggestion not found or expired" }, { status: 400 });
    }

    const suggestion = JSON.parse(rawSug);
    const phone = suggestion.phone;
    if (!phone) {
      return NextResponse.json({ error: "Invalid phone number in suggestion" }, { status: 400 });
    }

    // Save as active CallerProfile in Redis
    const ttl = 60 * 60 * 24 * 90; // 90 days
    await r.set(`callerprofile:${phone}`, JSON.stringify(suggestion), "EX", ttl);

    // Mark as applied in Redis so CallDetail can render a disabled/success badge
    await r.set(`callerprofile:applied:${params.id}`, "true", "EX", 60 * 60 * 24 * 7);

    // Also update Call table in DB (set outcome to "Self-Learning Applied")
    try {
      await prisma.call.update({
        where: { id: params.id },
        data: { outcome: "Self-Learning Applied" },
      });
    } catch (dbErr) {
      console.error("failed to update call outcome in db", dbErr);
    }

    return NextResponse.json({ ok: true, profile: suggestion });
  } catch (err: any) {
    console.error("failed to apply self-learning", err);
    return NextResponse.json({ error: err.message || "Failed to apply self-learning" }, { status: 500 });
  }
}
