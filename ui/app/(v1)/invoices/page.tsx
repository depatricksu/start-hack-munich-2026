"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import type { CarrierFlag, Invoice, InvoiceData } from "@/lib/invoices";

type Payload = { invoices: InvoiceData; carriers: CarrierFlag[] };
type Filter = "open" | "overdue" | "reported" | "paid" | "all";

const eur = (v: number) => `${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
const eur0 = (v: number) => `${Math.round(v).toLocaleString("en-GB")} €`;
const day = (ts: number) => new Date(ts * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
const short = (m: string) => m.split("@")[0];

// Color = state: green paid, blue open, amber "check the bank" (a person must look), red overdue, grey cancelled.
const STATUS: Record<string, { label: string; cls: string }> = {
  open: { label: "Open", cls: "bg-sky-400/12 text-sky-300 ring-sky-400/25" },
  paid_reported: { label: "Customer says paid", cls: "bg-amber-400/14 text-amber-300 ring-amber-400/30" },
  paid: { label: "Paid", cls: "bg-emerald-400/12 text-emerald-300 ring-emerald-400/25" },
  overdue_human: { label: "Call the customer", cls: "bg-red-400/14 text-red-300 ring-red-400/30" },
  cancelled: { label: "Cancelled", cls: "bg-white/5 text-zinc-500 ring-white/10" },
};
const OVERDUE = { label: "Overdue", cls: "bg-red-400/14 text-red-300 ring-red-400/30" };

function Chip({ inv }: { inv: Invoice }) {
  const c = inv.overdue_days > 0 && inv.status === "open" ? OVERDUE : STATUS[inv.status] ?? { label: inv.status, cls: STATUS.cancelled.cls };
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${c.cls}`}>{c.label}</span>;
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="rounded-2xl glass px-5 py-4">
      <div className="num text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`num mt-1.5 text-3xl font-semibold tracking-tight ${tone ?? "text-white"}`}>{value}</div>
      <div className="mt-1 text-xs text-zinc-500">{sub}</div>
    </div>
  );
}

function Due({ inv, now }: { inv: Invoice; now: number }) {
  if (inv.status === "paid") return <span className="text-emerald-300">paid {inv.paid_at ? day(inv.paid_at) : ""}</span>;
  if (inv.status === "cancelled") return <span className="text-zinc-500">—</span>;
  if (inv.overdue_days > 0) return <span className="text-red-300">{inv.overdue_days} days late</span>;
  const left = Math.ceil((inv.due_at - now) / 86400);
  return <span className="text-zinc-400">due {day(inv.due_at)} <span className="text-zinc-600">· {left} d</span></span>;
}

