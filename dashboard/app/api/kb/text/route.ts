import { proxy } from "@/lib/pyapi";

export const dynamic = "force-dynamic";

// Ingest pasted plain text (no file) into the KB.
export async function POST(req: Request) {
  const body = await req.text();
  return proxy("/api/kb/text", { method: "POST", body });
}
