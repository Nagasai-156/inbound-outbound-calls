import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

async function auth() {
  const s = createClient();
  const {
    data: { user },
  } = await s.auth.getUser();
  return user;
}

export async function GET(
  _r: Request,
  { params }: { params: { id: string } }
) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const campaign = await prisma.campaign.findUnique({
    where: { id: params.id },
  });
  if (!campaign)
    return NextResponse.json({ error: "not found" }, { status: 404 });
  const contacts = await prisma.campaignContact.findMany({
    where: { campaignId: params.id },
    orderBy: { updatedAt: "asc" },
    take: 1000,
  });
  // Durable run history — each Run / Re-run with its own per-contact
  // outcomes + transcript links (latest run first).
  const runs = await prisma.campaignRun.findMany({
    where: { campaignId: params.id },
    orderBy: { runNo: "desc" },
    include: {
      contacts: { orderBy: { updatedAt: "asc" }, take: 1000 },
    },
    take: 50,
  });
  return NextResponse.json({ campaign, contacts, runs });
}

// Edit a campaign's settings (name / caller ID / language / script /
// voice). Optionally replace the contact list via `csv` — that resets
// progress to draft so a re-run dials the new list cleanly. Blocked
// while the campaign is actively running (avoids a dialer race).
export async function PATCH(
  req: Request,
  { params }: { params: { id: string } }
) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });

  const existing = await prisma.campaign.findUnique({
    where: { id: params.id },
  });
  if (!existing)
    return NextResponse.json({ error: "not found" }, { status: 404 });
  if (existing.status === "running")
    return NextResponse.json(
      { error: "Campaign is running — wait for it to finish to edit" },
      { status: 409 }
    );

  const b = await req.json();
  const data: Record<string, unknown> = {};
  for (const k of [
    "name",
    "callerId",
    "language",
    "script",
    "voiceModel",
    "voiceSpeaker",
    "useCaseType",
    "businessDescription",
    "styleExamples",
    "kbVectorStoreId",
  ] as const) {
    if (b[k] !== undefined) data[k] = String(b[k] ?? "");
  }
  if (typeof data.name === "string" && !data.name.trim())
    return NextResponse.json({ error: "Name required" }, { status: 400 });

  // Optional contact-list replacement.
  const csv = typeof b.csv === "string" ? b.csv : null;
  if (csv && csv.trim()) {
    const rows: { phone: string; name: string }[] = [];
    for (const raw of csv.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line) continue;
      const [p, ...rest] = line.split(/[,;\t]/);
      const phone = (p || "").trim();
      if (/^\+?\d[\d\s-]{6,}$/.test(phone))
        rows.push({
          phone: phone.replace(/[\s-]/g, ""),
          name: rest.join(" ").trim(),
        });
    }
    if (rows.length === 0)
      return NextResponse.json(
        { error: "No valid phone numbers in the list" },
        { status: 400 }
      );
    await prisma.campaignContact.deleteMany({
      where: { campaignId: params.id },
    });
    data.total = rows.length;
    data.completed = 0;
    data.failed = 0;
    data.status = "draft";
    data.finishedAt = null;
    data.contacts = { create: rows };
  }

  const campaign = await prisma.campaign.update({
    where: { id: params.id },
    data,
  });
  return NextResponse.json({ campaign });
}

export async function DELETE(
  _r: Request,
  { params }: { params: { id: string } }
) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  try {
    await prisma.campaign.delete({ where: { id: params.id } });
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
