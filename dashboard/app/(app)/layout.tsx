import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import Shell from "@/components/Shell";
import { ToastProvider } from "@/components/ui";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  return (
    <ToastProvider>
      <Shell email={user.email ?? ""}>{children}</Shell>
    </ToastProvider>
  );
}
