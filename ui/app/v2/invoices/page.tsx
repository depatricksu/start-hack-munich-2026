"use client";
// Relay v2 Invoices: what is open, what is late, and who to call. "Mark paid" is the only write on this page.
import { useMemo, useState } from "react";
import type { CarrierFlag, Invoice, InvoiceData } from "@/lib/invoices";
import { Card, CountUp, Item, PageHead, Reveal, Segmented, Skeleton, eur, useJson, useNow } from "@/components/v2/ui";
import { COLS, CallFirst, Filter, InvoiceRow, Kpi, PerCustomer, inFilter, isOverdue } from "@/components/v2/invoices-parts";

type Payload = { invoices: InvoiceData; carriers: CarrierFlag[] };
const CAP = 25;
const fmtEur = (v: number) => eur(v);
function omit<V>(o: Record<number, V>, k: number): Record<number, V> {
  const c = { ...o };
  delete c[k];
  return c;
}

function Loading() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-6 px-6 py-8">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-4 gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[112px]" />)}</div>
      <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-4"><Skeleton className="h-[520px]" /><Skeleton className="h-[300px]" /></div>
    </div>
  );
}

export default function InvoicesPage() {
  const raw = useJson<Payload>("/api/invoices", 10000);
  const now = useNow(60000);
  const [filter, setFilter] = useState<Filter>("open");
  const [all, setAll] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  // Optimistic "paid": thread_id -> time we marked it. Stays until the server agrees (or the POST fails).
  const [paidLocal, setPaidLocal] = useState<Record<number, number>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});

  const d = useMemo<InvoiceData | null>(() => {
    const src = raw?.invoices;
    if (!src) return null;
    const ids = Object.keys(paidLocal).map(Number);
    if (!ids.length) return src;
    const t = { ...src.totals };
    const fix = (r: Invoice): Invoice => {
      const at = paidLocal[r.thread_id];
      if (at == null || r.status === "paid") return r;
      t.open -= 1; t.open_eur -= r.amount; t.paid += 1; t.paid_eur += r.amount;
      if (isOverdue(r)) { t.overdue -= 1; t.overdue_eur -= r.amount; }
      if (r.status === "paid_reported") t.reported -= 1;
      return { ...r, status: "paid", paid_at: at, overdue_days: 0 };
    };
    const rows = src.rows.map(fix);
    const left = new Set(rows.filter((r) => r.status !== "paid").map((r) => r.thread_id));
    const byCustomer = src.byCustomer.map((c) => {
      const gone = rows.filter((r) => r.customer === c.customer && paidLocal[r.thread_id] != null && src.rows.find((x) => x.thread_id === r.thread_id)?.status !== "paid");
      return { ...c, eur: c.eur - gone.reduce((a, r) => a + r.amount, 0), n: c.n - gone.length };
    }).filter((c) => c.n > 0).sort((a, b) => b.eur - a.eur);
    return { ...src, totals: t, rows, byCustomer, overdue: src.overdue.filter((r) => left.has(r.thread_id)), reported: src.reported.filter((r) => left.has(r.thread_id)) };
  }, [raw, paidLocal]);

  async function markPaid(inv: Invoice) {
    if (!window.confirm(`Mark ${inv.number} (${eur(inv.amount)}) as paid? Only do this when the money is in the bank.`)) return;
    const id = inv.thread_id;
    setBusy(id);
    setErrors((x) => omit(x, id));
    setPaidLocal((p) => ({ ...p, [id]: Date.now() / 1000 }));
    try {
      const r = await fetch("/api/invoices/paid", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: inv.number }) });
      if (!r.ok) {
        const j = (await r.json().catch(() => ({}))) as { error?: string };
        throw new Error(j.error ?? `the server said ${r.status}`);
      }
    } catch (e) {
      setPaidLocal((p) => omit(p, id));
      setErrors((x) => ({ ...x, [id]: `Could not mark ${inv.number} paid: ${e instanceof Error ? e.message : "network error"}.` }));
    } finally {
      setBusy(null);
    }
  }

  if (!d) return <div className="h-full overflow-y-auto scroll-thin"><Loading /></div>;
  if (!d.available) {
    return (
      <div className="mx-auto max-w-[1440px] px-6 py-8">
        <PageHead title="Invoices" sub="Written the day the airline confirms." />
        <Card className="mt-6"><p className="text-[14px] text-[var(--fg-2)]">No invoices yet. They are written the day an airline confirms a booking.</p></Card>
      </div>
    );
  }

  const t = d.totals;
  const counts: Record<Filter, number> = {
    open: d.rows.filter((r) => inFilter(r, "open")).length,
    overdue: d.rows.filter((r) => inFilter(r, "overdue")).length,
    reported: d.rows.filter((r) => inFilter(r, "reported")).length,
    paid: d.rows.filter((r) => inFilter(r, "paid")).length,
    all: d.rows.length,
  };
  const rows = d.rows.filter((r) => inFilter(r, filter));
  const shown = all ? rows : rows.slice(0, CAP);
  const overdue = [...d.overdue].sort((a, b) => b.amount - a.amount);
  const pick = (f: Filter) => { setFilter(f); setAll(false); setOpen(null); };

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <Reveal className="mx-auto max-w-[1440px] space-y-6 px-6 py-8">
        <Item>
          <PageHead title="Invoices" sub="Written the day the airline confirms." />
          {t.mailed === 0 && <p className="mt-0.5 text-[13px] text-[var(--fg-3)]">Mailing them to customers is switched off for now.</p>}
        </Item>

        <div className="grid grid-cols-4 gap-4">
          <Item><Kpi label="Open" sub={`${t.open} ${t.open === 1 ? "invoice" : "invoices"} waiting for payment`}><CountUp value={t.open_eur} format={fmtEur} /></Kpi></Item>
          <Item>
            <Kpi label="Overdue" tone={t.overdue > 0 ? "text-[var(--bad)]" : undefined} sub={t.overdue ? `${t.overdue} late, call these first` : "Nothing late"}>
              <CountUp value={t.overdue_eur} format={fmtEur} />
            </Kpi>
          </Item>
          <Item><Kpi label="Check the bank" tone={t.reported > 0 ? "text-[var(--warn)]" : undefined} sub="Customer says paid"><CountUp value={t.reported} /></Kpi></Item>
          <Item>
            <Kpi label="Paid" tone={t.paid > 0 ? "text-[var(--ok)]" : undefined} sub={`${t.paid} ${t.paid === 1 ? "invoice" : "invoices"}`}>
              <CountUp value={t.paid_eur} format={fmtEur} />
            </Kpi>
          </Item>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_340px] items-start gap-4">
          <Item className="min-w-0">
            <Card pad={false} className="overflow-hidden">
              <div className="flex items-center gap-3 px-4 py-3">
                <Segmented id="inv-filter" value={filter} onChange={pick} options={[
                  { value: "open", label: "Open", count: counts.open },
                  { value: "overdue", label: "Overdue", count: counts.overdue },
                  { value: "reported", label: "Check the bank", count: counts.reported },
                  { value: "paid", label: "Paid", count: counts.paid },
                  { value: "all", label: "All", count: counts.all },
                ]} />
              </div>
              <div className={`grid ${COLS} gap-3 border-t border-[var(--hair)] px-4 py-2 eyebrow`}>
                <span className="pl-[19px]">Invoice</span><span>Customer</span><span>Route</span>
                <span className="text-right">Amount</span><span className="pl-3">Due</span><span>Status</span><span />
              </div>
              {rows.length === 0 ? (
                <p className="border-t border-[var(--hair)] px-4 py-10 text-center text-[13px] text-[var(--fg-2)]">Nothing here.</p>
              ) : (
                <ul>
                  {shown.map((r) => (
                    <InvoiceRow key={r.thread_id} r={r} now={now} open={open === r.thread_id}
                      onToggle={() => setOpen((o) => (o === r.thread_id ? null : r.thread_id))}
                      onPaid={() => markPaid(r)} busy={busy === r.thread_id} error={errors[r.thread_id] ?? null} />
                  ))}
                </ul>
              )}
              {rows.length > CAP && (
                <div className="flex items-center gap-3 border-t border-[var(--hair)] px-4 py-3 text-[13px] text-[var(--fg-3)]">
                  <span>Showing <span className="tnum">{shown.length}</span> of <span className="tnum">{rows.length}</span></span>
                  <span className="flex-1" />
                  <button onClick={() => setAll((a) => !a)} className="btn btn-ghost h-7 px-2.5 text-[12px]">{all ? "Show fewer" : "Show all"}</button>
                </div>
              )}
            </Card>
          </Item>

          <div className="space-y-4">
            <Item><CallFirst rows={overdue} /></Item>
            <Item><PerCustomer rows={d.byCustomer} /></Item>
          </div>
        </div>
      </Reveal>
    </div>
  );
}