export default function InvoicesPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [filter, setFilter] = useState<Filter>("open");
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now() / 1000);

  const load = useCallback(() => fetch("/api/invoices", { cache: "no-store" }).then((r) => r.json()).then(setData).catch(() => {}), []);
  useEffect(() => {
    load();
    const t = setInterval(() => { load(); setNow(Date.now() / 1000); }, 10000);
    return () => clearInterval(t);
  }, [load]);

  async function paid(inv: Invoice) {
    if (!window.confirm(`Mark ${inv.number} (${eur(inv.amount)}) as paid? Only do this when the money is in the bank.`)) return;
    setBusy(inv.thread_id);
    await fetch("/api/invoices/paid", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: inv.number }) });
    await load();
    setBusy(null);
  }

  if (!data) return <div className="p-8 text-sm text-zinc-500">Loading invoices…</div>;
  const d = data.invoices;
  if (!d.available) {
    return (
      <div className="h-full p-2"><div className="h-full rounded-2xl glass p-8">
        <h1 className="text-xl font-semibold text-white">Invoices</h1>
        <p className="mt-2 max-w-xl text-sm text-zinc-400">No invoices yet. They are written the day an airline confirms a booking
          (booking/invoice.py). The runner needs that code live for this page to fill.</p>
      </div></div>
    );
  }

  const rows = d.rows.filter((r) =>
    filter === "all" ? true
      : filter === "open" ? ["open", "paid_reported", "overdue_human"].includes(r.status)
      : filter === "overdue" ? r.overdue_days > 0 || r.status === "overdue_human"
      : filter === "reported" ? r.status === "paid_reported"
      : r.status === "paid");
  const maxCust = Math.max(1, ...d.byCustomer.map((c) => c.eur));

  return (
    <div className="h-full overflow-y-auto p-2">
      <div className="mx-auto max-w-[1400px] space-y-3 px-2 py-3">
        <div className="flex items-baseline justify-between px-1">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-white">Invoices</h1>
            <p className="mt-0.5 text-sm text-zinc-500">
              Written the day the airline confirms. {d.totals.mailed === 0
                ? "Mailing them to customers is switched off for now."
                : `${d.totals.mailed} sent to customers.`}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-4 gap-3">
          <Tile label="Open" value={eur0(d.totals.open_eur)} sub={`${d.totals.open} invoices waiting for payment`} />
          <Tile label="Overdue" value={eur0(d.totals.overdue_eur)} sub={d.totals.overdue ? `${d.totals.overdue} late, call these first` : "nothing late"}
            tone={d.totals.overdue ? "text-red-300" : "text-white"} />
          <Tile label="Check the bank" value={String(d.totals.reported)} sub="customer says paid" tone={d.totals.reported ? "text-amber-300" : "text-white"} />
          <Tile label="Paid" value={eur0(d.totals.paid_eur)} sub={`${d.totals.paid} invoices`} tone={d.totals.paid ? "text-emerald-300" : "text-white"} />
        </div>

        <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-3">
          {/* All invoices */}
          <section className="rounded-2xl glass p-4">
            <div className="mb-3 flex items-center gap-1.5">
              {([["open", "Open"], ["overdue", "Overdue"], ["reported", "Check the bank"], ["paid", "Paid"], ["all", "All"]] as [Filter, string][]).map(([k, label]) => (
                <button key={k} onClick={() => setFilter(k)}
                  className={`rounded-full px-3 py-1 text-xs transition ${filter === k ? "bg-white text-black" : "glass-2 text-zinc-400 hover:text-white"}`}>{label}</button>
              ))}
              <span className="num ml-auto text-xs text-zinc-500">{rows.length}</span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
                  <th className="py-1.5 font-medium">Invoice</th><th className="font-medium">Customer</th><th className="font-medium">Shipment</th>
                  <th className="text-right font-medium">Amount</th><th className="pl-4 font-medium">Due</th><th className="font-medium">Status</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 80).map((r) => (
                  <InvoiceRow key={r.thread_id} r={r} now={now} open={open === r.thread_id}
                    onToggle={() => setOpen(open === r.thread_id ? null : r.thread_id)} onPaid={() => paid(r)} busy={busy === r.thread_id} />
                ))}
                {rows.length === 0 && <tr><td colSpan={7} className="py-6 text-center text-sm text-zinc-500">Nothing here.</td></tr>}
              </tbody>
            </table>
            {rows.length > 80 && <p className="mt-2 text-xs text-zinc-500">Showing 80 of {rows.length}.</p>}
          </section>

          <div className="space-y-3">
            {/* Overdue: who to call */}
            <section className="rounded-2xl glass p-4">
              <h2 className="text-sm font-semibold text-white">Call these first</h2>
              <p className="text-xs text-zinc-500">Overdue, biggest first. After 2 reminders a person takes over.</p>
              <div className="mt-3 space-y-1.5">
                {d.overdue.length === 0 && <p className="text-sm text-zinc-500">Nothing is late.</p>}
                {d.overdue.slice(0, 6).map((r) => (
                  <Link key={r.thread_id} href={`/requests?id=${r.thread_id}`} className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-white/5">
                    <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-200">{short(r.customer)}</span>
                    <span className="num text-xs text-red-300">{r.overdue_days} d</span>
                    <span className="num w-24 text-right text-[13px] text-white">{eur0(r.amount)}</span>
                  </Link>
                ))}
              </div>
            </section>

            {/* Open per customer */}
            <section className="rounded-2xl glass p-4">
              <h2 className="text-sm font-semibold text-white">Open per customer</h2>
              <div className="mt-3 space-y-2.5">
                {d.byCustomer.slice(0, 8).map((c) => (
                  <div key={c.customer}>
                    <div className="flex items-baseline justify-between text-[13px]">
                      <span className="truncate text-zinc-300">{short(c.customer)} <span className="num text-zinc-600">· {c.n}</span></span>
                      <span className="num text-zinc-200">{eur0(c.eur)}</span>
                    </div>
                    <div className="mt-1 h-1 rounded-full bg-white/8"><div className="h-1 rounded-full bg-sky-400/60" style={{ width: `${(c.eur / maxCust) * 100}%` }} /></div>
                  </div>
                ))}
              </div>
            </section>

          </div>
        </div>
      </div>
    </div>
  );
}

function InvoiceRow({ r, now, open, onToggle, onPaid, busy }: { r: Invoice; now: number; open: boolean; onToggle: () => void; onPaid: () => void; busy: boolean }) {
  const payable = ["open", "paid_reported", "overdue_human"].includes(r.status);
  return (
    <>
      <tr className="border-t border-line text-zinc-300 hover:bg-white/[0.03]">
        <td className="py-2">
          <button onClick={onToggle} className="num flex items-center gap-1.5 text-[13px] text-white">
            <ChevronDown size={13} className={`text-zinc-500 transition ${open ? "rotate-180" : ""}`} />{r.number}
          </button>
        </td>
        <td className="max-w-[160px] truncate text-[13px]" title={r.customer}>{short(r.customer)}</td>
        <td className="text-[13px]">
          <Link href={`/requests?id=${r.thread_id}`} className="num text-zinc-300 hover:text-white">{r.route ?? `#${r.thread_id}`}</Link>
        </td>
        <td className="num text-right text-[13px] text-white">{eur(r.amount)}</td>
        <td className="num pl-4 text-xs"><Due inv={r} now={now} /></td>
        <td><Chip inv={r} /></td>
        <td className="text-right">
          {payable && (
            <button onClick={onPaid} disabled={busy}
              className="rounded-md glass-2 px-2 py-1 text-[11px] text-zinc-300 transition hover:text-white disabled:opacity-50">
              {busy ? "…" : "Mark paid"}
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr className="border-t border-line">
          <td colSpan={7} className="pb-3 pt-2">
            <div className="flex gap-6 text-xs text-zinc-500">
              <span>Issued <span className="num text-zinc-300">{day(r.issued_at)}</span></span>
              <span>Reminders <span className="num text-zinc-300">{r.reminders}</span></span>
              <span>{r.sent ? "Sent to the customer" : "Draft, not sent"}</span>
            </div>
            {r.body && <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-xl bg-white/[0.03] p-3 font-sans text-[13px] text-zinc-300 ring-1 ring-inset ring-white/8">{r.body}</pre>}
          </td>
        </tr>
      )}
    </>
  );
}
