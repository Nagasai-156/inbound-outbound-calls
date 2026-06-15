"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Card,
  Badge,
  Spinner,
  Button,
  EmptyState,
  SearchInput,
  ConfirmDialog,
} from "@/components/ui";

type Suggestion = {
  callId: string;
  suggestion: {
    phone: string;
    name: string;
    language: string;
    last_intent: string;
    last_summary: string;
    last_call_at: number;
    call_count: number;
  };
  applied: boolean;
  call?: {
    id: string;
    direction: string;
    callerName: string;
    language: string;
    status: string;
    startedAt: string;
    outcome: string;
  };
};

const LANG: Record<string, string> = {
  te: "Telugu",
  hi: "Hindi",
  en: "English",
  "te-mix": "Tenglish",
  "hi-mix": "Hinglish",
};

function fmtDate(epoch: number) {
  if (!epoch) return "—";
  try {
    return new Date(epoch * 1000).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

export default function SelfLearningList() {
  const [items, setItems] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [acting, setActing] = useState<string | null>(null); // callId being acted on
  const [confirm, setConfirm] = useState<{
    callId: string;
    action: "approve" | "reject";
  } | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/self-learning", { cache: "no-store" });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      setItems(data.suggestions || []);
      setError("");
    } catch (err: any) {
      setError(err.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [load]);

  const doAction = async (callId: string, action: "approve" | "reject") => {
    setActing(callId);
    try {
      const r = await fetch("/api/self-learning", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callId, action }),
      });
      if (!r.ok) throw new Error(await r.text());
      await load();
    } catch (err: any) {
      alert(`Failed to ${action}: ${err.message}`);
    } finally {
      setActing(null);
      setConfirm(null);
    }
  };

  const filtered = items.filter((s) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      (s.suggestion.phone || "").includes(q) ||
      (s.suggestion.name || "").toLowerCase().includes(q) ||
      (s.suggestion.last_intent || "").toLowerCase().includes(q) ||
      (s.suggestion.last_summary || "").toLowerCase().includes(q) ||
      (s.callId || "").toLowerCase().includes(q) ||
      (s.call?.callerName || "").toLowerCase().includes(q)
    );
  });

  const pending = filtered.filter((s) => !s.applied);
  const approved = filtered.filter((s) => s.applied);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[var(--muted)] py-10">
        <Spinner /> Loading self-learning suggestions…
      </div>
    );
  }

  if (error) {
    return (
      <Card title="Error">
        <p className="text-[var(--bad)] text-[13px]">{error}</p>
        <Button className="mt-3" onClick={load}>
          Retry
        </Button>
      </Card>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7z" />
            <circle cx="12" cy="9" r="2.5" />
          </svg>
        }
        title="No self-learning suggestions yet"
        desc="After each call, the AI extracts caller profile details (name, language, intent). They will appear here for your review and approval."
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Stats bar */}
      <div className="flex flex-wrap gap-3">
        <Badge tone="info">
          {items.length} total
        </Badge>
        <Badge tone="warn">
          {items.filter((s) => !s.applied).length} pending review
        </Badge>
        <Badge tone="ok">
          {items.filter((s) => s.applied).length} approved
        </Badge>
      </div>

      <SearchInput
        value={search}
        onChange={setSearch}
        placeholder="Search by phone, name, intent, or call ID…"
        className="max-w-md"
      />

      {/* Pending section */}
      {pending.length > 0 && (
        <div>
          <h2
            className="text-[14px] font-semibold text-[var(--txt)] mb-3 flex items-center gap-2"
          >
            <span
              className="w-2 h-2 rounded-full"
              style={{ background: "var(--warn)" }}
            />
            Pending Review ({pending.length})
          </h2>
          <div className="grid gap-3">
            {pending.map((s) => (
              <SuggestionCard
                key={s.callId}
                s={s}
                acting={acting}
                onApprove={() =>
                  setConfirm({ callId: s.callId, action: "approve" })
                }
                onReject={() =>
                  setConfirm({ callId: s.callId, action: "reject" })
                }
              />
            ))}
          </div>
        </div>
      )}

      {/* Approved section */}
      {approved.length > 0 && (
        <div>
          <h2
            className="text-[14px] font-semibold text-[var(--txt)] mb-3 flex items-center gap-2"
          >
            <span
              className="w-2 h-2 rounded-full"
              style={{ background: "var(--ok)" }}
            />
            Approved ({approved.length})
          </h2>
          <div className="grid gap-3">
            {approved.map((s) => (
              <SuggestionCard
                key={s.callId}
                s={s}
                acting={acting}
                onApprove={() => {}}
                onReject={() => {}}
              />
            ))}
          </div>
        </div>
      )}

      {filtered.length === 0 && search && (
        <div className="text-center py-10 text-[var(--muted)] text-[13px]">
          No suggestions match &ldquo;{search}&rdquo;
        </div>
      )}

      {/* Confirm dialog */}
      <ConfirmDialog
        open={!!confirm}
        title={
          confirm?.action === "approve"
            ? "Approve Self-Learning?"
            : "Reject Suggestion?"
        }
        desc={
          confirm?.action === "approve"
            ? "This will save the caller profile so the AI remembers this person on their next call. The agent will greet them warmly and reference their last topic."
            : "This will discard the suggestion. The AI will NOT remember this caller on their next call."
        }
        confirmLabel={confirm?.action === "approve" ? "Approve" : "Reject"}
        tone={confirm?.action === "approve" ? "primary" : "danger"}
        onConfirm={() => {
          if (confirm) doAction(confirm.callId, confirm.action);
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

function SuggestionCard({
  s,
  acting,
  onApprove,
  onReject,
}: {
  s: Suggestion;
  acting: string | null;
  onApprove: () => void;
  onReject: () => void;
}) {
  const sug = s.suggestion;
  const busy = acting === s.callId;

  return (
    <div
      className="card !p-4 transition-shadow hover:shadow-lg"
      style={{
        borderLeft: `3px solid ${
          s.applied ? "var(--ok)" : "var(--warn)"
        }`,
      }}
    >
      <div className="flex flex-col sm:flex-row sm:items-start gap-4">
        {/* Profile info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            {/* Phone avatar */}
            <div
              className="w-8 h-8 rounded-full flex-shrink-0 grid place-items-center text-[11px] font-bold text-white"
              style={{
                background:
                  "linear-gradient(135deg, #6366f1, #8b5cf6)",
              }}
            >
              {(sug.name || sug.phone || "?")[0]?.toUpperCase()}
            </div>
            <div>
              <div className="font-semibold text-[14px] text-[var(--txt)]">
                {sug.name || "Unknown Caller"}
              </div>
              <div className="text-[12px] text-[var(--muted)] font-mono">
                +{sug.phone}
              </div>
            </div>
            {s.applied && (
              <Badge tone="ok">✓ Approved</Badge>
            )}
          </div>

          {/* Detail grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 text-[12px] mt-2">
            <div>
              <span className="text-[var(--faint)] block text-[10px] font-semibold uppercase tracking-wider">
                Language
              </span>
              <span className="text-[var(--txt)] font-medium">
                {LANG[sug.language] || sug.language || "—"}
              </span>
            </div>
            <div>
              <span className="text-[var(--faint)] block text-[10px] font-semibold uppercase tracking-wider">
                Last Intent
              </span>
              <span className="text-[var(--txt)] font-medium">
                {sug.last_intent || "—"}
              </span>
            </div>
            <div>
              <span className="text-[var(--faint)] block text-[10px] font-semibold uppercase tracking-wider">
                Call Count
              </span>
              <span className="text-[var(--txt)] font-medium">
                {sug.call_count}
              </span>
            </div>
            <div>
              <span className="text-[var(--faint)] block text-[10px] font-semibold uppercase tracking-wider">
                Last Call
              </span>
              <span className="text-[var(--txt)] font-medium">
                {fmtDate(sug.last_call_at)}
              </span>
            </div>
          </div>

          {/* Summary */}
          {sug.last_summary && (
            <div className="mt-2.5 bg-[#fafafa] border border-[var(--line)] rounded-lg px-3 py-2 text-[12px] text-[var(--muted)] italic">
              &ldquo;{sug.last_summary}&rdquo;
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex sm:flex-col gap-2 shrink-0">
          <Link
            href={`/call?id=${s.callId}`}
            className="btn btn-sm btn-ghost text-[12px] text-center"
          >
            View Call
          </Link>
          {!s.applied && (
            <>
              <button
                onClick={onApprove}
                disabled={busy}
                className="btn btn-sm btn-primary text-[12px] disabled:opacity-50"
              >
                {busy ? "…" : "Approve"}
              </button>
              <button
                onClick={onReject}
                disabled={busy}
                className="btn btn-sm btn-danger text-[12px] disabled:opacity-50"
              >
                {busy ? "…" : "Reject"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
