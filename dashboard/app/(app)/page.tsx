import CallsTable from "@/components/CallsTable";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default function CallsPage() {
  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Live operations at a glance — call volume, active calls, conversation depth and how often the agent answered without the LLM."
      />
      <CallsTable />
    </div>
  );
}
