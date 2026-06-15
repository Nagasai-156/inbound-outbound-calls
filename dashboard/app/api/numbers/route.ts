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
  const numbers = await prisma.phoneNumber.findMany({
    orderBy: { createdAt: "desc" },
  });
  return NextResponse.json({ numbers });
}

export async function POST(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const b = await req.json();
  const e164 = String(b.e164 || "").trim();
  if (!/^\+\d{8,15}$/.test(e164))
    return NextResponse.json(
      { error: "Enter a valid E.164 number, e.g. +9198XXXXXXXX" },
      { status: 400 }
    );
  const inbound = !!b.inbound;
  const outbound = b.outbound === undefined ? true : !!b.outbound;
  if (!inbound && !outbound)
    return NextResponse.json(
      { error: "Pick at least one role: Inbound and/or Outbound" },
      { status: 400 }
    );
  try {
    const n = await prisma.phoneNumber.create({
      data: {
        e164,
        label: String(b.label || "").trim(),
        inbound,
        outbound,
      },
    });
    return NextResponse.json({ number: n });
  } catch {
    return NextResponse.json(
      { error: "That number already exists" },
      { status: 409 }
    );
  }
}

export async function DELETE(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const id = new URL(req.url).searchParams.get("id");
  if (!id)
    return NextResponse.json({ error: "id required" }, { status: 400 });
  try {
    await prisma.phoneNumber.delete({ where: { id } });
  } catch {
    // Unknown id → Prisma throws; return a clean 404 instead of a 500.
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return NextResponse.json({ ok: true });
}
