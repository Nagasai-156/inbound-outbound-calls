import Link from "next/link";
import CallDetail from "@/components/CallDetail";

export const dynamic = "force-dynamic";

export default function CallPage({ params }: { params: { id: string } }) {
  return (
    <div className="space-y-4">
      <Link href="/" className="text-accent text-sm">
        ← All calls
      </Link>
      <h1 className="text-xl font-semibold">Call {params.id}</h1>
      <CallDetail id={params.id} />
    </div>
  );
}
