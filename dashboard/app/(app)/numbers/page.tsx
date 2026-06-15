"use client";

import { useEffect, useState } from "react";
import {
  Card,
  Field,
  Input,
  Check,
  Button,
  Badge,
  EmptyState,
  Spinner,
  ConfirmDialog,
  useToast,
  PageHeader,
} from "@/components/ui";

type Num = {
  id: string;
  e164: string;
  label: string;
  inbound: boolean;
  outbound: boolean;
  active: boolean;
};

export default function NumbersPage() {
  const toast = useToast();
  const [list, setList] = useState<Num[] | null>(null);
  const [e164, setE164] = useState("");
  const [label, setLabel] = useState("");
  const [inbound, setInbound] = useState(true);
  const [outbound, setOutbound] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);

  const load = () =>
    fetch("/api/numbers")
      .then((r) => r.ok ? r.json() : { numbers: [] })
      .then((d) => setList(d.numbers || []))
      .catch(() => {});
  useEffect(() => {
    load();
  }, []);

  async function add() {
    if (!inbound && !outbound) {
      toast("Pick at least one role: Inbound and/or Outbound", "bad");
      return;
    }
    setBusy(true);
    const r = await fetch("/api/numbers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ e164, label, inbound, outbound }),
    });
    setBusy(false);
    const j = await r.json().catch(() => ({}));
    if (r.ok) {
      toast("Number added", "ok");
      setE164("");
      setLabel("");
      setInbound(true);
      setOutbound(true);
      load();
    } else toast(j.error || "Failed", "bad");
  }

  async function del(id: string) {
    await fetch(`/api/numbers?id=${id}`, { method: "DELETE" });
    toast("Removed", "info");
    load();
  }

  return (
    <div className="space-y-5">
      <ConfirmDialog
        open={!!confirmDel}
        title="Remove number?"
        desc="This removes the number from your account. Campaigns using it as caller-ID will need to be updated."
        confirmLabel="Remove"
        tone="danger"
        onConfirm={() => confirmDel && del(confirmDel)}
        onCancel={() => setConfirmDel(null)}
      />
      <PageHeader
        title="Phone Numbers"
        subtitle="A number can be used for inbound (rings into the agent), outbound (caller-ID for calls & campaigns), or BOTH."
      />

      <Card title="Add a number">
        <div className="grid md:grid-cols-2 gap-4">
          <Field label="Phone number (E.164)">
            <Input
              placeholder="+9198XXXXXXXX"
              value={e164}
              onChange={(e) => setE164(e.target.value)}
            />
          </Field>
          <Field label="Label (optional)">
            <Input
              placeholder="Sales line"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </Field>
        </div>
        <div className="flex flex-wrap items-center gap-6 mt-5">
          <span className="label !mb-0">Roles:</span>
          <Check
            checked={inbound}
            onChange={setInbound}
            label="Inbound (receives calls)"
          />
          <Check
            checked={outbound}
            onChange={setOutbound}
            label="Outbound (caller-ID)"
          />
          <Button
            variant="primary"
            onClick={add}
            disabled={busy || !e164}
            className="ml-auto"
          >
            {busy ? <Spinner /> : "Add number"}
          </Button>
        </div>
      </Card>

      <Card title="Your numbers">
        {!list ? (
          <Spinner />
        ) : list.length === 0 ? (
          <EmptyState
            icon="☎"
            title="No numbers yet"
            desc="Add a caller-ID number to place outbound calls."
          />
        ) : (
          <div className="tbl-wrap"><table className="tbl">
            <thead>
              <tr>
                <th>Number</th>
                <th>Label</th>
                <th>Roles</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.map((n) => (
                <tr key={n.id}>
                  <td className="font-medium">{n.e164}</td>
                  <td>{n.label || "—"}</td>
                  <td>
                    <div className="flex gap-1.5">
                      {n.inbound && <Badge tone="info">Inbound</Badge>}
                      {n.outbound && <Badge tone="info">Outbound</Badge>}
                      {!n.inbound && !n.outbound && (
                        <Badge tone="bad">none</Badge>
                      )}
                    </div>
                  </td>
                  <td>
                    <Badge tone={n.active ? "ok" : "bad"}>
                      {n.active ? "active" : "inactive"}
                    </Badge>
                  </td>
                  <td className="text-right">
                    <Button
                      variant="danger"
                      className="btn-sm"
                      onClick={() => setConfirmDel(n.id)}
                    >
                      Remove
                    </Button>
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
