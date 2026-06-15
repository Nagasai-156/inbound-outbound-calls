"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Card,
  Button,
  Badge,
  EmptyState,
  Spinner,
  ConfirmDialog,
  useToast,
  PageHeader,
  Field,
  Input,
  Textarea,
} from "@/components/ui";

type Doc = {
  id: string;
  filename: string;
  sizeBytes: number;
  status: string;
  error: string;
  createdAt: string;
};

type KB = {
  id: string;
  name: string;
  description: string;
  docs: Doc[];
};

const docTone = (s: string) =>
  s === "indexed" ? "ok" : s === "failed" ? "bad" : s === "ingesting" ? "info" : "warn";

export default function KbDetailPage({ params }: { params: { id: string } }) {
  const toast = useToast();
  const kbId = params.id;
  const [kb, setKb] = useState<KB | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<"file" | "text">("file");
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");

  const load = () =>
    fetch(`/api/knowledge-bases/${kbId}`)
      .then((r) => r.ok ? r.json() : { kb: null })
      .then((d) => d.kb && setKb(d.kb))
      .catch(() => {});

  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, [kbId]);

  async function upload(files: FileList | null) {
    if (!files || !files.length) return;
    setBusy(true);
    for (const f of Array.from(files)) {
      const fd = new FormData();
      fd.append("file", f);
      const r = await fetch(`/api/kb?kbId=${encodeURIComponent(kbId)}`, {
        method: "POST",
        body: fd,
      });
      toast(r.ok ? `Ingesting ${f.name}…` : `Failed: ${f.name}`, r.ok ? "ok" : "bad");
    }
    setBusy(false);
    if (fileRef.current) fileRef.current.value = "";
    load();
  }

  async function addText() {
    if (text.trim().length < 5) return toast("Paste some text first", "bad");
    setBusy(true);
    const r = await fetch("/api/kb/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title.trim() || "Pasted note", text, kb_id: kbId }),
    });
    setBusy(false);
    if (r.ok) {
      toast("Text ingested", "ok");
      setTitle(""); setText("");
      load();
    } else {
      const j = await r.json().catch(() => ({}));
      toast(j.detail || j.error || "Ingest failed", "bad");
    }
  }

  async function del(id: string) {
    await fetch(`/api/kb?id=${id}`, { method: "DELETE" });
    toast("Removed", "ok");
    load();
  }

  if (!kb) return <div className="py-12 flex justify-center"><Spinner /></div>;

  return (
    <div className="space-y-5">
      <ConfirmDialog
        open={!!confirmDel}
        title="Remove document?"
        desc="Removes the document and its embeddings. The agent will no longer answer from it."
        confirmLabel="Remove"
        tone="danger"
        onConfirm={() => confirmDel && del(confirmDel)}
        onCancel={() => setConfirmDel(null)}
      />

      <PageHeader
        title={kb.name}
        subtitle={kb.description || "Manage documents in this knowledge base."}
        actions={
          <Link href="/knowledge">
            <Button>← All KBs</Button>
          </Link>
        }
      />

      <Card title="Add documents">
        <div className="flex gap-2 mb-4">
          <Button variant={mode === "file" ? "primary" : "default"} className="btn-sm" onClick={() => setMode("file")}>
            Upload files
          </Button>
          <Button variant={mode === "text" ? "primary" : "default"} className="btn-sm" onClick={() => setMode("text")}>
            Paste text
          </Button>
        </div>

        {mode === "file" ? (
          <div
            className="border border-dashed border-[var(--line)] rounded-xl p-10 text-center cursor-pointer hover:border-[var(--accent)] transition-colors"
            onClick={() => fileRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files); }}
          >
            {busy ? (
              <div className="flex items-center justify-center gap-2 text-[var(--muted)]"><Spinner /> Uploading &amp; ingesting…</div>
            ) : (
              <>
                <span className="inline-grid place-items-center w-12 h-12 rounded-xl bg-[var(--accent-soft)] text-[var(--accent)] mb-3">
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
                  </svg>
                </span>
                <div className="font-medium">Drop files here or click to browse</div>
                <div className="text-[12px] text-[var(--muted)] mt-1">.pdf .txt .md .docx .json .html</div>
              </>
            )}
            <input ref={fileRef} type="file" multiple hidden accept=".pdf,.txt,.md,.docx,.json,.html" onChange={(e) => upload(e.target.files)} />
          </div>
        ) : (
          <div className="space-y-4">
            <Field label="Title">
              <Input placeholder="e.g. Pricing FAQ" value={title} onChange={(e) => setTitle(e.target.value)} />
            </Field>
            <Field label="Knowledge text" hint="Paste FAQs, policies, or any text. The agent will only answer from this.">
              <Textarea className="min-h-[220px] font-mono text-[13px]" placeholder="Refunds are processed in 5–7 days…" value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
            <Button variant="primary" onClick={addText} disabled={busy || text.trim().length < 5}>
              {busy ? <Spinner /> : "Add to this KB"}
            </Button>
          </div>
        )}
      </Card>

      <Card title={`Documents (${kb.docs.length})`}>
        {kb.docs.length === 0 ? (
          <EmptyState title="No documents yet" desc="Upload files or paste text above." />
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr><th>File</th><th>Size</th><th>Status</th><th></th></tr>
              </thead>
              <tbody>
                {kb.docs.map((d) => (
                  <tr key={d.id}>
                    <td className="font-medium">{d.filename}</td>
                    <td>{(d.sizeBytes / 1024).toFixed(0)} KB</td>
                    <td>
                      <Badge tone={docTone(d.status) as any}>{d.status}</Badge>
                      {d.error && <span className="text-[var(--bad)] text-[11px] ml-2">{d.error}</span>}
                    </td>
                    <td className="text-right">
                      <Button variant="danger" className="btn-sm" onClick={() => setConfirmDel(d.id)}>Remove</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="text-[12px] text-[var(--muted)]">
        KB ID: <code className="font-mono">{kbId}</code> — use this when assigning to campaigns via API.
      </div>
    </div>
  );
}
