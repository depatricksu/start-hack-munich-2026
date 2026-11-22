// "Off track": shipments and requests that left the happy path, with what Relay already did about each.
// Read-only. Built from data the other screens already use (sessions, events, shipments, invoices, carrier mails).
import { getDb } from "./db";
import { getSessions } from "./data";
import { getShipments } from "./shipments";
import { getInvoices } from "./invoices";
import { getCarriers } from "./carriers";

export type ExceptionKind = "docs" | "unconfirmed" | "carrier" | "overdue";
export type OffTrack = {
  id: string;
  kind: ExceptionKind;
  tone: "warn" | "bad";
  title: string;           // the problem, in plain words
  route: string | null;    // "MUC → PEK"
  customer: string;
  since: number;           // unix seconds: when the problem started
  action: string;          // what Relay did or is doing about it
  href: string;            // where to look
};

const HOUR = 3600;
const UNCONFIRMED_AFTER = 2 * HOUR;   // airlines usually confirm within minutes; two hours is clearly late
const CARRIER_NEWS_DAYS = 3;          // carrier bad news older than this is history, not an open problem

function count(kind: string, thread: number): number {
  const db = getDb();
  if (!db) return 0;
  try {
    return (db.prepare("SELECT COUNT(*) AS n FROM events WHERE kind=? AND thread_id=?").get(kind, thread) as { n: number }).n;
  } catch { return 0; }
}

const times = (n: number) => (n === 1 ? "once" : `${n} times`);

export function getExceptions(now = Date.now() / 1000): OffTrack[] {
  const out: OffTrack[] = [];
  const { sessions } = getSessions();

  // 1. Quote accepted, but the customer still owes us the documents (AWB data, invoice, DG papers).
  for (const s of sessions.filter((x) => (x.status as string) === "awaiting_docs")) {
    const nudges = count("follow_up_nudge", s.thread_id);
    out.push({
      id: `docs-${s.thread_id}`, kind: "docs", tone: "warn", title: "Waiting for the customer's documents",
      route: `${s.fields.origin ?? "???"} → ${s.fields.destination ?? "???"}`, customer: s.customer,
      since: s.quoted_at ?? s.received_at,
      action: nudges ? `Relay reminded the customer ${times(nudges)}` : "No reminder sent yet",
      href: `/v2/requests?id=${s.thread_id}`,
    });
  }

  // 2. Booked with the airline, but no confirmation came back.
  const ships = getShipments();
  for (const r of ships.rows.filter((x) => x.status === "booked" && now - x.at > UNCONFIRMED_AFTER)) {
    out.push({
      id: `unconf-${r.thread}`, kind: "unconfirmed", tone: "warn", title: "Airline has not confirmed the booking",
      route: `${r.origin ?? "???"} → ${r.destination ?? "???"}`, customer: r.customer, since: r.at,
      action: `Relay is waiting for ${r.airline ?? "the airline"} to confirm`,
      href: `/v2/shipments?id=${r.thread}`,
    });
  }

  // 3. A carrier wrote that something went wrong (delay, cancellation, rebooking) in the last few days.
  const carriers = getCarriers(now);
  // A delay is no longer a problem once the same shipment arrived or was delivered after it.
  const landed = new Map<number, number>();
  for (const u of carriers.updates)
    if (u.thread != null && (u.type === "arrived" || u.type === "delivered")) landed.set(u.thread, Math.max(landed.get(u.thread) ?? 0, u.ts));
  for (const u of carriers.updates) {
    if (u.from !== "carrier" || !["delayed", "cancelled", "rebooked"].includes(u.type)) continue;
    if (u.thread != null && (landed.get(u.thread) ?? 0) >= u.ts) continue;
    if (now - u.ts > CARRIER_NEWS_DAYS * 86400) continue;
    out.push({
      id: `carrier-${u.id}`, kind: "carrier", tone: u.type === "rebooked" ? "warn" : "bad",
      title: `${u.carrier ?? "Carrier"}: ${u.label.toLowerCase()}`,
      route: u.lane, customer: u.company ?? "", since: u.ts,
      action: u.told === "yes" ? "Relay told the customer" : u.told === "no" ? "Customer not told yet" : "Nothing to tell the customer",
      href: u.thread ? `/v2/shipments?id=${u.thread}` : "/v2/shipments",
    });
  }

  // 4. Money: invoices past their due date.
  const inv = getInvoices(now);
  for (const i of inv.overdue) {
    out.push({
      id: `inv-${i.thread_id}`, kind: "overdue", tone: "bad",
      title: i.status === "overdue_human" ? "Invoice overdue, needs a call" : `Invoice ${i.overdue_days} days overdue`,
      route: i.route, customer: i.customer, since: i.due_at,
      action: i.reminders ? `Relay sent ${i.reminders} reminder${i.reminders === 1 ? "" : "s"}` : "No reminder sent yet",
      href: "/v2/invoices",
    });
  }

  // Worst first (red before amber), then the oldest problem first.
  return out.sort((a, b) => (a.tone === b.tone ? a.since - b.since : a.tone === "bad" ? -1 : 1));
}
