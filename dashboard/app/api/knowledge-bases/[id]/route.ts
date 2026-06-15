import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

async function auth() {
  const { data: { user } } = await createClient().auth.getUser();
  return user;
}

export async function GET(_: Request, { params }: { params: { id: string } }) {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const p = prisma as any;
  const kb = await p.knowledgeBase.findUnique({ where: { id: params.id } });
  if (!kb) return NextResponse.json({ error: "not found" }, { status: 404 });
  const docs = await p.kbDocument.findMany({
    where: { kbId: params.id },
    orderBy: { createdAt: "desc" },
  });
  return NextResponse.json({ kb: { ...kb, docs } });
}

export async function PATCH(req: Request, { params }: { params: { id: string } }) {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const { name, description } = await req.json();
  const p = prisma as any;
  const kb = await p.knowledgeBase.update({
    where: { id: params.id },
    data: {
      ...(name !== undefined && { name: name.trim() }),
      ...(description !== undefined && { description: description.trim() }),
    },
  });
  return NextResponse.json({ kb });
}

export async function DELETE(_: Request, { params }: { params: { id: string } }) {
  if (!(await auth())) return NextResponse.json({ error: "unauth" }, { status: 401 });
  const p = prisma as any;
  try {
    await p.knowledgeBase.delete({ where: { id: params.id } });
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
