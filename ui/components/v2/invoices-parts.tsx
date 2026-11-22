"use client";
// Relay v2 Invoices: the table row (with inline body and "Mark paid"), the KPI tile and the side lists.
import { ReactNode } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown } from "lucide-react";
import type { Invoice } from "@/lib/invoices";
import { Badge, Card, CardHead, EASE, Tone, day, eur, money, shortMail } from "@/components/v2/ui";

export type Filter = "open" | "overdue" | "reported" | "paid" | "all";
export const PAYABLE = ["open", "paid_reported", "overdue_human"];
export const isOverdue = (r: Invoice) => r.status !== "paid" && r.status !== "cancelled" && (r.overdue_days > 0 || r.status === "overdue_human");
export const inFilter = (r: Invoice, f: Filter) =>
  f === "all" ? true
    : f === "open" ? PAYABLE.includes(r.status)
    : f === "overdue" ? isOverdue(r)
    : f === "reported" ? r.status === "paid_reported"
    : r.status === "paid";

export const COLS = "grid-cols-[132px_minmax(120px,1fr)_112px_128px_150px_148px_92px]";

export function Kpi({ label, sub, children, tone }: { label: string; sub: ReactNode; children: ReactNode; tone?: string }) {
  return (
    <Card className="h-full">
      <div className="eyebrow">{label}</div>
      <div className={`mt-2 text-[28px] font-semibold leading-none tracking-[-0.03em] ${tone ?? "text-[var(--fg)]"}`}>{children}</div>
      <div className="mt-2 text-[13px] text-[var(--fg-2)]">{sub}</div>
    </Card>
  );
}

function statusOf(r: Invoice): [string, Tone] {
  if (r.status === "paid") return ["Paid", "ok"];
  if (r.status === "cancelled") return ["Cancelled", "idle"];
  if (r.status === "paid_reported") return ["Customer says paid", "warn"];
  if (r.status === "overdue_human") return ["Call the customer", "bad"];
  if (r.overdue_days > 0) return ["Overdue", "bad"];
  return ["Open", "idle"];
}

function Due({ r, now }: { r: Invoice; now: number }) {
  if (r.status === "paid") return <span className="text-[var(--fg-2)]">Paid {r.paid_at ? day(r.paid_at) : ""}</span>;
  if (r.status === "cancelled") return <span className="text-[var(--fg-3)]">Not due</span>;
  if (r.overdue_days > 0) return <span className="text-[var(--bad)]">{r.overdue_days} {r.overdue_days === 1 ? "day" : "days"} late</span>;
  const left = Math.max(0, Math.ceil((r.due_at - now) / 86400));
  return (
    <span className="text-[var(--fg-2)]">
      <span className="tnum">{day(r.due_at)}</span>{" "}
      <span className="text-[var(--fg-3)]">{left === 0 ? "today" : `in ${left} ${left === 1 ? "day" : "days"}`}</span>
    </span>
  );
}

