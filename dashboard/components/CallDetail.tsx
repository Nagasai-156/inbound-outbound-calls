"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import { Card, Badge, Spinner, CopyButton } from "@/components/ui";
import { estimateCallCost, inr } from "@/lib/cost";

type Turn = { role: string; text: string; ts: string };

function fmt(ts: string) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return ""; }
}

function CopyTranscript({ transcript }: { transcript: Turn[] }) {
  const text = transcript
    .map((t) => `[${fmt(t.ts)}] ${t.role === "user" ? "Caller" : "Agent"}: ${t.text}`)
    .join("\n");
  return <CopyButton text={text} />;
}

// Latency thresholds in ms. Tuned for voice-agent feel:
//   green  : <500ms  — feels instant
//   yellow : <1000ms — acceptable but noticeable
//   red    : >=1000ms — sounds slow
function latencyTone(ms: number): "ok" | "warn" | "bad" | "default" {
  if (!ms) return "default";
  if (ms < 500) return "ok";
  if (ms < 1000) return "warn";
  return "bad";
}

function LatencyCell({ ms, label }: { ms: number; label: string }) {
  const tone = latencyTone(ms);
  const colorClass =
    tone === "ok" ? "text-[#10b981]" :
    tone === "warn" ? "text-[#d97706]" :
    tone === "bad" ? "text-[#dc2626]" : "text-[var(--muted)]";
  return (
    <div className="flex flex-col items-start gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-[var(--faint)]">{label}</span>
      <span className={`tabular-nums font-mono text-[15px] font-semibold ${colorClass}`}>
        {ms ? `${ms} ms` : "—"}
      </span>
    </div>
  );
}

function LatencyRow({
  name, p50Ms, p95Ms, hint, note,
}: { name: string; p50Ms: number; p95Ms: number; hint: string; note?: string }) {
  return (
    <div className="grid grid-cols-[160px_1fr_1fr] gap-4 items-center py-2.5 border-b border-[var(--line)] last:border-b-0">
      <div className="flex flex-col">
        <span className="font-medium text-[13px] text-[var(--txt)]">{name}</span>
        <span className="text-[11px] text-[var(--muted)]">{hint}</span>
        {note ? (
          <span className="text-[10px] text-[var(--faint)] mt-0.5">{note}</span>
        ) : null}
      </div>
      <LatencyCell ms={p50Ms} label="Typical (p50)" />
      <LatencyCell ms={p95Ms} label="Tail (p95)" />
    </div>
  );
}

