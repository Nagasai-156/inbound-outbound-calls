import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

async function auth() {
  const { data: { user } } = await createClient().auth.getUser();
  return user;
}

export async function GET() {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const p = prisma as any;
  const kbs = await p.knowledgeBase.findMany({ orderBy: { createdAt: "desc" } });
  for (const kb of kbs) {
    kb._count = { docs: await p.kbDocument.count({ where: { kbId: kb.id } }) };
  }
  return NextResponse.json({ kbs });
}

export async function POST(req: Request) {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const { name, description = "" } = await req.json();
  if (!name?.trim()) return NextResponse.json({ error: "name required" }, { status: 400 });
  const p = prisma as any;
  const kb = await p.knowledgeBase.create({
    data: { name: name.trim(), description: description.trim() },
  });
  return NextResponse.json({ kb });
}
