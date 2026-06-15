"use client";

import { useEffect, useState } from "react";
import {
  Card,
  EmptyState,
  Spinner,
  ConfirmDialog,
  useToast,
  PageHeader,
  Badge,
} from "@/components/ui";
import { LANGUAGES, speakersFor } from "@/lib/options";

type VoiceConfig = {
  id: string;
  name: string;
  defaultLanguage: string;
  ttsModel: string;
  ttsSpeakerTe: string;
  ttsSpeakerHi: string;
  ttsSpeakerEn: string;
  ttsPace: number;
  useCaseType: string;
  businessDescription: string;
  llmModel: string;
  createdAt: string;
};

export default function ProfilesPage() {
  const toast = useToast();
  const [configs, setConfigs] = useState<VoiceConfig[] | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const load = () =>
    fetch("/api/profiles")
      .then((r) => r.ok ? r.json() : { profiles: [] })
      .then((d) => setConfigs(d.profiles || []))
      .catch(() => setConfigs([]));

  useEffect(() => { load(); }, []);

  async function del(id: string) {
    const r = await fetch(`/api/profiles/${id}`, { method: "DELETE" });
    if (r.ok) { toast("Deleted", "ok"); load(); }
    else toast("Failed", "bad");
  }

  async function apply(id: string, name: string) {
    const r = await fetch(`/api/profiles/${id}`, { method: "POST" });
    if (r.ok) toast(`Applied "${name}" — takes effect on the next call`, "ok");
    else toast("Apply failed", "bad");
  }

  const langLabel = (v: string) => LANGUAGES.find((l) => l.value === v)?.label?.split(" ")[0] ?? v;
  const speakerLabel = (c: VoiceConfig) => {
    const spk = c.ttsSpeakerTe || c.ttsSpeakerHi || c.ttsSpeakerEn;
    if (!spk) return "";
    return speakersFor(c.ttsModel).find((s) => s.value === spk)?.label?.split(" — ")[0] ?? spk;
  };

  return (
    <div className="space-y-5 max-w-3xl">
      <ConfirmDialog
        open={!!confirmDelete}
        title="Delete voice config?"
        desc="This config will be removed. Campaigns and calls already placed are not affected."
        confirmLabel="Delete"
        tone="danger"
        onConfirm={() => confirmDelete && del(confirmDelete)}
        onCancel={() => setConfirmDelete(null)}
      />

      <PageHeader
        title="Voice Configs"
        subtitle={`Saved snapshots of Voice & Agent settings. To create one: go to Voice & Agent, configure everything, then click "Save as config…" at the bottom.`}
      />

      <Card title="Saved configs">
        {!configs ? (
          <Spinner />
        ) : configs.length === 0 ? (
          <EmptyState
            title="No configs saved yet"
            desc={`Go to Voice & Agent, set everything up, then click "Save as config…" at the bottom of the page.`}
          />
        ) : (
          <div className="tbl-wrap"><table className="tbl">
            <thead>
              <tr>
                <th>Name</th>
                <th>Language</th>
                <th>Speaker</th>
                <th>Use-case</th>
                <th>LLM</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {configs.map((c) => (
                <tr key={c.id}>
                  <td className="font-medium">{c.name}</td>
                  <td className="text-[var(--muted)]">{langLabel(c.defaultLanguage)}</td>
                  <td className="text-[var(--muted)]">{speakerLabel(c) || "—"}</td>
                  <td>
                    {c.useCaseType && c.useCaseType !== "custom"
                      ? <Badge tone="info">{c.useCaseType}</Badge>
                      : <span className="text-[var(--muted)]">custom</span>}
                  </td>
                  <td className="text-[var(--muted)]">{c.llmModel}</td>
                  <td className="text-right">
                    <button
                      onClick={() => apply(c.id, c.name)}
                      className="text-[var(--accent)] text-[13px] hover:underline mr-4"
                    >
                      Apply to live config
                    </button>
                    <button
                      onClick={() => setConfirmDelete(c.id)}
                      className="text-[var(--bad)] text-[13px] hover:underline"
                    >
                      Delete
                    </button>
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
