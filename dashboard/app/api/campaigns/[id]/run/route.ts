import { proxy } from "@/lib/pyapi";

export const dynamic = "force-dynamic";

// Hand the campaign to the Python control API, which dials each contact
// (throttled) via LiveKit/Vobiz and updates Supabase rows live.
export async function POST(
  _r: Request,
  { params }: { params: { id: string } }
) {
  return proxy(`/api/campaigns/${params.id}/run`, { method: "POST" });
}
