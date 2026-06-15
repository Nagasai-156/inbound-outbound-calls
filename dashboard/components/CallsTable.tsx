"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import {
  Card,
  Badge,
  EmptyState,
  Skeleton,
  Stat,
  StatGrid,
  SearchInput,
  CopyButton,
} from "@/components/ui";

type Call = {
  id: string;
  direction: string;
  status: string;
  language: string;
  emotion: string;
  intent: string;
  turns: number;
  bypassRate: number;
  avgEouMs?: number;
  avgLlmTtftMs?: number;
  avgTtsTtfbMs?: number;
};

// Same thresholds as CallDetail.LatencyCell — kept consistent intentionally.
function totalToneClass(ms: number): string {
  if (!ms) return "text-[var(--muted)]";
  if (ms < 800) return "text-[#10b981]";    // instant feel
  if (ms < 1500) return "text-[#d97706]";   // acceptable
  return "text-[#dc2626]";                  // slow
}

const ICONS = {
  total: "M3 3v18h18M7 14l4-4 4 4 5-6",
  live: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zM12 8v4l3 2",
  turns: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  bypass: "M13 2 3 14h7l-1 8 10-12h-7l1-8z",
};

function Ico({ d }: { d: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

function SkeletonRows() {
  return (
    <>
      {[...Array(5)].map((_, i) => (
        <tr key={i}>
          {["w-36", "w-20", "w-14", "w-16", "w-16", "w-10", "w-16", "w-16", "w-16"].map((w, j) => (
            <td key={j}><Skeleton className={`h-4 ${w}`} /></td>
          ))}
        </tr>
      ))}
    </>
  );
}

export default function CallsTable() {
  const [calls, setCalls] = useState<Call[] | null>(null);
  const [live, setLive] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const load = useCallback(async () => {
    const r = await fetch("/api/calls", { cache: "no-store" });
    if (r.ok) setCalls((await r.json()).calls);
  }, []);

  useEffect(() => {
    load();
    const supabase = createClient();
    const ch = supabase
      .channel("calls-rt")
      .on("postgres_changes", { event: "*", schema: "voiceai", table: "Call" }, () => load())
      .subscribe((s) => setLive(s === "SUBSCRIBED"));
    const poll = setInterval(load, 5000);
    return () => { supabase.removeChannel(ch); clearInterval(poll); };
  }, [load]);

  const list = calls ?? [];
  const liveNow = list.filter((c) => c.status === "live").length;
  const totalTurns = list.reduce((s, c) => s + (c.turns || 0), 0);
  const avgTurns = list.length ? Math.round(totalTurns / list.length) : 0;
  const bypassVals = list.filter((c) => c.bypassRate != null);
  const avgBypass = bypassVals.length
    ? Math.round((bypassVals.reduce((s, c) => s + c.bypassRate, 0) / bypassVals.length) * 100)
    : 0;

  const filtered = list.filter((c) => {
    const q = search.toLowerCase();
    const matchSearch = !q || c.id.toLowerCase().includes(q) || (c.language || "").toLowerCase().includes(q) || (c.emotion || "").toLowerCase().includes(q) || (c.intent || "").toLowerCase().includes(q);
    const matchStatus = !statusFilter || c.status === statusFilter;
    return matchSearch && matchStatus;
  });

  const statuses = [...new Set(list.map((c) => c.status))];

  return (
    <div>
      <StatGrid>
        <Stat label="Total calls" value={calls ? list.length : "—"} icon={<Ico d={ICONS.total} />} />
        <Stat label="Live now" value={calls ? liveNow : "—"} tone={liveNow ? "ok" : "default"} hint={liveNow ? "in progress" : "idle"} icon={<Ico d={ICONS.live} />} />
        <Stat label="Avg turns / call" value={calls ? avgTurns : "—"} icon={<Ico d={ICONS.turns} />} />
        <Stat label="Avg LLM bypass" value={calls ? avgBypass + "%" : "—"} tone={avgBypass >= 50 ? "ok" : "default"} hint="canned + cache hit-rate" icon={<Ico d={ICONS.bypass} />} />
      </StatGrid>

      <Card
        title="Recent calls"
        desc="Language, emotion, intent and LLM-bypass per call — streaming over Supabase Realtime."
        actions={
          <Badge tone={live ? "ok" : "default"}>
            {live ? "● live" : "polling"}
          </Badge>
        }
      >
        {/* filters */}
        <div className="flex flex-wrap gap-2 mb-4">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search calls…"
            className="w-[220px]"
          />
          {statuses.length > 1 && (
            <select
              className="select !w-auto !py-2 !text-[13px]"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">All statuses</option>
              {statuses.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          )}
        </div>

        {!calls ? (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Call</th><th>Direction</th><th>Language</th>
                  <th>Emotion</th><th>Intent</th><th>Turns</th>
                  <th>LLM bypass</th><th>Latency</th><th>Status</th>
                </tr>
              </thead>
              <tbody><SkeletonRows /></tbody>
            </table>
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title={search || statusFilter ? "No matching calls" : "No calls yet"}
            desc={search || statusFilter ? "Try a different search or filter." : "Place a single call or run a campaign to see them here."}
          />
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Call</th><th>Direction</th><th>Language</th>
                  <th>Emotion</th><th>Intent</th><th>Turns</th>
                  <th>LLM bypass</th><th>Latency</th><th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <div className="flex items-center gap-1">
                        <Link
                          className="text-[var(--accent-2)] font-medium font-mono text-[13px] hover:underline"
                          href={`/calls/${c.id}`}
                          title={c.id}
                        >
                          {c.id.slice(0, 18)}…
                        </Link>
                        <CopyButton text={c.id} />
                      </div>
                    </td>
                    <td>
                      <Badge tone={c.direction === "inbound" ? "info" : "default"}>{c.direction}</Badge>
                    </td>
                    <td className="uppercase text-[12px] font-medium">{c.language || "—"}</td>
                    <td>{c.emotion || "—"}</td>
                    <td>{c.intent || "—"}</td>
                    <td className="tabular-nums">{c.turns}</td>
                    <td className="tabular-nums">{c.bypassRate ? Math.round(c.bypassRate * 100) + "%" : "—"}</td>
                    <td className={`tabular-nums font-mono text-[12px] font-medium ${totalToneClass((c.avgEouMs || 0) + (c.avgLlmTtftMs || 0) + (c.avgTtsTtfbMs || 0))}`} title="Average total response time (Endpointing + LLM + TTS)">
                      {(c.avgEouMs || c.avgLlmTtftMs || c.avgTtsTtfbMs)
                        ? `${(c.avgEouMs || 0) + (c.avgLlmTtftMs || 0) + (c.avgTtsTtfbMs || 0)} ms`
                        : "—"}
                    </td>
                    <td>
                      <Badge tone={c.status === "live" ? "ok" : c.status === "failed" ? "bad" : "default"}>
                        {c.status === "live" ? "● live" : c.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {calls && filtered.length > 0 && list.length > filtered.length && (
          <p className="text-[12px] text-[var(--muted)] mt-3 text-right">
            Showing {filtered.length} of {list.length} calls
          </p>
        )}
      </Card>
    </div>
  );
}
