import { proxy } from "@/lib/pyapi";

export const dynamic = "force-dynamic";

// Re-arm a finished campaign and dial it again. ?failed=1 retries only
// the contacts that didn't complete; otherwise the whole list re-runs.
export async function POST(
  r: Request,
  { params }: { params: { id: string } }
) {
  const failed = new URL(r.url).searchParams.get("failed") === "1";
  return proxy(
    `/api/campaigns/${params.id}/rerun${failed ? "?failed=1" : ""}`,
    { method: "POST" }
  );
}
