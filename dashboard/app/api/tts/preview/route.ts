import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const PY = process.env.PYTHON_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.CONTROL_API_KEY ?? "";

// Auth-gate then stream the Sarvam audio sample back to the browser.
export async function POST(req: Request) {
  const sb = createClient();
  const {
    data: { user },
  } = await sb.auth.getUser();
  if (!user) return new Response("unauth", { status: 401 });

  const body = await req.text();
  try {
    const r = await fetch(`${PY}/api/tts/preview`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
      body,
    });
    if (!r.ok) return new Response(await r.text(), { status: r.status });
    return new Response(r.body, {
      status: 200,
      headers: { "Content-Type": "audio/wav" },
    });
  } catch (e: any) {
    return new Response(`python api unreachable: ${e.message}`, {
      status: 502,
    });
  }
}
