// One invoice as a document: the `invoices` row (booking/invoice.py) plus what the order says in sessions and bookings.
// The page and the PDF both read this, so they always show the same thing. Read-only. A field with no data is null
// and is left out: nothing here is invented (no address, tax line or bank details exist in the data).
import { getDb } from "./db";

export type DocItem = { label: string; amount: string };
export type DocGroup = { title: string | null; items: DocItem[] };
export type DocLeg = {
  n: number | null; origin: string | null; destination: string | null; airline: string | null;
  kg: string | null; cbm: string | null; booking: string | null;
};
export type InvoiceDoc = {
  number: string; threadId: number;
  seller: { name: string; contact: string | null; email: string | null };
  customer: { email: string; request: string | null };
  issued: string; due: string; termsDays: number | null;
  status: { label: string; tone: "ok" | "warn" | "bad" | "idle"; paid: string | null };
  reference: string; bookings: string[]; legs: DocLeg[];
  totalKg: string | null; totalCbm: string | null;
  groups: DocGroup[]; itemsNote: string | null;
  total: string; currency: string;
  body: string;
};

const DAY = 86400;
// Same words as the offer PDF (core/offer_file.py) and the invoice mail (booking/invoice.py).
const SELLER_NAME = "Air Export";
const SELLER_CONTACT = process.env.SIGNER || "Lena Hofmann";
const SELLER_EMAIL = process.env.OUR_ADDRESS || "google@hackloop.mail";

type Obj = Record<string, unknown>;
function json(v: unknown): Obj {
  if (typeof v !== "string" || !v) return {};
  try { const j = JSON.parse(v); return j && typeof j === "object" ? (j as Obj) : {}; } catch { return {}; }
}
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() && v !== "null" ? v.trim() : typeof v === "number" ? String(v) : null);
const arr = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter((x) => x && typeof x === "object") as Obj[] : []);

// Money stays a string from the database; cents are only used to compare sums.
const cents = (s: string | null): number | null => {
  if (s == null || !/^-?\d+(\.\d{1,2})?$/.test(s.trim())) return null;
  return Math.round(Number(s) * 100);
};
const sum = (items: DocItem[]): number | null => {
  let t = 0;
  for (const i of items) { const c = cents(i.amount); if (c == null) return null; t += c; }
  return t;
};
// 1972.0 -> "1972", 4.63 -> "4.63"
const num = (v: unknown): string | null => {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() ? Number(v) : NaN;
  return Number.isFinite(n) ? String(Number(n.toFixed(2))) : null;
};

const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "Europe/Berlin" });
const fmtDate = (t: number) => dateFmt.format(new Date(t * 1000));

function statusOf(status: string, overdueDays: number, paidAt: number | null): InvoiceDoc["status"] {
  const paid = paidAt ? fmtDate(paidAt) : null;
  if (status === "paid") return { label: "Paid", tone: "ok", paid };
  if (status === "cancelled") return { label: "Cancelled", tone: "idle", paid: null };
  if (status === "paid_reported") return { label: "Customer says paid", tone: "warn", paid };
  if (status === "overdue_human") return { label: "Overdue", tone: "bad", paid: null };
  if (overdueDays > 0) return { label: "Overdue", tone: "bad", paid: null };
  return { label: "Open", tone: "idle", paid: null };
}

// The price lines. Three sources, best first; the first one whose lines add up exactly to the invoiced total wins.
// If none does, the lines the invoice itself stored are shown with a note, and the total stays as invoiced.
function priceGroups(chosen: Obj, stored: DocItem[], cur: string, amount: string, legs: DocLeg[]): { groups: DocGroup[]; note: string | null } {
  const same = (c: unknown) => c == null || c === cur;
  const freightLabel = (o: string | null, d: string | null, a: string | null) => `Air freight ${o ?? "?"} to ${d ?? "?"}${a ? `, ${a}` : ""}`;
  const insuranceItem = (x: unknown): DocItem[] => {
    const i = x && typeof x === "object" ? (x as Obj) : null;
    const p = i && str(i.premium);
    return p ? [{ label: "Cargo insurance", amount: p }] : [];
  };
  const customsItem = (x: unknown): DocItem[] => {
    const c = x && typeof x === "object" ? (x as Obj) : null;
    const f = c && str(c.fee);
    return f ? [{ label: "Customs clearance", amount: f }] : [];
  };

  const candidates: DocGroup[][] = [];
  const parts = arr(chosen.parts);
  if (parts.length > 1) {
    candidates.push(parts.map((p, k) => {
      const items: DocItem[] = [];
      const fl = str(p.flight_total), tr = str(p.trucker_total);
      if (fl && same(p.currency)) items.push({ label: freightLabel(str(p.origin), str(p.destination), str(p.airline)), amount: fl });
      if (tr && same(p.trucker_currency)) items.push({ label: `Pickup by truck${str(p.trucker) ? `, ${str(p.trucker)}` : ""}`, amount: tr });
      items.push(...insuranceItem(p.insurance), ...customsItem(p.customs));
      return { title: `Shipment ${num(p.n) ?? k + 1}: ${str(p.origin) ?? "?"} to ${str(p.destination) ?? "?"}`, items };
    }));
  } else {
    const items: DocItem[] = [];
    const fl = str(chosen.flight_total);
    const o = legs[0]?.origin ?? null, d = legs[0]?.destination ?? null, a = legs[0]?.airline ?? null;
    if (fl && same(chosen.flight_currency)) items.push({ label: freightLabel(o, d, a), amount: fl });
    const tr = str(chosen.trucker_total);
    if (tr && same(chosen.trucker_currency)) items.push({ label: `Pickup by truck${str(chosen.trucker) ? `, ${str(chosen.trucker)}` : ""}`, amount: tr });
    items.push(...insuranceItem(chosen.insurance), ...customsItem(chosen.customs));
    candidates.push([{ title: null, items }]);
  }
  candidates.push([{ title: null, items: stored }]);

  const target = cents(amount);
  const flat = (g: DocGroup[]) => g.flatMap((x) => x.items);
  const fit = candidates.find((g) => flat(g).length > 0 && sum(flat(g)) === target);
  if (fit) return { groups: fit, note: null };
  const fallback = stored.length ? [{ title: null, items: stored }] : candidates.map((g) => g).find((g) => flat(g).length > 0) ?? [];
  return { groups: fallback, note: flat(fallback).length ? "The lines shown do not add up to the total. The total is the amount invoiced." : null };
}

