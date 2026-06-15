import SelfLearningList from "@/components/SelfLearning";
import { PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default function SelfLearningPage() {
  return (
    <div>
      <PageHeader
        title="Self Learning"
        subtitle="Review AI-extracted caller profiles. Approve a suggestion to let the AI remember this caller — their name, language, and last topic — so it greets them warmly next time."
      />
      <SelfLearningList />
    </div>
  );
}