export function InvoiceRow({ r, now, open, onToggle, onPaid, busy, error }:
  { r: Invoice; now: number; open: boolean; onToggle: () => void; onPaid: () => void; busy: boolean; error: string | null }) {
  const [label, tone] = statusOf(r);
  const payable = PAYABLE.includes(r.status);
  return (
    <li className="border-t border-[var(--hair)]">
      <div onClick={onToggle}
        className={`group grid ${COLS} cursor-pointer items-center gap-3 px-4 py-2.5 text-[13px] transition-colors duration-150 hover:bg-[var(--bg-2)] ${open ? "bg-[var(--bg-2)]" : ""}`}>
        <button onClick={(e) => { e.stopPropagation(); onToggle(); }} aria-expanded={open}
          className="tnum flex items-center gap-1.5 text-left text-[var(--fg)]">
          <ChevronDown size={13} className={`shrink-0 text-[var(--fg-3)] transition-transform duration-150 ${open ? "rotate-180" : ""}`} />{r.number}
        </button>
        <span className="truncate text-[var(--fg)]" title={r.customer}>{shortMail(r.customer)}</span>
        <span className="tnum truncate text-[var(--fg-2)]">{r.route ?? `#${r.thread_id}`}</span>
        <span className="tnum text-right text-[var(--fg)]">{money(r.amount, r.currency)}</span>
        <span className="pl-3"><Due r={r} now={now} /></span>
        <span><Badge tone={tone}>{label}</Badge></span>
        <span className="flex justify-end">
          {payable && (
            <button onClick={(e) => { e.stopPropagation(); onPaid(); }} disabled={busy}
              className={`btn btn-ghost h-7 px-2.5 text-[12px] transition-opacity duration-150 focus-visible:opacity-100 group-hover:opacity-100 ${busy ? "opacity-100" : "opacity-0"}`}>
              {busy ? "Saving" : "Mark paid"}
            </button>
          )}
        </span>
      </div>
      {error && <p className="px-4 pb-2 text-right text-[13px] text-[var(--bad)]">{error}</p>}
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }} className="overflow-hidden">
            <div className="px-4 pb-4 pt-1 pl-[34px]">
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-[13px] text-[var(--fg-3)]">
                <span>Issued <span className="tnum text-[var(--fg-2)]">{day(r.issued_at)}</span></span>
                <span>Reminders <span className="tnum text-[var(--fg-2)]">{r.reminders}</span></span>
                <span>{r.sent ? "Mailed to the customer" : "Not mailed to the customer"}</span>
                <Link href={`/v2/shipments?id=${r.thread_id}`} className="text-[var(--fg-2)] transition-colors duration-150 hover:text-[var(--fg)]">Open shipment</Link>
              </div>
              {r.body && (
                <pre className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-md border border-[var(--hair)] bg-[var(--bg)] p-4 font-sans text-[13px] leading-relaxed text-[var(--fg-2)] scroll-thin">{r.body}</pre>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

export function CallFirst({ rows }: { rows: Invoice[] }) {
  return (
    <Card>
      <CardHead title="Call these first" hint="Overdue, biggest first" />
      {rows.length === 0 ? (
        <p className="text-[13px] text-[var(--fg-2)]">Nothing is late. Every open invoice is still within its payment time.</p>
      ) : (
        <ul className="-mx-2">
          {rows.slice(0, 6).map((r) => (
            <li key={r.thread_id}>
              <Link href={`/v2/requests?id=${r.thread_id}`} className="flex items-center gap-3 rounded-md px-2 py-2 transition-colors duration-150 hover:bg-[var(--bg-2)]">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--bad)]" />
                <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg)]">{shortMail(r.customer)}</span>
                <span className="tnum text-[12px] text-[var(--bad)]">{r.overdue_days} d late</span>
                <span className="tnum w-24 text-right text-[13px] text-[var(--fg)]">{eur(r.amount)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function PerCustomer({ rows }: { rows: { customer: string; eur: number; n: number }[] }) {
  const max = Math.max(1, ...rows.map((c) => c.eur));
  return (
    <Card>
      <CardHead title="Open per customer" hint={`${rows.length} customers`} />
      {rows.length === 0 ? <p className="text-[13px] text-[var(--fg-2)]">Nothing open.</p> : (
        <ol className="space-y-3">
          {rows.slice(0, 8).map((c, i) => (
            <li key={c.customer} className="grid grid-cols-[20px_minmax(0,1fr)] gap-x-2">
              <span className="tnum pt-px text-[12px] text-[var(--fg-3)]">{i + 1}</span>
              <div className="min-w-0">
                <div className="flex items-baseline gap-2 text-[13px]">
                  <span className="truncate text-[var(--fg)]">{shortMail(c.customer)}</span>
                  <span className="tnum text-[12px] text-[var(--fg-3)]">{c.n}</span>
                  <span className="flex-1" />
                  <span className="tnum text-[var(--fg)]">{eur(c.eur)}</span>
                </div>
                <motion.div initial={{ scaleX: 0 }} animate={{ scaleX: 1 }} transition={{ duration: 0.6, ease: EASE, delay: 0.1 + i * 0.04 }}
                  style={{ width: `${(c.eur / max) * 100}%`, originX: 0 }} className="mt-1.5 h-[2px] rounded-full bg-[var(--fg-3)]" />
              </div>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
