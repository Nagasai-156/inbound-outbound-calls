"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

const I = {
  calls:    "M3 3v18h18M7 14l4-4 4 4 5-6",
  phone:    "M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.18 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13 1.05.36 2 .7 3a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.96.34 1.95.57 3 .7A2 2 0 0 1 22 16.92z",
  dial:     "M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13 1.05.36 2 .7 3a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.96.34 1.95.57 3 .7A2 2 0 0 1 22 16.92z",
  campaign: "M3 11l19-9-9 19-2-8-8-2z",
  kb:       "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z",
  profile:  "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z",
  test:     "M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v4",
  appts:    "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM9 16l2 2 4-4",
  learn:    "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 1 1 7.072 0l-.548.547A3.374 3.374 0 0 0 14 18.469V19a2 2 0 1 1-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z",
  menu:     "M4 6h16M4 12h16M4 18h16",
};

const GROUPS = [
  { label: "Calls",     items: [
    { href: "/",           label: "Overview",       icon: "calls"    },
    { href: "/call",       label: "Single Call",    icon: "dial"     },
    { href: "/test",       label: "Test Call (no phone)", icon: "test" },
    { href: "/campaigns",  label: "Campaigns",      icon: "campaign" },
    { href: "/appointments",label: "Appointments",  icon: "appts"    },
  ]},
  { label: "Intelligence", items: [
    { href: "/self-learning", label: "Self Learning", icon: "learn"   },
  ]},
  { label: "Setup",     items: [
    { href: "/numbers",   label: "Phone Numbers",   icon: "phone"    },
    { href: "/knowledge", label: "Knowledge Base",  icon: "kb"       },
    { href: "/settings",  label: "Voice & Agent",   icon: "settings" },
  ]},
] as const;

type IconKey = keyof typeof I;

function Icon({ d, size = 15 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"
      strokeLinejoin="round" style={{ flexShrink: 0 }}>
      <path d={d} />
    </svg>
  );
}

function Logo() {
  return (
    <div style={{
      width: 30, height: 30, borderRadius: 8, flexShrink: 0,
      background: "#0284c7",
      display: "grid", placeItems: "center",
      boxShadow: "0 2px 8px rgba(2,132,199,.3)",
    }}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
        stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="9" y="2" width="6" height="12" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
    </div>
  );
}

function NavSection({ label, items, path, onNavigate }: {
  label: string;
  items: readonly { href: string; label: string; icon: IconKey }[];
  path: string;
  onNavigate?: () => void;
}) {
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{
        fontSize: 10.5, fontWeight: 700, letterSpacing: ".08em",
        textTransform: "uppercase", color: "var(--faint)",
        padding: "10px 10px 4px",
      }}>
        {label}
      </div>
      {items.map((n) => {
        const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
        return (
          <Link
            key={n.href}
            href={n.href}
            onClick={onNavigate}
            className={`nav-item ${active ? "nav-active" : ""}`}
            style={{ marginLeft: 10 }}
          >
            <Icon d={I[n.icon]} size={15} />
            {n.label}
          </Link>
        );
      })}
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const router = useRouter();

  async function signOut() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Brand */}
      <div style={{
        height: 56, display: "flex", alignItems: "center",
        padding: "0 16px", gap: 10,
        borderBottom: "1px solid var(--line)",
      }}>
        <Logo />
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, letterSpacing: "-0.025em", color: "var(--txt)" }}>
            Voice Console
          </div>
          <div style={{ fontSize: 10.5, color: "var(--faint)", marginTop: 0 }}>
            AI calling platform
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, overflowY: "auto", padding: "8px 6px" }}>
        {GROUPS.map((g) => (
          <NavSection
            key={g.label}
            label={g.label}
            items={g.items}
            path={path}
            onNavigate={onNavigate}
          />
        ))}
      </nav>

      {/* Sign out */}
      <div style={{
        padding: "10px 16px",
        borderTop: "1px solid var(--line)",
      }}>
        <button
          onClick={signOut}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "none", border: "none", cursor: "pointer",
            color: "var(--muted)", fontSize: 13, fontWeight: 500,
            padding: "6px 0", width: "100%", borderRadius: 6,
            transition: "color .13s",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--txt)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--muted)")}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
          Sign out
        </button>
      </div>
    </div>
  );
}

export default function Shell({
  email,
  children,
}: {
  email: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const initial = (email[0] || "A").toUpperCase();

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>

      {/* Desktop sidebar */}
      <aside
        className="hidden lg:block"
        style={{
          width: 232, flexShrink: 0,
          background: "#fff",
          borderRight: "1px solid var(--line)",
          position: "sticky", top: 0, height: "100vh",
        }}
      >
        <Sidebar />
      </aside>

      {/* Mobile overlay */}
      {open && (
        <div
          className="lg:hidden"
          style={{ position: "fixed", inset: 0, zIndex: 50 }}
        >
          <div
            onClick={() => setOpen(false)}
            style={{
              position: "absolute", inset: 0,
              background: "rgba(17,24,39,.4)",
              backdropFilter: "blur(4px)",
            }}
          />
          <aside
            style={{
              position: "absolute", left: 0, top: 0, bottom: 0,
              width: "80%", maxWidth: 260,
              background: "#fff",
              borderRight: "1px solid var(--line)",
              animation: "slideIn .16s ease",
            }}
          >
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      {/* Main */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>

        {/* Topbar */}
        <header style={{
          height: 52,
          background: "rgba(248,249,251,.92)",
          backdropFilter: "blur(10px)",
          WebkitBackdropFilter: "blur(10px)",
          borderBottom: "1px solid var(--line)",
          display: "flex", alignItems: "center",
          padding: "0 20px", gap: 12,
          position: "sticky", top: 0, zIndex: 30,
        }}>
          <button
            className="lg:hidden mobile-menu-btn"
            onClick={() => setOpen(true)}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: "var(--muted)", borderRadius: 6, padding: 4,
              display: "grid", placeItems: "center",
            }}
          >
            <Icon d={I.menu} size={18} />
          </button>

          <div style={{ flex: 1 }} />

          {/* User chip */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: "#fff",
            border: "1px solid var(--line)",
            borderRadius: 999,
            padding: "4px 10px 4px 5px",
            boxShadow: "var(--shadow-xs)",
          }}>
            <div style={{
              width: 24, height: 24, borderRadius: "50%",
              background: "#0284c7",
              display: "grid", placeItems: "center",
              fontSize: 10.5, fontWeight: 800, color: "#fff",
              flexShrink: 0,
            }}>
              {initial}
            </div>
            <span style={{
              fontSize: 12.5, color: "var(--muted)", fontWeight: 500,
              maxWidth: 160, overflow: "hidden",
              textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}
              className="hidden sm:block"
            >
              {email}
            </span>
          </div>
        </header>

        {/* Content */}
        <main style={{ flex: 1 }}>
          <div style={{
            maxWidth: 1160,
            margin: "0 auto",
            padding: "clamp(20px,3vw,36px) clamp(16px,3vw,32px)",
          }}>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
