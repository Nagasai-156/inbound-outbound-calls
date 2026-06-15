"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Card,
  Field,
  Input,
  Select,
  Textarea,
  Button,
  Badge,
  EmptyState,
  Spinner,
  ProgressBar,
  ConfirmDialog,
  useToast,
  PageHeader,
} from "@/components/ui";
import { LANGUAGES, TTS_MODELS, speakersFor, USE_CASES } from "@/lib/options";

type C = {
  id: string;
  name: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  createdAt: string;
};

const tone = (s: string) =>
  s === "running"
    ? "info"
    : s === "done"
      ? "ok"
      : s === "paused"
        ? "warn"
        : "default";

export default function CampaignsPage() {
  const toast = useToast();
  const [list, setList] = useState<C[] | null>(null);
  const [callerIds, setCallerIds] = useState<any[]>([]);
  const [name, setName] = useState("");
  const [callerId, setCallerId] = useState("");
  const [csv, setCsv] = useState("");
  const [language, setLanguage] = useState("");
  const [script, setScript] = useState("");
  const [voiceModel, setVoiceModel] = useState("");
  const [voiceSpeaker, setVoiceSpeaker] = useState("");
  const [useCaseType, setUseCaseType] = useState("custom");
  const [businessDescription, setBusinessDescription] = useState("");
  const [styleExamples, setStyleExamples] = useState("");
  const [kbVectorStoreId, setKbVectorStoreId] = useState("");
  const [kbId, setKbId] = useState("");
  const [kbOptions, setKbOptions] = useState<{ value: string; label: string }[]>([]);
  const [profileOptions, setProfileOptions] = useState<{ value: string; label: string }[]>([]);
  const [profileId, setProfileId] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmRerun, setConfirmRerun] = useState<string | null>(null);

  const load = () =>
    fetch("/api/campaigns")
      .then((r) => r.ok ? r.json() : { campaigns: [] })
      .then((d) => setList(d.campaigns || []))
      .catch(() => {});

  useEffect(() => {
    fetch("/api/knowledge-bases")
      .then((r) => r.ok ? r.json() : { kbs: [] })
      .then((d) => setKbOptions([
        { value: "", label: "— none (use global KB) —" },
        ...(d.kbs || []).map((kb: any) => ({ value: kb.id, label: kb.name })),
      ]))
      .catch(() => {});
    fetch("/api/profiles")
      .then((r) => r.ok ? r.json() : { profiles: [] })
      .then((d) => setProfileOptions([
        { value: "", label: "— manual —" },
        ...(d.profiles || []).map((p: any) => ({ value: p.id, label: p.name })),
      ]))
      .catch(() => {});
  }, []);

  useEffect(() => {
    load();
    fetch("/api/numbers")
      .then((r) => r.ok ? r.json() : { numbers: [] })
      .then((d) => {
        const cs = (d.numbers || [])
          .filter((n: any) => n.outbound && n.active)
          .map((n: any) => ({ value: n.e164, label: n.e164 }));
        setCallerIds(cs);
        if (cs[0]) setCallerId(cs[0].value);
      });
  }, []);

  async function applyProfile(id: string) {
    setProfileId(id);
    if (!id) return;
    const r = await fetch(`/api/profiles/${id}`);
    const j = await r.json().catch(() => ({}));
    if (!j.profile) return;
    const p = j.profile;
    if (p.defaultLanguage) setLanguage(p.defaultLanguage);
    if (p.ttsModel)        setVoiceModel(p.ttsModel);
    const spk = p.ttsSpeakerTe || p.ttsSpeakerHi || p.ttsSpeakerEn || "";
    if (spk)               setVoiceSpeaker(spk);
    if (p.useCaseType)          setUseCaseType(p.useCaseType);
    if (p.businessDescription)  setBusinessDescription(p.businessDescription);
    if (p.styleExamples)        setStyleExamples(p.styleExamples);
  }

  async function rerun(cid: string) {
    const r = await fetch(`/api/campaigns/${cid}/rerun`, { method: "POST" });
    const j = await r.json().catch(() => ({}));
    toast(
      r.ok
        ? `Re-running ${j.rearmed ?? ""} contact(s)…`
        : j.detail || j.error || "Could not re-run",
      r.ok ? "ok" : "bad"
    );
    load();
  }

  async function create() {
    setBusy(true);
    const r = await fetch("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        callerId,
        csv,
        language,
        script,
        voiceModel,
        voiceSpeaker,
        useCaseType,
        businessDescription,
        styleExamples,
        kbId,
        kbVectorStoreId: kbId,
      }),
    });
    const j = await r.json().catch(() => ({}));
    setBusy(false);
    if (r.ok) {
      toast(`Campaign created · ${j.campaign.total} contacts`, "ok");
      setName("");
      setCsv("");
      setScript("");
      load();
    } else toast(j.error || "Failed", "bad");
  }

  return (
    <div className="space-y-5">
      <ConfirmDialog
        open={!!confirmRerun}
        title="Re-run campaign?"
        desc="This resets all contacts and dials the whole list again."
        confirmLabel="Re-run"
        tone="primary"
        onConfirm={() => confirmRerun && rerun(confirmRerun)}
        onCancel={() => setConfirmRerun(null)}
      />
      <PageHeader
        title="Campaigns"
        subtitle="Bulk outbound calling. Paste or upload a list — one phone,name per line — then run it."
      />

      <Card title="New campaign">
        <div className="grid gap-5">
          <div className="grid md:grid-cols-2 gap-5">
            <Field
              label="Voice & Agent"
              hint="Pick a saved Voice & Agent config — auto-fills voice, language, persona, style for this campaign."
            >
              <Select
                value={profileId}
                onChange={applyProfile}
                options={profileOptions}
              />
            </Field>
            <Field
              label="Knowledge Base"
              hint="The agent only searches this KB during this campaign's calls."
            >
              <Select
                value={kbId}
                onChange={setKbId}
                options={kbOptions}
              />
            </Field>
          </div>

          <div className="grid md:grid-cols-2 gap-5">
            <Field label="Campaign name">
              <Input
                placeholder="Diwali offer — May batch"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Caller ID">
              <Select
                value={callerId}
                onChange={setCallerId}
                options={
                  callerIds.length
                    ? callerIds
                    : [{ value: "", label: "— add under Phone Numbers —" }]
                }
              />
            </Field>
          </div>
          <Field
            label="Use-case"
            hint="Drives the agent's scoped behaviour AND which tools it gets. Booking tools are exposed ONLY for appointment-family use-cases."
          >
            <Select
              value={useCaseType}
              onChange={setUseCaseType}
              options={USE_CASES}
            />
          </Field>
          <Field
            label="Call script / goal"
            hint="What this campaign's calls are about — overrides the global persona for THIS campaign only. e.g. appointment reminder, sales offer, survey…"
          >
            <Textarea
              className="min-h-[110px]"
              placeholder="You are calling to remind the patient of tomorrow's 11 AM appointment at Apollo Clinic. Confirm or reschedule. Be brief and warm. Max 2 short sentences."
              value={script}
              onChange={(e) => setScript(e.target.value)}
            />
          </Field>
          <details className="rounded-lg border border-[var(--line-soft)] p-3">
            <summary className="text-[13px] cursor-pointer text-[var(--muted)]">
              Advanced — per-campaign overrides (optional; blank = global)
            </summary>
            <div className="grid gap-4 mt-3">
              <Field label="Business description (this campaign)">
                <Textarea
                  className="min-h-[80px]"
                  placeholder="Blank = use global. Facts: services, hours, pricing/SMS policy."
                  value={businessDescription}
                  onChange={(e) => setBusinessDescription(e.target.value)}
                />
              </Field>
              <Field label="Style example (this campaign)">
                <Textarea
                  className="min-h-[80px]"
                  placeholder="Blank = neutral built-in. A short sample dialogue in YOUR domain/language."
                  value={styleExamples}
                  onChange={(e) => setStyleExamples(e.target.value)}
                />
              </Field>
            </div>
          </details>
          <div className="grid md:grid-cols-3 gap-5">
            <Field label="Language">
              <Select
                value={language}
                onChange={setLanguage}
                options={[
                  { value: "", label: "Auto-detect" },
                  ...LANGUAGES,
                ]}
              />
            </Field>
            <Field label="Voice model">
              <Select
                value={voiceModel}
                onChange={(v) => {
                  setVoiceModel(v);
                  setVoiceSpeaker("");
                }}
                options={[
                  { value: "", label: "Use global voice" },
                  ...TTS_MODELS,
                ]}
              />
            </Field>
            <Field label="Voice speaker">
              <Select
                value={voiceSpeaker}
                onChange={setVoiceSpeaker}
                options={
                  voiceModel
                    ? [
                        { value: "", label: "— pick —" },
                        ...speakersFor(voiceModel),
                      ]
                    : [{ value: "", label: "Use global voice" }]
                }
              />
            </Field>
          </div>
          <Field
            label="Contacts (CSV: phone,name per line)"
            hint="Upload a .csv/.txt or paste below"
          >
            <input
              type="file"
              accept=".csv,.txt"
              className="text-[13px] mb-2 block text-[var(--muted)]"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) f.text().then(setCsv);
              }}
            />
            <Textarea
              className="min-h-[140px] font-mono text-[13px]"
              placeholder={"+919812345678,Ravi\n+919898989898,Anita"}
              value={csv}
              onChange={(e) => setCsv(e.target.value)}
            />
          </Field>
          <div>
            <Button
              variant="primary"
              onClick={create}
              disabled={busy || !name || !csv.trim()}
            >
              {busy ? <Spinner /> : "Create campaign"}
            </Button>
          </div>
        </div>
      </Card>

      <Card title="All campaigns">
        {!list ? (
          <Spinner />
        ) : list.length === 0 ? (
          <EmptyState
            title="No campaigns yet"
            desc="Create one above to start bulk calling."
          />
        ) : (
          <div className="tbl-wrap"><table className="tbl">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th style={{ minWidth: 160 }}>Progress</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id}>
                  <td className="font-medium">{c.name}</td>
                  <td>
                    <Badge tone={tone(c.status) as any}>{c.status}</Badge>
                  </td>
                  <td style={{ minWidth: 160 }}>
                    <div className="space-y-1">
                      <ProgressBar
                        value={c.completed}
                        max={c.total}
                        tone={c.failed > 0 ? "warn" : "ok"}
                      />
                      <div className="text-[11px] text-[var(--muted)]">
                        {c.completed}/{c.total}
                        {c.failed > 0 && (
                          <span className="text-[var(--bad)] ml-2">{c.failed} failed</span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="text-right">
                    <div className="flex items-center gap-3 justify-end">
                      {c.status !== "running" &&
                        (c.status === "done" || c.completed > 0 || c.failed > 0) && (
                          <button
                            onClick={() => setConfirmRerun(c.id)}
                            className="text-[var(--accent-2)] text-[13px] font-medium hover:underline"
                          >
                            Re-run
                          </button>
                        )}
                      <Link href={`/campaigns/${c.id}`} className="text-[var(--accent-2)] text-[13px] hover:underline">
                        Open →
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </Card>
    </div>
  );
}
