"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Card,
  Button,
  Badge,
  Spinner,
  Field,
  Input,
  Select,
  Textarea,
  useToast,
} from "@/components/ui";
import { LANGUAGES, TTS_MODELS, speakersFor, USE_CASES } from "@/lib/options";
import { createClient } from "@/lib/supabase/client";

const tone = (s: string) =>
  s === "done"
    ? "ok"
    : s === "failed"
      ? "bad"
      : s === "dialing" || s === "running"
        ? "info"
        : "default";

type Edit = {
  name: string;
  callerId: string;
  language: string;
  script: string;
  voiceModel: string;
  voiceSpeaker: string;
  useCaseType: string;
  businessDescription: string;
  styleExamples: string;
  kbVectorStoreId: string;
  csv: string;
};

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [callerIds, setCallerIds] = useState<any[]>([]);
  const [edit, setEdit] = useState<Edit | null>(null);
  const [openRun, setOpenRun] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`/api/campaigns/${id}`, { cache: "no-store" });
      if (r.ok) {
        const d = await r.json();
        setData(d);
        setEdit((prev) =>
          prev && dirty
            ? prev
            : {
                name: d.campaign.name || "",
                callerId: d.campaign.callerId || "",
                language: d.campaign.language || "",
                script: d.campaign.script || "",
                voiceModel: d.campaign.voiceModel || "",
                voiceSpeaker: d.campaign.voiceSpeaker || "",
                useCaseType: d.campaign.useCaseType || "custom",
                businessDescription: d.campaign.businessDescription || "",
                styleExamples: d.campaign.styleExamples || "",
                kbVectorStoreId: d.campaign.kbVectorStoreId || "",
                csv: "",
              }
        );
      }
    } catch {
      // Transient blip (dashboard recompile/restart, dropped conn).
      // This view polls + is realtime-driven, so just let the next
      // tick / Supabase event retry — never crash the page with an
      // unhandled "Failed to fetch".
    }
  }, [id, dirty]);

  useEffect(() => {
    load();
    fetch("/api/numbers")
      .then((r) => r.ok ? r.json() : { numbers: [] })
      .then((d) => {
        const cs = (d.numbers || [])
          .filter((n: any) => n.outbound && n.active)
          .map((n: any) => ({ value: n.e164, label: n.e164 }));
        setCallerIds(cs);
      })
      .catch(() => {});
    const sb = createClient();
    const ch = sb
      .channel(`camp-${id}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "voiceai", table: "CampaignContact" },
        () => load()
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "voiceai", table: "Campaign" },
        () => load()
      )
      .subscribe();
    const t = setInterval(load, 5000);
    return () => {
      sb.removeChannel(ch);
      clearInterval(t);
    };
  }, [id, load]);

  const setF = (k: keyof Edit, v: string) => {
    setEdit((e) => (e ? { ...e, [k]: v } : e));
    setDirty(true);
  };

  async function save() {
    if (!edit) return;
    setSaving(true);
    const r = await fetch(`/api/campaigns/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(edit),
    });
    const j = await r.json().catch(() => ({}));
    setSaving(false);
    if (r.ok) {
      setDirty(false);
      setEdit((e) => (e ? { ...e, csv: "" } : e));
      toast(
        edit.csv.trim()
          ? "Saved — contact list replaced, campaign reset to draft"
          : "Campaign settings saved",
        "ok"
      );
      load();
    } else toast(j.error || "Save failed", "bad");
  }

  async function run() {
    setBusy(true);
    const r = await fetch(`/api/campaigns/${id}/run`, { method: "POST" });
    setBusy(false);
    toast(
      r.ok ? "Campaign started — dialing…" : "Could not start",
      r.ok ? "ok" : "bad"
    );
    load();
  }

  async function rerun(onlyFailed: boolean) {
    setBusy(true);
    const r = await fetch(
      `/api/campaigns/${id}/rerun${onlyFailed ? "?failed=1" : ""}`,
      { method: "POST" }
    );
    const j = await r.json().catch(() => ({}));
    setBusy(false);
    toast(
      r.ok
        ? `Re-running ${j.rearmed ?? ""} contact(s) — dialing…`
        : j.detail || j.error || "Could not re-run",
      r.ok ? "ok" : "bad"
    );
    load();
  }

  if (!data || !edit) return <Spinner />;
  const c = data.campaign;
  const contacts = data.contacts || [];
  const pct = c.total ? Math.round((c.completed / c.total) * 100) : 0;
  const running = c.status === "running";
  const hasRun =
    c.status === "done" || c.completed > 0 || c.failed > 0;

  const Play = () =>
    busy ? (
      <Spinner />
    ) : (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor">
        <path d="M8 5v14l11-7z" />
      </svg>
    );

  return (
    <div className="space-y-5">
      <Link href="/campaigns" className="text-[var(--accent-2)] text-[13px]">
        ← Campaigns
      </Link>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{c.name}</h1>
          <p className="text-[var(--muted)] text-[13px] mt-1">
            {c.total} contacts · caller ID {c.callerId || "default"}
          </p>
        </div>
        {running ? (
          <Button variant="primary" disabled>
            <Spinner /> Running…
          </Button>
        ) : hasRun ? (
          <div className="flex gap-2">
            {c.failed > 0 && (
              <Button
                onClick={() => rerun(true)}
                disabled={busy || dirty}
                title="Dial only the contacts that didn't complete"
              >
                <Play /> Retry failed ({c.failed})
              </Button>
            )}
            <Button
              variant="primary"
              onClick={() => rerun(false)}
              disabled={busy || dirty}
              title="Reset every contact and dial the whole list again"
            >
              <Play /> Re-run all
            </Button>
          </div>
        ) : (
          <Button
            variant="primary"
            onClick={run}
            disabled={busy || dirty}
          >
            <Play /> Run campaign
          </Button>
        )}
      </div>

      {dirty && (
        <p className="text-[12px] text-[var(--warn)]">
          Unsaved changes — Save before running so the call uses them.
        </p>
      )}

      <Card>
        <div className="flex items-center gap-4 mb-3">
          <Badge tone={tone(c.status) as any}>{c.status}</Badge>
          <span className="text-[13px] text-[var(--muted)]">
            {c.completed}/{c.total} done · {c.failed} failed
          </span>
        </div>
        <div className="h-2 rounded-full bg-[var(--line-soft)] overflow-hidden">
          <div
            className="h-full bg-[var(--accent)] transition-all"
            style={{ width: pct + "%" }}
          />
        </div>
      </Card>

      <Card
        title="Edit campaign"
        desc="Change the script / language / voice, then Save and Re-run."
        actions={
          <Button
            variant="primary"
            onClick={save}
            disabled={saving || !dirty || running}
          >
            {saving ? <Spinner /> : null}
            {saving ? "Saving…" : dirty ? "Save changes" : "Saved"}
          </Button>
        }
      >
        <div className="grid gap-5">
          <div className="grid md:grid-cols-2 gap-5">
            <Field label="Campaign name">
              <Input
                value={edit.name}
                onChange={(e) => setF("name", e.target.value)}
              />
            </Field>
            <Field label="Caller ID">
              <Select
                value={edit.callerId}
                onChange={(v) => setF("callerId", v)}
                options={
                  callerIds.length
                    ? [{ value: "", label: "— default —" }, ...callerIds]
                    : [{ value: "", label: "— default —" }]
                }
              />
            </Field>
          </div>
          <Field
            label="Use-case"
            hint="Drives scoped behaviour + which tools the agent gets. Booking tools only for appointment-family; Custom & others cannot book."
          >
            <Select
              value={edit.useCaseType}
              onChange={(v) => setF("useCaseType", v)}
              options={USE_CASES}
            />
          </Field>
          <Field
            label="Call script / goal"
            hint="Overrides the global persona for THIS campaign's calls only."
          >
            <Textarea
              className="min-h-[130px]"
              value={edit.script}
              onChange={(e) => setF("script", e.target.value)}
              placeholder="You are calling to remind the patient of tomorrow's appointment. Confirm or reschedule. Warm, 1–2 short sentences."
            />
          </Field>
          <details className="rounded-lg border border-[var(--line-soft)] p-3">
            <summary className="text-[13px] cursor-pointer text-[var(--muted)]">
              Advanced — per-campaign overrides (blank = global)
            </summary>
            <div className="grid gap-4 mt-3">
              <Field label="Business description (this campaign)">
                <Textarea
                  className="min-h-[80px]"
                  value={edit.businessDescription}
                  onChange={(e) => setF("businessDescription", e.target.value)}
                  placeholder="Blank = global. Facts: services, hours, pricing/SMS policy."
                />
              </Field>
              <Field label="Style example (this campaign)">
                <Textarea
                  className="min-h-[80px]"
                  value={edit.styleExamples}
                  onChange={(e) => setF("styleExamples", e.target.value)}
                  placeholder="Blank = neutral built-in."
                />
              </Field>
              <Field label="KB vector store id (this campaign)">
                <input
                  className="input"
                  value={edit.kbVectorStoreId}
                  onChange={(e) => setF("kbVectorStoreId", e.target.value)}
                  placeholder="Blank = global KB"
                />
              </Field>
            </div>
          </details>
          <div className="grid md:grid-cols-3 gap-5">
            <Field label="Language">
              <Select
                value={edit.language}
                onChange={(v) => setF("language", v)}
                options={[{ value: "", label: "Auto-detect" }, ...LANGUAGES]}
              />
            </Field>
            <Field label="Voice model">
              <Select
                value={edit.voiceModel}
                onChange={(v) => {
                  setF("voiceModel", v);
                  setF("voiceSpeaker", "");
                }}
                options={[
                  { value: "", label: "Use global voice" },
                  ...TTS_MODELS,
                ]}
              />
            </Field>
            <Field label="Voice speaker">
              <Select
                value={edit.voiceSpeaker}
                onChange={(v) => setF("voiceSpeaker", v)}
                options={
                  edit.voiceModel
                    ? [
                        { value: "", label: "— pick —" },
                        ...speakersFor(edit.voiceModel),
                      ]
                    : [{ value: "", label: "Use global voice" }]
                }
              />
            </Field>
          </div>
          <Field
            label={`Replace contact list (optional) — current: ${c.total}`}
            hint="Leave blank to keep the current list. Pasting a new list REPLACES all contacts and resets the campaign to draft."
          >
            <Textarea
              className="min-h-[110px] font-mono text-[13px]"
              placeholder={"+919812345678,Ravi\n+919898989898,Anita"}
              value={edit.csv}
              onChange={(e) => setF("csv", e.target.value)}
            />
          </Field>
        </div>
      </Card>

      <Card title="Contacts">
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Phone</th>
                <th>Name</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>Call</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((ct: any) => (
                <tr key={ct.id}>
                  <td className="font-medium">{ct.phone}</td>
                  <td>{ct.name || "—"}</td>
                  <td>
                    <Badge tone={tone(ct.status) as any}>{ct.status}</Badge>
                    {ct.error && (
                      <span className="text-[var(--bad)] text-[11px] ml-2">
                        {ct.error}
                      </span>
                    )}
                  </td>
                  <td>{ct.attempts}</td>
                  <td>
                    {ct.room ? (
                      <Link
                        href={`/calls/${ct.room}`}
                        className="text-[var(--accent-2)] text-[13px]"
                      >
                        {ct.room}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="Run history"
        desc="Every Run / Re-run is kept with its own results & transcripts."
      >
        {(data.runs || []).length === 0 ? (
          <p className="text-[13px] text-[var(--muted)]">
            No runs yet — press Run to dial this campaign.
          </p>
        ) : (
          <div className="space-y-2">
            {(data.runs || []).map((run: any, i: number) => {
              const open =
                openRun === run.id || (openRun === null && i === 0);
              const when = run.startedAt
                ? new Date(run.startedAt).toLocaleString()
                : "—";
              return (
                <div
                  key={run.id}
                  className="rounded-lg border border-[var(--line-soft)] overflow-hidden"
                >
                  <button
                    onClick={() =>
                      setOpenRun(open ? "__none__" : run.id)
                    }
                    className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-[var(--line-soft)] transition-colors"
                  >
                    <span className="text-[13px]">{open ? "▾" : "▸"}</span>
                    <span className="font-semibold text-[14px]">
                      Run #{run.runNo}
                    </span>
                    <Badge tone={tone(run.status) as any}>
                      {run.status}
                    </Badge>
                    <span className="text-[12px] text-[var(--muted)]">
                      {when}
                    </span>
                    <span className="ml-auto text-[12px]">
                      <span className="text-[var(--accent)]">
                        ✓ {run.completed}
                      </span>
                      {"  "}
                      <span className="text-[var(--bad)]">
                        ✗ {run.failed}
                      </span>
                      <span className="text-[var(--muted)]">
                        {"  "}/ {run.total}
                      </span>
                    </span>
                  </button>
                  {open && (
                    <div className="tbl-wrap border-t border-[var(--line-soft)]">
                      <table className="tbl">
                        <thead>
                          <tr>
                            <th>Phone</th>
                            <th>Name</th>
                            <th>Status</th>
                            <th>Transcript</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(run.contacts || []).map((rc: any) => (
                            <tr key={rc.id}>
                              <td className="font-medium">{rc.phone}</td>
                              <td>{rc.name || "—"}</td>
                              <td>
                                <Badge tone={tone(rc.status) as any}>
                                  {rc.status}
                                </Badge>
                                {rc.error && (
                                  <span className="text-[var(--bad)] text-[11px] ml-2">
                                    {rc.error}
                                  </span>
                                )}
                              </td>
                              <td>
                                {rc.room ? (
                                  <Link
                                    href={`/calls/${rc.room}`}
                                    className="text-[var(--accent-2)] text-[13px]"
                                  >
                                    View →
                                  </Link>
                                ) : (
                                  "—"
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
