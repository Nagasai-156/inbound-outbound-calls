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

export async function GET() {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const campaigns = await prisma.campaign.findMany({
    orderBy: { createdAt: "desc" },
    take: 100,
  });
  return NextResponse.json({ campaigns });
}

// Body: { name, callerId, language, csv } — csv = "phone,name" per line.
export async function POST(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const b = await req.json();
  const name = String(b.name || "").trim();
  if (!name)
    return NextResponse.json({ error: "Name required" }, { status: 400 });

  const rows: { phone: string; name: string }[] = [];
  for (const raw of String(b.csv || "").split(/\r?\n/)) {
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
      { error: "No valid phone numbers found in the list" },
      { status: 400 }
    );

  const campaign = await prisma.campaign.create({
    data: {
      name,
      callerId: String(b.callerId || ""),
      language: String(b.language || ""),
      script: String(b.script || ""),
      voiceModel: String(b.voiceModel || ""),
      voiceSpeaker: String(b.voiceSpeaker || ""),
      useCaseType: String(b.useCaseType || ""),
      businessDescription: String(b.businessDescription || ""),
      styleExamples: String(b.styleExamples || ""),
      kbVectorStoreId: String(b.kbId || b.kbVectorStoreId || ""),
      kbId: String(b.kbId || ""),
      total: rows.length,
      contacts: { create: rows },
    },
  });
  return NextResponse.json({ campaign });
}
