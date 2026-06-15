"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
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
} from "@/components/ui";

type KB = {
  id: string;
  name: string;
  description: string;
  createdAt: string;
  _count: { docs: number };
};

export default function KnowledgePage() {
  const toast = useToast();
  const router = useRouter();
  const [kbs, setKbs] = useState<KB[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState<KB | null>(null);

  const load = () =>
    fetch("/api/knowledge-bases")
      .then((r) => r.ok ? r.json() : { kbs: [] })
      .then((d) => setKbs(d.kbs || []))
      .catch(() => setKbs([]));

  useEffect(() => { load(); }, []);

  async function create() {
    if (!newName.trim()) return toast("Name required", "bad");
    setBusy(true);
    const r = await fetch("/api/knowledge-bases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName, description: newDesc }),
    });
    setBusy(false);
    if (r.ok) {
      const { kb } = await r.json();
      toast(`Created "${kb.name}"`, "ok");
      setNewName(""); setNewDesc(""); setCreating(false);
      router.push(`/knowledge/${kb.id}`);
    } else {
      toast("Failed to create", "bad");
    }
  }

  async function del(kb: KB) {
    const r = await fetch(`/api/knowledge-bases/${kb.id}`, { method: "DELETE" });
    if (r.ok) { toast("Deleted", "ok"); load(); }
    else toast("Delete failed", "bad");
  }

  return (
    <div className="space-y-5">
      <ConfirmDialog
        open={!!confirmDel}
        title={`Delete "${confirmDel?.name}"?`}
        desc="All documents in this KB will be unlinked. The agent will no longer use them."
        confirmLabel="Delete KB"
        tone="danger"
        onConfirm={() => confirmDel && del(confirmDel)}
        onCancel={() => setConfirmDel(null)}
      />

      <PageHeader
        title="Knowledge Bases"
        subtitle="Each KB is a named collection of documents. Assign a KB to a campaign or call — the agent answers grounded in that KB only."
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 5v14M5 12h14" />
            </svg>
            New KB
          </Button>
        }
      />

      {creating && (
        <Card title="New knowledge base">
          <div className="grid md:grid-cols-2 gap-4">
            <Field label="Name">
              <Input
                placeholder="e.g. Dental pricing & FAQs"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
              />
            </Field>
            <Field label="Description (optional)">
              <Input
                placeholder="What this KB covers"
                value={newDesc}
                onChange={(e) => setNewDesc(e.target.value)}
              />
            </Field>
          </div>
          <div className="flex gap-2 mt-4">
            <Button variant="primary" onClick={create} disabled={busy || !newName.trim()}>
              {busy ? <Spinner /> : "Create & add docs"}
            </Button>
            <Button onClick={() => { setCreating(false); setNewName(""); setNewDesc(""); }}>
              Cancel
            </Button>
          </div>
        </Card>
      )}

      {!kbs ? (
        <div className="py-12 flex justify-center"><Spinner /></div>
      ) : kbs.length === 0 ? (
        <EmptyState
          title="No knowledge bases yet"
          desc="Create one to upload documents. Assign it to campaigns so the agent only reads relevant knowledge per call."
          action={<Button variant="primary" onClick={() => setCreating(true)}>Create first KB</Button>}
        />
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
          {kbs.map((kb) => (
            <div
              key={kb.id}
              className="card cursor-pointer hover:border-[var(--accent)] hover:shadow-[var(--shadow)] transition-all"
              onClick={() => router.push(`/knowledge/${kb.id}`)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-semibold text-[15px] truncate">{kb.name}</div>
                  {kb.description && (
                    <div className="text-[12.5px] text-[var(--muted)] mt-0.5 line-clamp-2">{kb.description}</div>
                  )}
                </div>
                <Badge tone={kb._count.docs > 0 ? "ok" : "default"}>
                  {kb._count.docs} doc{kb._count.docs !== 1 ? "s" : ""}
                </Badge>
              </div>
              <div className="flex items-center justify-between mt-4">
                <span className="text-[11.5px] text-[var(--faint)]">
                  {new Date(kb.createdAt).toLocaleDateString()}
                </span>
                <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                  <Button
                    className="btn-sm"
                    onClick={() => router.push(`/knowledge/${kb.id}`)}
                  >
                    Manage docs
                  </Button>
                  <Button
                    variant="danger"
                    className="btn-sm"
                    onClick={() => setConfirmDel(kb)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
