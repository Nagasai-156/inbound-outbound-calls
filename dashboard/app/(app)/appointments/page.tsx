"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  Card,
  Field,
  Input,
  Select,
  Button,
  Badge,
  Spinner,
  EmptyState,
  ConfirmDialog,
  PageHeader,
  useToast,
} from "@/components/ui";

type Slot = {
  time: string;
  status: "available" | "booked";
  id?: string;
  name?: string;
  phone?: string;
  reason?: string;
  source?: string;
  partySize?: number;
  serviceType?: string;
  notes?: string;
};

type Grid = { openHour: number; closeHour: number; slotMin: number };

const today = () => new Date().toISOString().slice(0, 10);

export default function AppointmentsPage() {
  const toast = useToast();
  const [date, setDate] = useState(today());
  const [data, setData] = useState<{
    closed: boolean;
    slots: Slot[];
    grid?: Grid;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [time, setTime] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("");
  const [partySize, setPartySize] = useState<string>("");
  const [serviceType, setServiceType] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmCancel, setConfirmCancel] = useState<string | null>(null);
  const [dateLoading, setDateLoading] = useState(false);
  // Inline hours editor — same backend as Settings; saves to AgentConfig
  // and the next call (inbound/outbound) picks up the new grid within 5s.
  const [editHours, setEditHours] = useState(false);
  const [hOpen, setHOpen] = useState<string>("");
  const [hClose, setHClose] = useState<string>("");
  const [hSlot, setHSlot] = useState<string>("");
  const [hDays, setHDays] = useState<string>("");
  const [savingHours, setSavingHours] = useState(false);

  const load = useCallback(async (): Promise<void> => {
    const r = await fetch(`/api/appointments?date=${date}`, {
      cache: "no-store",
    });
    if (r.ok) setData(await r.json());
  }, [date]);

  useEffect(() => {
    setData(null);
    setDateLoading(true);
    load().finally(() => setDateLoading(false));
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [load]);

  const free = (data?.slots || []).filter((s) => s.status === "available");
  const bookedCount = (data?.slots || []).filter(
    (s) => s.status === "booked"
  ).length;

  async function book() {
    if (!time) return toast("Pick a free slot", "bad");
    setBusy(true);
    const r = await fetch("/api/appointments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date, time, name, phone, reason,
        partySize: partySize ? Number(partySize) : 0,
        serviceType, notes,
      }),
    });
    const j = await r.json().catch(() => ({}));
    setBusy(false);
    if (r.ok) {
      toast(`Booked ${date} ${time}`, "ok");
      setName("");
      setPhone("");
      setReason("");
      setPartySize("");
      setServiceType("");
      setNotes("");
      setTime("");
      load();
    } else toast(j.error || "Booking failed", "bad");
  }

  // Pre-fill the dialog with the CURRENT values the page is showing,
  // then open. Fetched from /api/config so it's authoritative (matches
  // what Settings would show).
  async function openEditHours() {
    try {
      const r = await fetch("/api/config", { cache: "no-store" });
      const j = await r.json().catch(() => ({}));
      const c = j.config || {};
      setHOpen(String(c.apptOpenHour ?? 9));
      setHClose(String(c.apptCloseHour ?? 18));
      setHSlot(String(c.apptSlotMin ?? 30));
      setHDays(String(c.apptOpenWeekdays ?? "0,1,2,3,4,5"));
    } catch {
      // Fall back to the grid we already have on screen — better than
      // opening a blank dialog.
      if (data?.grid) {
        setHOpen(String(data.grid.openHour));
        setHClose(String(data.grid.closeHour));
        setHSlot(String(data.grid.slotMin));
      }
    }
    setEditHours(true);
  }

  async function saveHours() {
    const o = parseInt(hOpen, 10);
    const c = parseInt(hClose, 10);
    const s = parseInt(hSlot, 10);
    const days = hDays
      .split(",")
      .map((x) => x.trim())
      .filter((x) => /^[0-6]$/.test(x));
    if (
      !Number.isFinite(o) || o < 0 || o > 23 ||
      !Number.isFinite(c) || c < 1 || c > 24 || c <= o ||
      !Number.isFinite(s) || s <= 0 ||
      days.length === 0
    ) {
      toast(
        "Check values: open 0-23, close 1-24 (must be > open), slot > 0, days 0-6 comma-separated.",
        "bad"
      );
      return;
    }
    setSavingHours(true);
    const r = await fetch("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        apptOpenHour: o,
        apptCloseHour: c,
        apptSlotMin: s,
        apptOpenWeekdays: days.join(","),
      }),
    });
    setSavingHours(false);
    if (r.ok) {
      toast("Hours saved — next call uses these (~5s).", "ok");
      setEditHours(false);
      load();
    } else {
      const j = await r.json().catch(() => ({}));
      toast(j.error || "Save failed", "bad");
    }
  }

  async function cancel(id: string) {
    const r = await fetch(`/api/appointments?id=${id}`, { method: "DELETE" });
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      toast((j.error as string) || "Cancel failed", "bad");
      return;
    }
    toast("Appointment cancelled", "ok");
    load();
  }

  return (
    <div className="space-y-5">
      <ConfirmDialog
        open={!!confirmCancel}
        title="Cancel appointment?"
        desc="This frees the slot and removes the booking."
        confirmLabel="Cancel booking"
        tone="danger"
        onConfirm={() => confirmCancel && cancel(confirmCancel)}
        onCancel={() => setConfirmCancel(null)}
      />
      {editHours && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
          <div
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => !savingHours && setEditHours(false)}
          />
          <div className="relative card !p-7 w-full max-w-lg shadow-2xl animate-[slideIn_.15s_ease]">
            <div className="font-semibold text-[16px] mb-1">
              Edit appointment hours
            </div>
            <p className="text-[13px] text-[var(--muted)] leading-relaxed mb-5">
              The agent reads this grid for every call. Changes apply to the
              next call within ~5 seconds — no redeploy.
            </p>
            <div className="grid sm:grid-cols-3 gap-4">
              <Field label="Open hour" hint="0-23 (24h). e.g. 9 = 9 AM, 6 = 6 AM.">
                <Input
                  type="number"
                  min={0}
                  max={23}
                  value={hOpen}
                  onChange={(e) => setHOpen(e.target.value)}
                />
              </Field>
              <Field label="Close hour" hint="1-24 (exclusive). Must be > open.">
                <Input
                  type="number"
                  min={1}
                  max={24}
                  value={hClose}
                  onChange={(e) => setHClose(e.target.value)}
                />
              </Field>
              <Field label="Slot (min)" hint="e.g. 30, 60.">
                <Input
                  type="number"
                  min={5}
                  max={120}
                  value={hSlot}
                  onChange={(e) => setHSlot(e.target.value)}
                />
              </Field>
            </div>
            <div className="mt-4">
              <Field
                label="Open weekdays"
                hint="Mon=0 … Sun=6, comma-separated. Default Mon-Sat = 0,1,2,3,4,5. 7-day business = 0,1,2,3,4,5,6."
              >
                <Input
                  value={hDays}
                  onChange={(e) => setHDays(e.target.value)}
                  placeholder="0,1,2,3,4,5"
                />
              </Field>
            </div>
            <div className="flex items-center justify-between gap-2 mt-6">
              <Link
                href="/settings"
                className="text-[13px] text-[var(--muted)] hover:text-[var(--txt)] underline-offset-2 hover:underline"
              >
                Open full Settings →
              </Link>
              <div className="flex gap-2">
                <Button
                  onClick={() => setEditHours(false)}
                  disabled={savingHours}
                >
                  Cancel
                </Button>
                <Button
                  variant="primary"
                  onClick={saveHours}
                  disabled={savingHours}
                >
                  {savingHours ? <Spinner /> : null} Save
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
      <PageHeader
        title="Appointments"
        subtitle="Calendar of slots. The phone agent reads free slots from here before offering a time, and writes a row when it books one. You can also book manually."
      />

      <div className="flex flex-wrap items-end gap-4">
        <Field label="Date">
          <Input
            type="date"
            value={date}
            min={today()}
            onChange={(e) => setDate(e.target.value)}
            className="w-[180px]"
          />
        </Field>
        <div className="flex gap-2 pb-1">
          {dateLoading && !data ? (
            <Spinner className="w-4 h-4" />
          ) : data ? (
            <>
              <Badge tone="ok">{free.length} free</Badge>
              <Badge tone={bookedCount ? "info" : "default"}>{bookedCount} booked</Badge>
              {data.closed && <Badge tone="warn">closed this day</Badge>}
            </>
          ) : null}
        </div>
      </div>

      <Card title="Book a slot manually">
        <div className="grid md:grid-cols-4 gap-4">
          <Field label="Time slot">
            <Select
              value={time}
              onChange={setTime}
              options={[
                { value: "", label: "— pick a free slot —" },
                ...free.map((s) => ({ value: s.time, label: s.time })),
              ]}
            />
          </Field>
          <Field label="Name">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Customer name"
            />
          </Field>
          <Field label="Phone">
            <Input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="+9198…"
            />
          </Field>
          <Field label="Reason / purpose">
            <Input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. checkup, table for 4, haircut & color…"
            />
          </Field>
        </div>
        <div className="grid md:grid-cols-3 gap-4 mt-4">
          <Field
            label="Party size"
            hint="Restaurants / hotels / events. Leave blank for 1-on-1."
          >
            <Input
              type="number"
              min={0}
              value={partySize}
              onChange={(e) => setPartySize(e.target.value)}
              placeholder="e.g. 4"
            />
          </Field>
          <Field
            label="Service type"
            hint="Salon / clinic / spa — which service was booked."
          >
            <Input
              value={serviceType}
              onChange={(e) => setServiceType(e.target.value)}
              placeholder="e.g. haircut, consultation"
            />
          </Field>
          <Field
            label="Notes"
            hint="Free-form special instructions."
          >
            <Input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. window seat, vegan menu"
            />
          </Field>
        </div>
        <div className="mt-4">
          <Button
            variant="primary"
            onClick={book}
            disabled={busy || !time}
          >
            {busy ? <Spinner /> : null} Book appointment
          </Button>
        </div>
      </Card>

      <Card
        title={`Slots — ${date}`}
        desc={
          data?.grid
            ? `${String(data.grid.openHour).padStart(2, "0")}:00 – ${String(
                data.grid.closeHour
              ).padStart(2, "0")}:00 · ${data.grid.slotMin}-min slots · live from Settings`
            : undefined
        }
        actions={
          <Button variant="ghost" onClick={openEditHours}>
            Edit hours
          </Button>
        }
      >
        {!data ? (
          <div className="py-10 flex justify-center">
            <Spinner />
          </div>
        ) : data.slots.length === 0 ? (
          <EmptyState
            title="No slots"
            desc="Closed that day, or working hours not configured."
          />
        ) : (
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Status</th>
                  <th>Booked by</th>
                  <th>Reason</th>
                  <th>Service / party / notes</th>
                  <th>Source</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.slots.map((s) => {
                  const extras = [
                    s.serviceType,
                    s.partySize ? `${s.partySize} pax` : "",
                    s.notes,
                  ].filter(Boolean);
                  return (
                    <tr key={s.time}>
                      <td className="font-medium tabular-nums">{s.time}</td>
                      <td>
                        <Badge tone={s.status === "booked" ? "info" : "ok"}>
                          {s.status}
                        </Badge>
                      </td>
                      <td>
                        {s.name || (s.status === "booked" ? "—" : "")}
                        {s.phone ? (
                          <span className="text-[var(--muted)] text-[12px]">
                            {" "}
                            · {s.phone}
                          </span>
                        ) : null}
                      </td>
                      <td>{s.reason || ""}</td>
                      <td className="text-[12px] text-[var(--muted)]">
                        {extras.length ? extras.join(" · ") : ""}
                      </td>
                      <td>
                        {s.source ? (
                          <Badge
                            tone={s.source === "call" ? "info" : "default"}
                          >
                            {s.source}
                          </Badge>
                        ) : (
                          ""
                        )}
                      </td>
                      <td className="text-right">
                        {s.status === "booked" && s.id && (
                          <Button
                            variant="danger"
                            className="btn-sm"
                            onClick={() => setConfirmCancel(s.id!)}
                          >
                            Cancel
                          </Button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
