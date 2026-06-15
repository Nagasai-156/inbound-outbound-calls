import TestClient from "@/components/TestClient";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default function TestPage() {
  return (
    <div className="max-w-3xl">
      <PageHeader
        title="Test Client"
        subtitle="Talk to the agent from your browser — no phone needed. Live transcript streams via Supabase Realtime."
      />
      <TestClient />
    </div>
  );
}