export default function CallDetail({ id }: { id: string }) {
  const [d, setD] = useState<{ call: any; transcript: Turn[]; suggestion?: any; applied?: boolean } | null>(null);
  const [tries, setTries] = useState(0);
  const [missing, setMissing] = useState(false);
  const [live, setLive] = useState(false);
  const [applying, setApplying] = useState(false);
  const [cfg, setCfg] = useState<any>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/calls/${id}`, { cache: "no-store" });
      if (r.ok) {
        setD(await r.json());
        setMissing(false);
      } else {
        setTries((t) => t + 1);
        if (r.status === 404) setMissing(true);
      }
    } catch {
      setTries((t) => t + 1);
    }
  }, [id]);

  const applySelfLearning = async () => {
    setApplying(true);
    try {
      const r = await fetch(`/api/calls/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (r.ok) {
        load();
      } else {
        alert("Failed to apply self-learning.");
      }
    } catch (err) {
      console.error(err);
      alert("Error applying self-learning.");
    } finally {
      setApplying(false);
    }
  };

  useEffect(() => {
    load();
    const supabase = createClient();
    const ch = supabase
      .channel(`call-${id}`)
      .on("postgres_changes", { event: "*", schema: "voiceai", table: "Transcript", filter: `callId=eq.${id}` }, () => load())
      .on("postgres_changes", { event: "*", schema: "voiceai", table: "Call", filter: `id=eq.${id}` }, () => load())
      .subscribe((status) => setLive(status === "SUBSCRIBED"));
    const poll = setInterval(load, 5000);
    return () => { supabase.removeChannel(ch); clearInterval(poll); };
  }, [id, load]);

  // Live AgentConfig — so the cost panel labels show the ACTUAL model in
  // use (gpt-4.1-nano / mistral / ...) instead of a hardcoded string.
  useEffect(() => {
    fetch("/api/config", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => setCfg(j))
      .catch(() => {});
  }, []);

  // Auto-scroll to latest turn
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [d?.transcript.length]);

  if (!d) {
    if (!missing || tries < 3) {
      return (
        <div className="flex items-center gap-2 text-[var(--muted)] py-10">
          <Spinner /> Loading call… (connecting / waiting for the first words)
        </div>
      );
    }
    return (
      <Card title="No transcript for this call">
        <p className="text-[var(--muted)] text-[13px] leading-relaxed">
          Nothing has been recorded for{" "}
          <span className="font-mono text-[var(--txt)]">{id}</span> yet.
          This means one of:
        </p>
        <ul className="text-[13px] text-[var(--muted)] mt-3 space-y-1.5 list-disc pl-5">
          <li>The call is still connecting — this page keeps checking.</li>
          <li>The callee didn&apos;t pick up / hung up before speaking.</li>
          <li>The agent ran but couldn&apos;t reach the database to save the transcript (transient network) — it self-recovers; a later call will persist normally.</li>
        </ul>
        <p className="text-[12px] text-[var(--faint)] mt-3">
          Auto-retrying every 5s ({tries} checks). It will appear here automatically if it lands.
        </p>
      </Card>
    );
  }
  const c = d.call;

  return (
    <div className="space-y-5">
      <Card title="Context">
        <div className="flex flex-wrap gap-2">
          {[
            ["dir", c.direction],
            ["status", c.status],
            ["lang", c.language],
            ["emotion", c.emotion],
            ["intent", c.intent],
            ["name", c.callerName || "—"],
            ["turns", c.turns],
            ["LLM", c.llmCalls],
            ["KB", c.kbCalls],
            ["bypass", c.bypassRate ? Math.round(c.bypassRate * 100) + "%" : "—"],
          ].map(([k, v]) => (
            <Badge key={String(k)}>{k} {String(v)}</Badge>
          ))}
        </div>
      </Card>

      {(() => {
        // Prefer robust percentiles; fall back to avg/max for older calls
        // (history rows store only avg/max — no migration). p50 = the turn
        // the caller typically feels; p95 = realistic tail (one caller
        // pause no longer wrecks the number).
        const eouP50 = c.p50EouRespMs || c.p50EouMs || c.avgEouMs || 0;
        const eouP95 = c.p95EouRespMs || c.p95EouMs || c.maxEouMs || 0;
        const llmP50 = c.p50LlmTtftMs || c.avgLlmTtftMs || 0;
        const llmP95 = c.p95LlmTtftMs || c.maxLlmTtftMs || 0;
        const ttsP50 = c.p50TtsTtfbMs || c.avgTtsTtfbMs || 0;
        const ttsP95 = c.p95TtsTtfbMs || c.maxTtsTtfbMs || 0;
        const asmP50 = c.p50AssemblyMs || c.avgAssemblyMs || 0;
        const asmP95 = c.p95AssemblyMs || c.maxAssemblyMs || 0;
        const snapP50 = c.p50SnapshotMs || c.avgSnapshotMs || 0;
        const snapP95 = c.p95SnapshotMs || c.maxSnapshotMs || 0;
        const totalP50 = eouP50 + llmP50 + ttsP50;
        const waitTurns = c.callerWaitTurns || 0;
        const hasData = eouP50 || llmP50 || ttsP50 || c.avgEouMs || c.avgLlmTtftMs;
        if (!hasData) return null;
        return (
        <Card
          title="Latency breakdown"
          desc="Per-call timing from the LiveKit metrics stream. Numbers are robust percentiles: Typical (p50) = the turn the caller usually feels, Tail (p95) = realistic worst-case. Green <500ms instant · yellow <1s ok · red ≥1s slow."
        >
          <LatencyRow
            name="Endpointing"
            hint="caller stop → end-of-turn detected"
            note={waitTurns ? `${waitTurns} caller-pause turn(s) excluded (not our latency)` : undefined}
            p50Ms={eouP50}
            p95Ms={eouP95}
          />
          <LatencyRow
            name="LLM first token"
            hint="prompt sent → first token back"
            p50Ms={llmP50}
            p95Ms={llmP95}
          />
          <LatencyRow
            name="Prompt assembly"
            hint="markers + memory build (inside LLM)"
            p50Ms={asmP50}
            p95Ms={asmP95}
          />
          <LatencyRow
            name="Snapshot DB read"
            hint="Appointment-table read (inside LLM)"
            p50Ms={snapP50}
            p95Ms={snapP95}
          />
          <LatencyRow
            name="TTS first audio"
            hint="text sent → first audio chunk"
            p50Ms={ttsP50}
            p95Ms={ttsP95}
          />
          <div className="mt-3 pt-3 border-t border-[var(--line)] text-[11px] text-[var(--muted)] leading-relaxed">
            Typical perceived response ≈ Endpointing + LLM + TTS ≈{" "}
            <span className="font-mono font-semibold text-[var(--txt)]">{totalP50} ms</span> (p50).
            Under ~1.0s feels instant; over ~1.5s sounds slow.
            {waitTurns ? " Caller-pause / STT-hang turns are excluded from Endpointing so the number reflects only our pipeline." : ""}
          </div>
        </Card>
        );
      })()}

      {(() => {
        const cost = estimateCallCost(c);
        // Labels reflect the LIVE AgentConfig (current settings), not a
        // hardcoded model — fixes the "switching isn't working" illusion.
        const llmName = cfg?.llmModel || "current model";
        const ttsName = cfg?.ttsModel ? `Sarvam ${cfg.ttsModel}` : "Sarvam Bulbul";
        const sttName = cfg?.sttModel ? `Sarvam ${cfg.sttModel}` : "Sarvam Saaras";
        const rows: [string, number, string][] = [
          [`TTS (${ttsName})`, cost.tts, "voice synthesis · per char"],
          [`STT (${sttName})`, cost.stt, "transcription · per min"],
          [`LLM (${llmName})`, cost.llm, "current model from settings"],
          ["LiveKit Cloud", cost.livekit, "agent session · per min"],
          ["Telephony (Vobiz)", cost.telephony, "India trunk · per min"],
        ];
        return (
          <Card
            title="Estimated cost"
            desc="Data-driven estimate from call duration + turns at current provider rates. Exact billing is in each provider's dashboard."
            actions={
              <span className="tabular-nums font-mono text-[18px] font-bold text-[var(--txt)]">
                {inr(cost.total)}
              </span>
            }
          >
            <div className="text-[11px] text-[var(--muted)] mb-2">
              Duration ≈ {cost.durationMin.toFixed(1)} min ·{" "}
              {c.turns || 0} turns
            </div>
            {rows.map(([name, amt, hint]) => (
              <div
                key={name}
                className="grid grid-cols-[1fr_auto] gap-3 items-center py-2 border-b border-[var(--line)] last:border-b-0"
              >
                <div className="flex flex-col">
                  <span className="text-[13px] text-[var(--txt)]">{name}</span>
                  <span className="text-[11px] text-[var(--muted)]">{hint}</span>
                </div>
                <span className="tabular-nums font-mono text-[14px] text-[var(--txt)]">
                  {inr(amt)}
                </span>
              </div>
            ))}
            <div className="grid grid-cols-[1fr_auto] gap-3 items-center pt-3 mt-1">
              <span className="text-[13px] font-semibold text-[var(--txt)]">
                Total {c.status === "live" ? "(so far)" : "per call"}
              </span>
              <span className="tabular-nums font-mono text-[16px] font-bold text-[var(--accent-2)]">
                {inr(cost.total)}
              </span>
            </div>
          </Card>
        );
      })()}

      {d.suggestion && (
        <Card title="Self Learning Suggestions">
          <div className="space-y-4">
            <p className="text-[13px] text-[var(--muted)]">
              The AI extracted the following profile details from this call. You can approve them to apply "Self Learning" so the AI remembers them on the caller&apos;s next call:
            </p>
            <div className="grid grid-cols-2 gap-4 text-[13px] border-[var(--line)] border p-4 rounded-xl bg-[#fafafa]">
              <div>
                <span className="text-[var(--muted)] block font-semibold text-[11px] uppercase tracking-wider">Phone</span>
                <span className="font-mono text-[var(--txt)]">+{d.suggestion.phone}</span>
              </div>
              <div>
                <span className="text-[var(--muted)] block font-semibold text-[11px] uppercase tracking-wider">Extracted Name</span>
                <span className="font-medium text-[var(--txt)]">{d.suggestion.name || "—"}</span>
              </div>
              <div>
                <span className="text-[var(--muted)] block font-semibold text-[11px] uppercase tracking-wider">Preferred Language</span>
                <span className="font-medium text-[var(--txt)]">{d.suggestion.language ? (d.suggestion.language === "te" ? "Telugu" : d.suggestion.language === "hi" ? "Hindi" : "English") : "—"}</span>
              </div>
              <div>
                <span className="text-[var(--muted)] block font-semibold text-[11px] uppercase tracking-wider">Last Intent</span>
                <span className="font-medium text-[var(--txt)]">{d.suggestion.last_intent || "—"}</span>
              </div>
              <div className="col-span-2">
                <span className="text-[var(--muted)] block font-semibold text-[11px] uppercase tracking-wider">Last Turn Summary</span>
                <p className="text-[var(--txt)] italic mt-1 bg-[#fff] border border-[var(--line)] px-3 py-2 rounded-lg">&ldquo;{d.suggestion.last_summary || "—"}&rdquo;</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              {d.applied ? (
                <button
                  disabled
                  className="px-4 py-2 bg-[rgba(16,185,129,0.12)] border border-[rgba(16,185,129,0.3)] text-[#10b981] font-medium text-[13px] rounded-lg cursor-not-allowed flex items-center gap-1.5"
                >
                  ✓ Self-Learning Applied
                </button>
              ) : (
                <button
                  onClick={applySelfLearning}
                  disabled={applying}
                  className="px-4 py-2 bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white font-medium text-[13px] rounded-lg transition-colors shadow-sm flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {applying ? "Applying..." : "Approve & Learn Caller Profile"}
                </button>
              )}
              {d.applied && (
                <span className="text-[12px] text-[var(--muted)]">
                  The AI will automatically welcome this caller back and refer to this topic next time they call!
                </span>
              )}
            </div>
          </div>
        </Card>
      )}

      <Card
        title="Transcript"
        actions={
          <div className="flex items-center gap-2">
            {d.transcript.length > 0 && <CopyTranscript transcript={d.transcript} />}
            <Badge tone={live ? "ok" : "default"}>
              {live ? "● live" : "polling (slow)"}
            </Badge>
          </div>
        }
      >
        <div className="flex flex-col gap-2 max-h-[60vh] overflow-auto pr-1">
          {d.transcript.length === 0 && (
            <p className="text-[var(--muted)] text-[13px]">No turns yet.</p>
          )}
          {d.transcript.map((t, i) => (
            <div key={i} className={
              "flex flex-col gap-0.5 max-w-[80%] " +
              (t.role === "user" ? "self-end items-end" : "self-start items-start")
            }>
              <div className={
                "px-4 py-2.5 rounded-2xl border text-[14px] shadow-sm " +
                (t.role === "user"
                  ? "bg-[var(--accent-soft)] border-[rgba(79,70,229,.22)] rounded-br-md"
                  : "bg-[#fbfbfc] border-[var(--line)] rounded-bl-md")
              }>
                <div className={
                  "text-[11px] font-semibold mb-0.5 " +
                  (t.role === "user" ? "text-[var(--accent-2)]" : "text-[var(--muted)]")
                }>
                  {t.role === "user" ? "Caller" : "Agent"}
                </div>
                {t.text}
              </div>
              {t.ts && (
                <span className="text-[10px] text-[var(--faint)] px-1">
                  {fmt(t.ts)}
                </span>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </Card>
    </div>
  );
}
