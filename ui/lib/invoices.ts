// Cash flow for the forwarder: Patrick's `invoices` table (booking/invoice.py) and his `carrier_flags`
// (monitor/carriers.py). Read-only except markPaid, which does what `python3 -m booking.invoice --paid` does.
import { getDb, getWriteDb } from "./db";

export type InvoiceStatus = "open" | "paid_reported" | "paid" | "overdue_human" | "cancelled" | string;
export type Invoice = {
  thread_id: number; number: string; customer: string; subject: string; amount: number; currency: string;
  issued_at: number; due_at: number; status: InvoiceStatus; sent: boolean; reminders: number;
  last_reminder_at: number | null; paid_at: number | null; body: string; overdue_days: number;
  route: string | null;
};
export type InvoiceData = {
  available: boolean;
  totals: { open_eur: number; open: number; overdue_eur: number; overdue: number; reported: number; paid: number; paid_eur: number; mailed: number };
  overdue: Invoice[]; reported: Invoice[]; byCustomer: { customer: string; eur: number; n: number }[]; rows: Invoice[];
};
export type CarrierFlag = {
  carrier: string; role: string; level: "red" | "amber" | "ok" | "unknown" | string; jobs: number; issues: number;
  issue_rate: number; reasons: string[]; examples: Record<string, number[]>; updated_at: number | null;
};

const DAY = 86400;
const OPEN = ["open", "paid_reported", "overdue_human"];

function hasTable(name: string): boolean {
  const db = getDb();
  if (!db) return false;
  return !!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(name);
}

function json<T>(v: unknown, fb: T): T {
  if (typeof v !== "string" || !v) return fb;
  try { return JSON.parse(v) as T; } catch { return fb; }
}

export function getInvoices(now = Date.now() / 1000): InvoiceData {
  const empty: InvoiceData = { available: false, totals: { open_eur: 0, open: 0, overdue_eur: 0, overdue: 0, reported: 0, paid: 0, paid_eur: 0, mailed: 0 },
    overdue: [], reported: [], byCustomer: [], rows: [] };
  if (!hasTable("invoices")) return empty;
  const db = getDb();
  const raw = db.prepare(`SELECT i.*, json_extract(s.fields,'$.origin') AS o, json_extract(s.fields,'$.destination') AS d
    FROM invoices i LEFT JOIN sessions s ON s.thread_id = i.thread_id ORDER BY i.issued_at DESC`).all() as Record<string, unknown>[];
  const rows: Invoice[] = raw.map((r) => {
    const status = String(r.status ?? "open");
    const due = Number(r.due_at ?? 0);
    const o = r.o && r.o !== "null" ? String(r.o) : null, d = r.d && r.d !== "null" ? String(r.d) : null;
    return {
      thread_id: Number(r.thread_id), number: String(r.number ?? ""), customer: String(r.customer ?? ""),
      subject: String(r.subject ?? ""), amount: Number(r.amount ?? 0) || 0, currency: String(r.currency ?? "EUR"),
      issued_at: Number(r.issued_at ?? 0), due_at: due, status, sent: Number(r.sent ?? 0) === 1,
      reminders: Number(r.reminders ?? 0), last_reminder_at: r.last_reminder_at == null ? null : Number(r.last_reminder_at),
      paid_at: r.paid_at == null ? null : Number(r.paid_at), body: String(r.body ?? ""),
      overdue_days: OPEN.includes(status) && now > due ? Math.floor((now - due) / DAY) : 0,
      route: o || d ? `${o ?? "???"} → ${d ?? "???"}` : null,
    };
  });
  const eur = (xs: Invoice[]) => xs.reduce((a, x) => a + (x.currency === "EUR" ? x.amount : 0), 0);
  const open = rows.filter((r) => OPEN.includes(r.status));
  const overdue = open.filter((r) => r.overdue_days > 0 || r.status === "overdue_human").sort((a, b) => b.amount - a.amount);
  const reported = rows.filter((r) => r.status === "paid_reported");
  const paid = rows.filter((r) => r.status === "paid");
  const m = new Map<string, { eur: number; n: number }>();
  for (const r of open) { const x = m.get(r.customer) ?? { eur: 0, n: 0 }; x.eur += r.amount; x.n += 1; m.set(r.customer, x); }
  return {
    available: true,
    totals: { open_eur: eur(open), open: open.length, overdue_eur: eur(overdue), overdue: overdue.length,
      reported: reported.length, paid: paid.length, paid_eur: eur(paid), mailed: rows.filter((r) => r.sent).length },
    overdue, reported, rows,
    byCustomer: [...m.entries()].map(([customer, x]) => ({ customer, ...x })).sort((a, b) => b.eur - a.eur),
  };
}

export function getInvoice(threadId: number): Invoice | null {
  return getInvoices().rows.find((r) => r.thread_id === threadId) ?? null;
}

// The forwarder saw the money in the bank. Same effect as booking.invoice.mark_paid: status, paid_at, an event.
export function markPaid(key: string): Invoice | null {
  const k = Number(String(key).toUpperCase().replace("INV-", ""));
  if (!Number.isInteger(k) || !hasTable("invoices")) return null;
  const w = getWriteDb();
  if (!w) return null;
  const inv = w.prepare("SELECT number, amount FROM invoices WHERE thread_id=?").get(k) as { number: string; amount: string } | undefined;
  if (!inv) return null;
  const now = Date.now() / 1000;
  w.prepare("UPDATE invoices SET status='paid', paid_at=? WHERE thread_id=?").run(now, k);
  try {
    w.prepare("INSERT INTO events(ts, kind, thread_id, data) VALUES (?, 'invoice_paid', ?, ?)")
      .run(now, k, JSON.stringify({ number: inv.number, amount: inv.amount, by: "ui" }));
  } catch { /* the events table may differ in older DBs; the status change is what matters */ }
  return getInvoice(k);
}

export function getCarrierFlags(): CarrierFlag[] {
  if (!hasTable("carrier_flags")) return [];
  const order: Record<string, number> = { red: 0, amber: 1, ok: 2, unknown: 3 };
  return (getDb().prepare("SELECT * FROM carrier_flags").all() as Record<string, unknown>[])
    .map((r) => ({
      carrier: String(r.carrier), role: String(r.role ?? ""), level: String(r.level ?? "unknown"),
      jobs: Number(r.jobs ?? 0), issues: Number(r.issues ?? 0), issue_rate: Number(r.issue_rate ?? 0),
      reasons: json<string[]>(r.reasons, []), examples: json<Record<string, number[]>>(r.examples, {}),
      updated_at: r.updated_at == null ? null : Number(r.updated_at),
    }))
    .sort((a, b) => (order[a.level] ?? 9) - (order[b.level] ?? 9) || b.issue_rate - a.issue_rate);
}
