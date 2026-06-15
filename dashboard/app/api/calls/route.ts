import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

// Recent calls (live first). Auth-gated like everything else.
export async function GET() {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "unauth" }, { status: 401 });

  const select = {
    id: true,
    direction: true,
    status: true,
    language: true,
    emotion: true,
    intent: true,
    callerName: true,
    turns: true,
    llmCalls: true,
    kbCalls: true,
    bypassRate: true,
    avgEouMs: true,
    avgLlmTtftMs: true,
    avgTtsTtfbMs: true,
    startedAt: true,
    endedAt: true,
  } as const;

  // Live calls FIRST, always (never dropped by the take:100 cap), then
  // the 100 most-recent finished calls. The old single query ordered by
  // `status asc` — alphabetical, which sorts "ended"/"failed" BEFORE
  // "live", so once ≥100 finished calls existed the in-progress live
  // calls fell off the end and vanished from the monitor.
  const [live, recent] = await Promise.all([
    prisma.call.findMany({
      where: { status: "live" },
      orderBy: { startedAt: "desc" },
      select,
    }),
    prisma.call.findMany({
      where: { status: { not: "live" } },
      orderBy: { startedAt: "desc" },
      take: 100,
      select,
    }),
  ]);
  return NextResponse.json({ calls: [...live, ...recent] });
}
