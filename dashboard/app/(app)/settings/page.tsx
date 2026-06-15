import ConfigForm from "@/components/ConfigForm";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default function SettingsPage() {
  return (
    <div>
      <PageHeader
        title="Voice & Agent"
        subtitle="Every behaviour knob, persisted to Supabase. The agent reloads this at the start of every call — no redeploy."
      />
      <ConfigForm />
    </div>
  );
}
