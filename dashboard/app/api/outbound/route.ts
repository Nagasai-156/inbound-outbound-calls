import { proxy } from "@/lib/pyapi";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const body = await req.text();
  return proxy("/api/outbound", { method: "POST", body });
}
