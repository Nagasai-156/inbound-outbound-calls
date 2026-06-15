import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

// Reads the slot grid LIVE from AgentConfig (the single source of truth,
// shared with the Python agent via src/db.py::_refresh_appt_grid). When
// the operator changes hours from Settings, the next /appointments GET
// reflects them immediately — no redeploy, no hardcoded drift.
// Mon=0..Sun=6 to match Python (different from JS getDay() which is
// Sun=0..Sat=6), so we convert in the closed-day check below.
type ApptGrid = {
  openHour: number;
  closeHour: number;
  slotMin: number;
  openWeekdaysPy: Set<number>; // Mon=0..Sun=6
};

async function loadApptGrid(): Promise<ApptGrid> {
  const c = await prisma.agentConfig.findUnique({ where: { id: "default" } });
  const open = c?.apptOpenHour ?? 9;
  const close = c?.apptCloseHour ?? 18;
  const slot = c?.apptSlotMin ?? 30;
  const wdRaw = c?.apptOpenWeekdays ?? "0,1,2,3,4,5";
  const days = new Set<number>(
    wdRaw
      .split(",")
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => Number.isFinite(n) && n >= 0 && n <= 6)
  );
  // Sanity: if config is broken, fall back to a working 9-6 grid so the
  // page never returns an empty / impossible slot list.
  if (close <= open || slot <= 0 || days.size === 0) {
    return {
      openHour: 9,
      closeHour: 18,
      slotMin: 30,
      openWeekdaysPy: new Set([0, 1, 2, 3, 4, 5]),
    };
  }
  return {
    openHour: open,
    closeHour: close,
    slotMin: slot,
    openWeekdaysPy: days,
  };
}

function allSlots(g: ApptGrid): string[] {
  const out: string[] = [];
  for (let t = g.openHour * 60; t < g.closeHour * 60; t += g.slotMin) {
    out.push(
      `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(
        t % 60
      ).padStart(2, "0")}`
    );
  }
  return out;
}

async function auth() {
  const s = createClient();
  const {
    data: { user },
  } = await s.auth.getUser();
  return user;
}

// GET ?date=YYYY-MM-DD -> the full slot grid for that day with who (if
// anyone) is booked in each slot.
export async function GET(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const date =
    new URL(req.url).searchParams.get("date") ||
    new Date().toISOString().slice(0, 10);

  const grid = await loadApptGrid();
  const rows = await prisma.appointment.findMany({
    where: { date },
    orderBy: { time: "asc" },
  });
  const byTime = new Map(
    rows.filter((r) => r.status === "booked").map((r) => [r.time, r])
  );
  // JS getDay(): Sun=0..Sat=6. Python uses Mon=0..Sun=6. Convert.
  const jsDay = new Date(date + "T00:00:00").getDay();
  const pyDay = (jsDay + 6) % 7;
  const closed = !grid.openWeekdaysPy.has(pyDay);

  const slots = allSlots(grid).map((time) => {
    const b = byTime.get(time);
    return b
      ? {
          time,
          status: "booked" as const,
          id: b.id,
          name: b.name,
          phone: b.phone,
          reason: b.reason,
          source: b.source,
          partySize: b.partySize,
          serviceType: b.serviceType,
          notes: b.notes,
        }
      : { time, status: "available" as const };
  });

  return NextResponse.json({
    date,
    closed,
    slots,
    all: rows,
    grid: {
      openHour: grid.openHour,
      closeHour: grid.closeHour,
      slotMin: grid.slotMin,
    },
  });
}

// POST { date, time, name, phone, reason } -> manual booking.
export async function POST(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const b = await req.json();
  const date = String(b.date || "").trim();
  const time = String(b.time || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^\d{2}:\d{2}$/.test(time))
    return NextResponse.json(
      { error: "date (YYYY-MM-DD) and time (HH:MM) required" },
      { status: 400 }
    );
  const grid = await loadApptGrid();
  if (!allSlots(grid).includes(time))
    return NextResponse.json(
      { error: "not a valid slot time" },
      { status: 400 }
    );
  const clash = await prisma.appointment.findFirst({
    where: { date, time, status: "booked" },
  });
  if (clash)
    return NextResponse.json(
      { error: "that slot is already booked" },
      { status: 409 }
    );
  // Optional generic fields (partySize/serviceType/notes) — passed
  // through when the operator filled them; safe defaults otherwise so
  // any-shape business uses this form without per-business code change.
  const partySize = Number.isFinite(Number(b.partySize))
    ? Math.max(0, Math.floor(Number(b.partySize)))
    : 0;
  const appt = await prisma.appointment.create({
    data: {
      date,
      time,
      name: String(b.name || "").slice(0, 120),
      phone: String(b.phone || "").slice(0, 20),
      reason: String(b.reason || "").slice(0, 120),
      status: "booked",
      source: "manual",
      partySize,
      serviceType: String(b.serviceType || "").slice(0, 60),
      notes: String(b.notes || "").slice(0, 500),
    },
  });
  return NextResponse.json({ appointment: appt });
}

// DELETE ?id= -> cancel (keeps the row, frees the slot).
export async function DELETE(req: Request) {
  if (!(await auth()))
    return NextResponse.json({ error: "unauth" }, { status: 401 });
  const id = new URL(req.url).searchParams.get("id");
  if (!id)
    return NextResponse.json({ error: "id required" }, { status: 400 });
  // Verify the row exists before "cancelling" so the dashboard cancel
  // button can't false-success on a stale id (also returns 404 cleanly
  // instead of Prisma's unhandled NotFoundError → opaque 500).
  const existing = await prisma.appointment.findUnique({ where: { id } });
  if (!existing)
    return NextResponse.json({ error: "not found" }, { status: 404 });
  if (existing.status === "cancelled")
    return NextResponse.json({ error: "already cancelled" }, { status: 409 });
  await prisma.appointment.update({
    where: { id },
    data: { status: "cancelled" },
  });
  return NextResponse.json({ ok: true });
}
