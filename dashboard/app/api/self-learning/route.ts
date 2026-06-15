import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getRedis } from "@/lib/redis";
import { prisma } from "@/lib/prisma";

export const dynamic = "force-dynamic";

/**
 * GET /api/self-learning
 * Returns all pending self-learning suggestions from Redis.
 * Each suggestion is a CallerProfile snapshot saved at call end,
 * keyed as `callerprofile:suggested:<callId>`.
 */
export async function GET() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "unauth" }, { status: 401 });

  try {
    const r = getRedis();

    // Scan for all suggested profiles
    const suggestions: {
      callId: string;
      suggestion: any;
      applied: boolean;
      call?: any;
    }[] = [];

    let cursor = "0";
    const seen = new Set<string>();
    do {
      const [nextCursor, keys] = await r.scan(
        cursor,
        "MATCH",
        "callerprofile:suggested:*",
        "COUNT",
        200
      );
      cursor = nextCursor;
      for (const key of keys) {
        const callId = key.replace("callerprofile:suggested:", "");
        if (seen.has(callId)) continue;
        seen.add(callId);
        try {
          const raw = await r.get(key);
          if (!raw) continue;
          const suggestion = JSON.parse(raw);
          const appliedKey = `callerprofile:applied:${callId}`;
          const isApplied = await r.get(appliedKey);
          suggestions.push({
            callId,
            suggestion,
            applied: !!isApplied,
          });
        } catch {
          // skip malformed entries
        }
      }
    } while (cursor !== "0");

    // Bulk-load Call metadata for each suggestion (direction, callerName, etc.)
    if (suggestions.length > 0) {
      const callIds = suggestions.map((s) => s.callId);
      const calls = await prisma.call.findMany({
        where: { id: { in: callIds } },
        select: {
          id: true,
          direction: true,
          callerName: true,
          language: true,
          status: true,
          startedAt: true,
          outcome: true,
        },
      });
      const callMap = new Map(calls.map((c) => [c.id, c]));
      for (const s of suggestions) {
        s.call = callMap.get(s.callId) || null;
      }
    }

    // Sort: pending first, then by call date descending
    suggestions.sort((a, b) => {
      if (a.applied !== b.applied) return a.applied ? 1 : -1;
      const ta = a.suggestion?.last_call_at || 0;
      const tb = b.suggestion?.last_call_at || 0;
      return tb - ta;
    });

    return NextResponse.json({ suggestions });
  } catch (err: any) {
    console.error("self-learning list failed", err);
    return NextResponse.json(
      { error: err.message || "Failed to load suggestions" },
      { status: 500 }
    );
  }
}

/**
 * POST /api/self-learning
 * Body: { callId, action: "approve" | "reject" }
 * Approve: copies the suggested profile → active callerprofile
 * Reject: deletes the suggestion key
 */
export async function POST(req: Request) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "unauth" }, { status: 401 });

  try {
    const body = await req.json();
    const { callId, action } = body as {
      callId: string;
      action: "approve" | "reject";
    };

    if (!callId || !["approve", "reject"].includes(action)) {
      return NextResponse.json(
        { error: "callId and action (approve|reject) required" },
        { status: 400 }
      );
    }

    const r = getRedis();
    const sugKey = `callerprofile:suggested:${callId}`;
    const rawSug = await r.get(sugKey);

    if (!rawSug) {
      return NextResponse.json(
        { error: "Suggestion not found or expired" },
        { status: 404 }
      );
    }

    if (action === "reject") {
      // Delete the suggestion — operator reviewed and decided not to learn
      await r.del(sugKey);
      return NextResponse.json({ ok: true, action: "rejected" });
    }

    // action === "approve"
    const suggestion = JSON.parse(rawSug);
    const phone = suggestion.phone;
    if (!phone) {
      return NextResponse.json(
        { error: "Invalid phone in suggestion" },
        { status: 400 }
      );
    }

    // Save as active CallerProfile in Redis (90-day TTL)
    const ttl = 60 * 60 * 24 * 90;
    await r.set(`callerprofile:${phone}`, JSON.stringify(suggestion), "EX", ttl);

    // Mark as applied
    await r.set(
      `callerprofile:applied:${callId}`,
      "true",
      "EX",
      60 * 60 * 24 * 7
    );

    // Update Call outcome in DB
    try {
      await prisma.call.update({
        where: { id: callId },
        data: { outcome: "Self-Learning Applied" },
      });
    } catch {
      // Call might not exist in DB yet (still live) — non-fatal
    }

    return NextResponse.json({ ok: true, action: "approved", profile: suggestion });
  } catch (err: any) {
    console.error("self-learning action failed", err);
    return NextResponse.json(
      { error: err.message || "Failed" },
      { status: 500 }
    );
  }
}
