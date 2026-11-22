// Big problems only, read-only from the runner DB: flight delay, offload, airline cancellation, price jump at booking,
// a request the clerk stopped on or missed, agent stopped. Everyday progress (quotes, bids, confirmations) never notifies.
import fs from "node:fs";
import path from "node:path";
import { mailAlert } from "./alert-rules";
import { parse } from "./data";
import { DB_PATH, getDb } from "./db";
import type { Notice } from "./notification-types";

const WINDOW_S = 24 * 3600;
const SILENT_S = 120;

type Row = Record<string, unknown>;
type Booking = { thread: number; ref: string; customer: string; lane: string };

function q(sql: string, ...args: unknown[]): Row[] {
  try { return getDb()?.prepare(sql).all(...args) ?? []; } catch { return []; } // a table the clerk has not created yet
}

let carriers: Set<string> | null = null;
function carrierSenders(): Set<string> {
  if (carriers) return carriers;
  try {
    const csv = fs.readFileSync(path.join(process.cwd(), "..", "kit", "start-kit", "carrier-list.csv"), "utf8");
    carriers = new Set(csv.trim().split(/\r?\n/).slice(1).map((l) => l.split(",")[2].toLowerCase()));
  } catch { return new Set(); }
  return carriers;
}

const TITLE = { delayed: "Flight delayed", offloaded: "Cargo left behind", cancelled: "Airline cancelled the booking" } as const;

export function getNotifications(now = Date.now() / 1000): Notice[] {
  if (!getDb()) return [];
  const since = now - WINDOW_S;
  const out: Notice[] = [];

  const bookings: Booking[] = q("SELECT thread_id, booking_reference, customer, origin, destination FROM bookings").map((b) => ({
    thread: Number(b.thread_id), ref: String(b.booking_reference ?? "").toUpperCase(), customer: String(b.customer ?? "").toLowerCase(),
    lane: `${b.origin ?? "?"} → ${b.destination ?? "?"}`,
  }));
  const byThread = new Map(bookings.map((b) => [b.thread, b]));
  const byRef = new Map(bookings.filter((b) => b.ref).map((b) => [b.ref, b]));
  const alerted = new Set<number>(); // cancellation already shown from the airline's mail

  // 1. The airline's own mails.
  const mails = q("SELECT id, sender, subject, body, received_at, raw FROM mails WHERE received_at > ? AND route IN ('booking_confirmation','carrier_bid') ORDER BY id", since);
  for (const m of mails) {
    const subject = String(m.subject ?? ""), body = String(m.body ?? ""), ts = Number(m.received_at);
    if (!carrierSenders().has(String(m.sender).toLowerCase()) || /\[bid-\d+\]/i.test(subject)) continue;
    const hit = mailAlert(subject, body);
    if (!hit) continue;
    const text = `${subject}\n${body}`.toUpperCase();
    const bk = /\bBK-[A-Z0-9]+\b/.exec(text)?.[0];
    const ours = /\bGOOGLE-(\d+)\b/.exec(text)?.[1];
    const b = (bk ? byRef.get(bk) : undefined) ?? (ours ? byThread.get(Number(ours)) : undefined);
    if (hit.type === "cancelled") {
      if (!b) continue; // "cannot accept" without one of our bookings is a declined price request
      // The airline acknowledging a cancellation we sent is not a problem.
      if (q("SELECT 1 FROM events WHERE thread_id=? AND kind IN ('booking_cancel_call','booking_cancelled') AND ts<=?", b.thread, ts).length) continue;
      alerted.add(b.thread);
    } else if (!b && !/\b(flight|flug|shipment|sendung|cargo|booking|buchung)\b/i.test(text)) continue;
    // "Told" only if a later mail to this customer carries the same news: a plain confirmation does not count.
    const told = !!b && q("SELECT data FROM events WHERE thread_id=? AND kind='mail_out' AND ts>=?", b.thread, ts).some((e) => {
      const d = parse<{ to?: string; body?: string }>(e.data, {});
      return d.to?.toLowerCase() === b.customer && mailAlert("", d.body ?? "")?.type === hit.type;
    });
    out.push({
      id: `mail-${m.id}-${Math.floor(ts)}`, ts, severity: hit.type === "delayed" ? "warning" : "critical",
      title: TITLE[hit.type], detail: hit.sentence, context: b ? `${b.lane}${b.ref ? ` · ${b.ref}` : ""}` : "No shipment matched",
      action: told ? "Customer informed" : b ? "Customer not told yet" : "Find the shipment",
      href: b ? `/v2/requests?id=${b.thread}` : "/v2/shipments",
      simulated: parse<{ simulated?: boolean }>(m.raw, {}).simulated === true,
    });
  }

  // 2. What the clerk logged as a problem at booking.
  for (const e of q("SELECT id, ts, thread_id, kind, data FROM events WHERE ts > ? AND kind IN ('booking_cancelled_by_airline','booking_price_changed')", since)) {
    const thread = Number(e.thread_id), b = byThread.get(thread);
    const cancelled = e.kind === "booking_cancelled_by_airline";
    if (cancelled && alerted.has(thread)) continue;
    const d = parse<{ quoted_total?: string; new_total?: string }>(e.data, {});
    out.push({
      id: `event-${e.id}-${Math.floor(Number(e.ts))}`, ts: Number(e.ts), severity: cancelled ? "critical" : "warning",
      title: cancelled ? TITLE.cancelled : "Booked above our quote",
      detail: cancelled ? "The shipment has no flight." : `Quoted ${d.quoted_total ?? "?"}, now ${d.new_total ?? "?"}.`,
      context: b?.lane ?? `Request ${thread}`, action: cancelled ? "Rebook" : "Customer must agree",
      href: `/v2/requests?id=${thread}`,
    });
  }

  // 3. Open problems: they leave the list when the status is resolved.
  const open = q(`SELECT s.thread_id, s.status, s.note, s.customer, s.received_at,
      (SELECT max(ts) FROM events e WHERE e.thread_id = s.thread_id AND e.kind IN ('needs_human','error','rfq_expired')) AS since
    FROM sessions s WHERE s.status IN ('needs_human','failed','expired')`);
  for (const s of open) {
    const ts = Number(s.since ?? s.received_at), thread = Number(s.thread_id), note = String(s.note ?? "");
    if (ts <= since || (alerted.has(thread) && note.startsWith("AIRLINE CANCELLED"))) continue;
    const missed = s.status === "expired", failed = s.status === "failed" || note.startsWith("error:");
    out.push({
      id: `status-${thread}-${s.status}-${Math.floor(ts)}`, ts, severity: missed || failed ? "critical" : "warning",
      title: missed ? "Request missed" : failed ? "Something went wrong" : "Request stopped",
      detail: note.slice(0, 170) || "The agent could not finish this request.",
      context: byThread.get(thread)?.lane ?? String(s.customer ?? ""), action: "Take a look", href: `/v2/requests?id=${thread}`,
    });
  }

  // 4. Agent stopped. Only on the runner's own DB: a copy or snapshot always has an old heartbeat.
  if (path.basename(DB_PATH) === "forwarder.db") {
    const beat = Number(q("SELECT * FROM state WHERE key='heartbeat'")[0]?.value ?? 0);
    if (beat && now - beat > SILENT_S) out.push({
      id: `stopped-${Math.floor(beat)}`, ts: beat + SILENT_S, severity: "critical", title: "Agent stopped",
      detail: "No heartbeat for more than 2 minutes. Mails are not being answered.", context: "Relay", action: "Check the runner",
      href: "/v2",
    });
  }

  return out.sort((a, b) => b.ts - a.ts);
}
