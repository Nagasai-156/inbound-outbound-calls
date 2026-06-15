"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const supabase = createClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"in" | "up">("in");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  // Public sign-up is OFF by default — this console can place outbound
  // calls / run campaigns (real cost + abuse), so open registration is a
  // security hole. Admins are created via `npm run seed:admin`. Set
  // NEXT_PUBLIC_ALLOW_SIGNUP=true to re-enable the in-UI sign-up (also
  // ensure Supabase open-signups are disabled if you keep it off).
  const allowSignup = process.env.NEXT_PUBLIC_ALLOW_SIGNUP === "true";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (mode === "up" && !allowSignup) {
      setMsg("Sign-up is disabled. Ask an admin to create your account.");
      setMode("in");
      return;
    }
    setBusy(true);
    setMsg("");
    const { error } =
      mode === "in"
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password });
    setBusy(false);
    if (error) return setMsg(error.message);
    if (mode === "up") {
      setMsg("Account created — sign in now.");
      setMode("in");
      return;
    }
    router.push("/");
    router.refresh();
  }

  const Mark = ({ s = 36 }: { s?: number }) => (
    <span
      className="grid place-items-center rounded-xl text-white shrink-0"
      style={{
        width: s,
        height: s,
        background: "linear-gradient(150deg,var(--accent),var(--accent-2))",
        boxShadow: "0 6px 14px -6px rgba(79,70,229,.6)",
      }}
    >
      <svg
        width={s * 0.55}
        height={s * 0.55}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="9" y="2" width="6" height="12" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
    </span>
  );

  return (
    <main className="min-h-screen grid lg:grid-cols-2">
      {/* Brand panel */}
      <div className="hidden lg:flex flex-col justify-between p-12 relative overflow-hidden border-r border-[var(--line)] bg-white">
        <div className="flex items-center gap-3">
          <Mark />
          <span className="font-semibold text-lg tracking-tight">
            Voice Console
          </span>
        </div>
        <div className="relative z-10">
          <h2 className="text-3xl font-semibold leading-tight max-w-md">
            Realtime multilingual AI voice calling.
          </h2>
          <p className="text-[var(--muted)] mt-4 max-w-md">
            Telugu · Hindi · English. Inbound &amp; outbound, bulk
            campaigns, knowledge-grounded answers, live monitoring — one
            console.
          </p>
          <div className="flex flex-wrap gap-2 mt-6">
            {["Sub-second", "Barge-in", "KB-grounded", "Multilingual"].map(
              (t) => (
                <span key={t} className="badge badge-info">
                  {t}
                </span>
              )
            )}
          </div>
        </div>
        <div className="text-[12px] text-[var(--faint)] relative z-10">
          © {new Date().getFullYear()} Diigoo
        </div>
        <div className="absolute -bottom-32 -right-32 w-96 h-96 rounded-full bg-[var(--accent)] opacity-[0.12] blur-3xl" />
      </div>

      {/* Form */}
      <div className="flex items-center justify-center p-6">
        <form
          onSubmit={submit}
          className="card w-full max-w-[400px] space-y-5"
        >
          <div className="lg:hidden flex items-center gap-2.5 mb-2">
            <Mark s={32} />
            <span className="font-semibold tracking-tight">
              Voice Console
            </span>
          </div>
          <div>
            <h1 className="text-xl font-semibold">
              {mode === "in" ? "Welcome back" : "Create your account"}
            </h1>
            <p className="text-[var(--muted)] text-[13px] mt-1">
              {mode === "in"
                ? "Sign in to your console"
                : "Set up an admin login"}
            </p>
          </div>
          <div>
            <span className="label">Email</span>
            <input
              className="input"
              type="email"
              placeholder="admin@diigoo.ai"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <span className="label">Password</span>
            <input
              className="input"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <button
            className="btn btn-primary w-full"
            disabled={busy}
          >
            {busy
              ? "Please wait…"
              : mode === "in"
                ? "Sign in"
                : "Create account"}
          </button>
          {msg && (
            <p className="text-[13px] text-[var(--bad)]">{msg}</p>
          )}
          {allowSignup && (
            <button
              type="button"
              className="text-[var(--accent-2)] text-[13px] w-full text-center"
              onClick={() => setMode(mode === "in" ? "up" : "in")}
            >
              {mode === "in"
                ? "Need an account? Sign up"
                : "Have an account? Sign in"}
            </button>
          )}
        </form>
      </div>
    </main>
  );
}
