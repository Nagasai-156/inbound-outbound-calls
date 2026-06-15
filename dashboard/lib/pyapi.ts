import { createClient } from "@/lib/supabase/server";

const BASE = process.env.PYTHON_API_URL ?? "http://localhost:8000";
// Shared secret for the Python control API (server-side only — never
// exposed to the browser). Must match CONTROL_API_KEY in the root .env.
const API_KEY = process.env.CONTROL_API_KEY ?? "";

// Guard a route then proxy JSON to the Python control API (LiveKit
// token / outbound dial / content regen all live there so we don't
// reimplement LiveKit/Sarvam logic in Node).
export async function proxy(
  path: string,
  init: RequestInit
): Promise<Response> {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user)
    return new Response(JSON.stringify({ error: "unauth" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  try {
    const r = await fetch(`${BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        ...(init.headers || {}),
      },
      cache: "no-store",
    });
    const text = await r.text();
    return new Response(text, {
      status: r.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (e: any) {
    return new Response(
      JSON.stringify({ error: `python api unreachable: ${e.message}` }),
      { status: 502, headers: { "Content-Type": "application/json" } }
    );
  }
}