// number: "INV-123" or "123" (the thread). Null when there is no such invoice.
export function getInvoiceDoc(key: string, now = Date.now() / 1000): InvoiceDoc | null {
  const db = getDb();
  if (!db) return null;
  if (!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='invoices'").get()) return null;
  const k = String(key).trim().toUpperCase().replace(/^INV-/, "");
  if (!/^\d+$/.test(k)) return null;
  const inv = db.prepare("SELECT * FROM invoices WHERE thread_id=?").get(Number(k)) as Obj | undefined;
  if (!inv) return null;
  const tid = Number(inv.thread_id);
  const s = db.prepare("SELECT customer, subject, fields, chosen FROM sessions WHERE thread_id=?").get(tid) as Obj | undefined;
  const hasBookings = !!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bookings'").get();
  const b = (hasBookings ? db.prepare("SELECT * FROM bookings WHERE thread_id=?").get(tid) : undefined) as Obj | undefined;
  const chosen = json(s?.chosen), fields = json(s?.fields);

  const amount = String(inv.amount ?? "");
  const currency = String(inv.currency ?? "EUR");
  const issued = Number(inv.issued_at ?? 0), due = Number(inv.due_at ?? 0);
  const status = String(inv.status ?? "open");
  const overdueDays = ["open", "paid_reported", "overdue_human"].includes(status) && now > due ? Math.floor((now - due) / DAY) : 0;

  // Legs: one per shipment of the request. A single shipment reads the booking row first, then the quote.
  const parts = arr(chosen.parts);
  const legs: DocLeg[] = parts.length > 1
    ? parts.map((p, i) => ({
        n: Number(p.n) || i + 1, origin: str(p.origin), destination: str(p.destination), airline: str(p.airline),
        kg: num(p.kg), cbm: num(p.cbm), booking: str(p.booking_reference),
      }))
    : [{
        n: null, origin: str(b?.origin) ?? str(chosen.origin) ?? str(fields.origin),
        destination: str(b?.destination) ?? str(chosen.destination) ?? str(fields.destination),
        airline: str(b?.airline) ?? str(chosen.airline),
        kg: num(fields.weight_kg_total) ?? num(fields.weight_kg) ?? num(b?.weight_kg),
        cbm: num(fields.volume_cbm_total) ?? num(fields.volume_cbm) ?? num(b?.volume_cbm),
        booking: str(b?.booking_reference),
      }];
  // The booking row carries the reference of the first shipment of a multi request; do not lose it.
  if (parts.length > 1 && b && str(b.booking_reference) && !legs.some((l) => l.booking)) legs[0].booking = str(b.booking_reference);
  const bookings = [...new Set(legs.map((l) => l.booking).filter((x): x is string => !!x))];

  let stored: DocItem[] = [];
  try {
    const raw = JSON.parse(String(inv.lines ?? "[]"));
    if (Array.isArray(raw)) stored = raw.filter((r) => Array.isArray(r) && r.length >= 2).map((r) => ({ label: String(r[0]), amount: String(r[1]) }));
  } catch { /* the stored lines are only a fallback */ }
  const { groups, note } = priceGroups(chosen, stored, currency, amount, legs);

  const subject = str(inv.subject) ?? str(s?.subject);
  return {
    number: String(inv.number ?? `INV-${tid}`), threadId: tid,
    seller: { name: SELLER_NAME, contact: SELLER_CONTACT, email: SELLER_EMAIL },
    customer: { email: String(inv.customer ?? s?.customer ?? ""), request: subject },
    issued: fmtDate(issued), due: fmtDate(due),
    termsDays: due > issued ? Math.round((due - issued) / DAY) : null,
    status: statusOf(status, overdueDays, inv.paid_at == null ? null : Number(inv.paid_at)),
    reference: str(b?.team_reference) ?? `GOOGLE-${tid}`, bookings, legs,
    totalKg: num(fields.weight_kg_total) ?? (legs.length === 1 ? legs[0].kg : null),
    totalCbm: num(fields.volume_cbm_total) ?? (legs.length === 1 ? legs[0].cbm : null),
    groups, itemsNote: note, total: amount, currency, body: String(inv.body ?? ""),
  };
}
