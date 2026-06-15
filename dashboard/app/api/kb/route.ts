import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const PY = process.env.PYTHON_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.CONTROL_API_KEY ?? "";

async function auth() {
  const s = createClient();
  const {
    data: { user },
  } = await s.auth.getUser();
  return user;
}

export async function GET(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const kbId = new URL(req.url).searchParams.get("kbId") || undefined;
  const docs = await prisma.kbDocument.findMany({
    where: kbId ? { kbId } : undefined,
    orderBy: { createdAt: "desc" },
    take: 200,
  });
  return NextResponse.json({ docs });
}

// Forward the uploaded file to the Python control API, which ingests it
// into the OpenAI vector store and records the KbDocument row.
export async function POST(req: Request) {
  try {
    if (!(await auth()))
      return NextResponse.json({ error: "unauth" }, { status: 401 });

    const kbId = new URL(req.url).searchParams.get("kbId") || "";

    const py = new URL(`${PY}/api/kb/upload`);
    if (kbId) py.searchParams.set("kb_id", kbId);

    const r = await fetch(py.toString(), {
      method: "POST",
      body: req.body,
      headers: {
        "content-type": req.headers.get("content-type") || "",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
      // @ts-expect-error duplex is required by undici for streaming bodies
      duplex: "half",
    });
    const text = await r.text();
    return new NextResponse(text, {
      status: r.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (e: any) {
    console.error("[api/kb POST]", e);
    return NextResponse.json({ error: e.message || String(e) }, { status: 500 });
  }
}

export async function DELETE(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const id = new URL(req.url).searchParams.get("id");
  if (!id)
    return NextResponse.json({ error: "id required" }, { status: 400 });

  // Verify the row exists before deletion (clean 404 instead of an
  // unhandled Prisma NotFoundError → opaque 500).
  const existing = await prisma.kbDocument.findUnique({ where: { id } });
  if (!existing)
    return NextResponse.json({ error: "not found" }, { status: 404 });

  // Purge the pgvector embeddings via the Python API FIRST. If that
  // fails (Python down, network blip), do NOT delete the dashboard row
  // — that would orphan the vectors with no UI handle to retry the
  // purge. Return 502 so the caller knows it's a downstream issue.
  let pyRes: Response;
  try {
    pyRes = await fetch(`${PY}/api/kb/${id}`, {
      method: "DELETE",
      headers: { ...(API_KEY ? { "X-API-Key": API_KEY } : {}) },
    });
  } catch (e: any) {
    return NextResponse.json(
      { error: `python api unreachable: ${e.message}` },
      { status: 502 }
    );
  }
  if (!pyRes.ok) {
    const txt = await pyRes.text().catch(() => "");
    return NextResponse.json(
      { error: `pgvector purge failed: ${txt.slice(0, 200)}` },
      { status: 502 }
    );
  }

  try {
    await prisma.kbDocument.delete({ where: { id } });
  } catch (e: any) {
    // FK violation or other Prisma error → don't crash the API.
    return NextResponse.json(
      { error: `delete failed: ${e.message || e}` },
      { status: 409 }
    );
  }
  return NextResponse.json({ ok: true });
}
