"use client";
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Check, Copy } from "lucide-react";
import type { Line, Message, ShipmentDetail, ShipmentRow, ShipmentsData, Step } from "@/lib/shipments";
import { carrierHref, ShipmentCarrierUpdates } from "@/components/carrier-updates";

const short = (m: string) => m.split("@")[0];
const at = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const day = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) : "");
const eur = (v: number, c = "EUR") => `${v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${c}`;
const text = (l: Line) => l.map((s) => s.t).join("");

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="rounded-2xl glass px-5 py-4">
      <div className="num text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`num mt-1.5 text-3xl font-semibold tracking-tight ${tone ?? "text-white"}`}>{value}</div>
      <div className="mt-1 text-xs text-zinc-500">{sub}</div>
    </div>
  );
}

// Color = state: green done, blue the next step in progress, red a problem, grey not yet / over.
function stepTone(s: Step, next: boolean, over: boolean): string {
  if (over) return "bg-white/10";
  if (s.problem) return "bg-red-400/70";
  if (s.done) return s.sim ? "bg-emerald-400/35" : "bg-emerald-400/70";
  if (next) return "bg-sky-400/60";
  return "bg-white/10";
}

function Strip({ r }: { r: ShipmentRow }) {
  const over = r.status === "cancelled";
  const real = r.steps.filter((s) => !s.sim), sim = r.steps.filter((s) => s.sim);
  const next = real.find((s) => !s.done)?.key;
  return (
    <div className="flex items-center gap-1" aria-label="Shipment steps">
      {real.map((s) => <span key={s.key} title={`${s.label}${s.done ? ` · ${at(s.at)}` : ""}`} className={`h-1.5 w-5 rounded-full ${stepTone(s, s.key === next, over)}`} />)}
      <span className="mx-1 h-3 w-px bg-white/10" />
      {sim.map((s) => <span key={s.key} title={`${s.label} (sim) · ${at(s.at)}`} className={`h-1.5 w-3.5 rounded-full ${stepTone(s, false, over)}`} />)}
      <span className="ml-1 text-[10px] text-zinc-600">sim</span>
    </div>
  );
}

function StatusChip({ r }: { r: ShipmentRow }) {
  const c = r.status === "cancelled" ? { l: "Cancelled", cls: "bg-white/5 text-zinc-500 ring-white/10" }
    : r.status === "booked" ? { l: "Waiting for airline", cls: "bg-sky-400/12 text-sky-300 ring-sky-400/25" }
    : { l: "Confirmed", cls: "bg-emerald-400/12 text-emerald-300 ring-emerald-400/25" };
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${c.cls}`}>{c.l}</span>;
}

function StateChip({ m }: { m: Message }) {
  return m.state === "sent"
    ? <span className="inline-flex rounded-full bg-emerald-400/12 px-2 py-0.5 text-[11px] font-medium text-emerald-300 ring-1 ring-inset ring-emerald-400/25">Sent {at(m.sent_at)}</span>
    : <span className="inline-flex rounded-full bg-white/6 px-2 py-0.5 text-[11px] font-medium text-zinc-300 ring-1 ring-inset ring-white/12">Draft</span>;
}

// From our record: plain text with a muted underline. Still open: amber placeholder.
function Segs({ line }: { line: Line }) {
  return (
    <>
      {line.map((s, i) => s.k === "record"
        ? <span key={i} className="text-zinc-100 underline decoration-white/25 decoration-dotted underline-offset-[3px]">{s.t}</span>
        : s.k === "open"
          ? <span key={i} className="rounded bg-amber-400/12 px-1 text-amber-300 ring-1 ring-inset ring-amber-400/25">{s.t}</span>
          : <span key={i}>{s.t}</span>)}
    </>
  );
}

function MessageCard({ m }: { m: Message }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const parts = [m.address ? `To: ${m.address}` : `To: ${text(m.to)}`, `Subject: ${text(m.subject)}`, "", ...m.body.map(text)];
    navigator.clipboard?.writeText(parts.join("\n")).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1400); }).catch(() => {});
  };
  return (
    <div className="rounded-xl bg-white/[0.02] p-4 ring-1 ring-inset ring-white/7">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="num text-[11px] uppercase tracking-wider text-zinc-500">{m.role}</span>
            <span className="text-[11px] text-zinc-600">· {m.when}</span>
          </div>
          <div className="mt-0.5 text-sm font-semibold text-white">{m.title}</div>
          <p className="mt-0.5 text-xs text-zinc-500">{m.why}</p>
        </div>
        <StateChip m={m} />
        <button onClick={copy} title="Copy this message" className="flex items-center gap-1 rounded-md glass-2 px-2 py-1 text-[11px] text-zinc-300 transition hover:text-white">
          {copied ? <Check size={12} /> : <Copy size={12} />}{copied ? "Copied" : "Copy"}
        </button>
      </div>
      <div className="mt-3 space-y-0.5 text-[13px] text-zinc-400">
        <div><span className="inline-block w-16 text-zinc-600">To</span><Segs line={m.to} />
          {m.address ? <span className="num ml-2 text-xs text-zinc-500">{m.address}</span>
            : !m.recipients && <span className="ml-2 rounded bg-amber-400/12 px-1 text-xs text-amber-300 ring-1 ring-inset ring-amber-400/25">address open</span>}
        </div>
        {m.recipients && (
          <div className="pl-16 text-xs text-zinc-500">
            {m.recipients.map((r) => (
              <div key={r.name}>{r.name} <span className="num">{r.address ?? ""}</span>{r.offer && <span className="num text-zinc-600"> · offered {r.offer} (not in the mail)</span>}</div>
            ))}
            <div className="text-zinc-600">Each gets the mail on its own.</div>
          </div>
        )}
        <div><span className="inline-block w-16 text-zinc-600">Subject</span><span className="text-zinc-200"><Segs line={m.subject} /></span></div>
      </div>
      <pre className="num mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-black/20 p-3 text-[12.5px] leading-relaxed text-zinc-400 ring-1 ring-inset ring-white/6">
        {m.body.map((l, i) => <div key={i}>{l.length ? <Segs line={l} /> : " "}</div>)}
      </pre>
    </div>
  );
}

function Lifecycle({ d }: { d: ShipmentDetail }) {
  const over = d.status === "cancelled";
  const next = d.steps.filter((s) => !s.sim).find((s) => !s.done)?.key;
  return (
    <ol className="space-y-1.5">
      {d.steps.map((s, i) => {
        const tone = stepTone(s, s.key === next, over);
        const first = s.sim && !d.steps[i - 1]?.sim;
        return (
          <li key={s.key}>
            {first && <div className="mb-1.5 mt-3 text-[11px] text-zinc-500">Flight (sim): estimated from booking time + transit days. The game has no flight-status feed.</div>}
            <div className="flex items-center gap-3 text-[13px]">
              <span className={`h-2 w-2 shrink-0 rounded-full ${tone}`} />
              <span className={s.done ? "text-zinc-200" : "text-zinc-500"}>{s.label}{s.sim && <span className="text-zinc-600"> (sim)</span>}</span>
              <span className={`num ml-auto text-xs ${s.problem ? "text-red-300" : "text-zinc-500"}`}>
                {s.problem ? "overdue" : s.done ? at(s.at) : s.sim && s.at ? `expected ${at(s.at)}` : "not yet"}
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Detail({ d }: { d: ShipmentDetail }) {
  const inv = d.invoice;
  const invTone = !inv ? "" : inv.status === "paid" ? "text-emerald-300" : inv.overdue_days > 0 || inv.status === "overdue_human" ? "text-red-300"
    : inv.status === "paid_reported" ? "text-amber-300" : inv.status === "cancelled" ? "text-zinc-500" : "text-sky-300";
  const invLabel = !inv ? "" : inv.status === "paid" ? `Paid ${day(inv.paid_at)}` : inv.status === "cancelled" ? "Cancelled"
    : inv.status === "paid_reported" ? "Customer says paid, check the bank" : inv.overdue_days > 0 ? `${inv.overdue_days} days overdue` : "Open";
  const drafts = d.messages.filter((m) => m.state === "draft").length;
  return (
    <div className="space-y-3">
      <section className="rounded-2xl glass p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="num text-2xl font-semibold tracking-tight text-white">{d.origin ?? "?"} → {d.destination ?? "?"}</div>
            <div className="mt-1 text-sm text-zinc-400">{d.company} <span className="text-zinc-600">· {d.customer}</span></div>
            <div className="mt-1 flex flex-wrap gap-x-4 text-xs text-zinc-500">
              <span>Booking <span className="num text-zinc-300">{d.booking_ref ?? "—"}</span></span>
              <span>Our ref <span className="num text-zinc-300">{d.ref}</span></span>
              <span>Airline {d.airline ? <Link href={carrierHref(d.airline)} className="text-zinc-300 hover:text-white hover:underline">{d.airline}</Link> : <span className="text-zinc-300">—</span>}</span>
              {d.trucker && <span>Trucker <Link href={carrierHref(d.trucker)} className="text-zinc-300 hover:text-white hover:underline">{d.trucker}</Link></span>}
              {d.price && <span>Price <span className="num text-zinc-300">{d.price}</span></span>}
            </div>
          </div>
          <StatusChip r={d} />
          <Link href={`/requests?id=${d.thread}`} className="rounded-md glass-2 px-2.5 py-1 text-xs text-zinc-300 transition hover:text-white">Open request</Link>
        </div>

        {d.watch.map((w) => (
          <div key={w.carrier} className={`mt-3 flex items-center gap-3 rounded-xl px-4 py-2.5 ring-1 ring-inset ${w.level === "red" ? "bg-red-400/[0.06] ring-red-400/25" : "bg-amber-400/[0.06] ring-amber-400/25"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${w.level === "red" ? "bg-red-400" : "bg-amber-400"}`} />
            <span className="text-sm text-white">Watch {w.carrier}</span>
            <span className={`text-xs ${w.level === "red" ? "text-red-300" : "text-amber-300"}`}>{w.reasons.join(" · ")}</span>
          </div>
        ))}

        <div className="mt-4 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-5">
          <div><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Steps</h3><Lifecycle d={d} /></div>
          <div className="space-y-3">
            {d.facts.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">From our records</h3>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px]">
                  {d.facts.map((f) => (
                    <div key={f.k} className="contents">
                      <dt className="text-zinc-500">{f.k}</dt>
                      <dd className={f.open ? "text-amber-300" : "text-zinc-200"}>{f.v}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Invoice</h3>
              {inv ? (
                <Link href="/invoices" className="flex items-center gap-3 rounded-xl glass-2 px-3 py-2 transition hover:bg-white/5">
                  <span className="num text-[13px] text-white">{inv.number}</span>
                  <span className="num text-[13px] text-zinc-300">{eur(inv.amount, inv.currency)}</span>
                  <span className={`ml-auto text-xs ${invTone}`}>{invLabel}{!inv.sent && inv.status !== "paid" && <span className="ml-1.5 text-zinc-500">draft</span>}</span>
                </Link>
              ) : <p className="text-[13px] text-zinc-500">No invoice yet. It is written when the airline confirms.</p>}
            </div>
          </div>
        </div>
      </section>

      <ShipmentCarrierUpdates thread={d.thread} />

      <section className="rounded-2xl glass p-5">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-white">After the yes</h2>
          <span className="num text-xs text-zinc-500">{d.messages.length - drafts} sent · {drafts} drafts</span>
        </div>
        <p className="mt-0.5 text-xs text-zinc-500">
          The messages a forwarder still writes by hand, built from our records. Nothing here is sent.{" "}
          <span className="text-zinc-300 underline decoration-white/25 decoration-dotted underline-offset-[3px]">Underlined</span> = from our records,{" "}
          <span className="rounded bg-amber-400/12 px-1 text-amber-300 ring-1 ring-inset ring-amber-400/25">amber</span> = still open.
          “Sent” only where our log shows the mail went out.
        </p>
        {d.note && <p className="mt-2 text-[13px] text-zinc-400">{d.note}</p>}
        <div className="mt-3 space-y-2.5">
          {d.messages.map((m) => <MessageCard key={m.id} m={m} />)}
          {d.messages.length === 0 && <p className="text-sm text-zinc-500">No messages for this shipment.</p>}
        </div>
      </section>
    </div>
  );
}

export default function ShipmentsPage() {
  return <Suspense fallback={null}><ShipmentsView /></Suspense>;
}

function ShipmentsView() {
  const router = useRouter();
  const urlId = Number(useSearchParams().get("id")) || null;
  const [data, setData] = useState<ShipmentsData | null>(null);
  const [detail, setDetail] = useState<{ id: number; s: ShipmentDetail | null } | null>(null);

  const load = useCallback(() => fetch("/api/shipments", { cache: "no-store" }).then((r) => r.json()).then(setData).catch(() => {}), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const activeId = urlId ?? data?.rows[0]?.thread ?? null;
  useEffect(() => {
    if (!activeId) return;
    let alive = true;
    const get = () => fetch(`/api/shipments/${activeId}`, { cache: "no-store" }).then((r) => r.json())
      .then((j: { shipment: ShipmentDetail | null }) => { if (alive) setDetail({ id: activeId, s: j.shipment }); }).catch(() => {});
    get();
    const t = setInterval(get, 10000);
    return () => { alive = false; clearInterval(t); };
  }, [activeId]);

  if (!data) return <div className="p-8 text-sm text-zinc-500">Loading shipments…</div>;
  if (!data.available || data.rows.length === 0) {
    return (
      <div className="h-full p-2"><div className="h-full rounded-2xl glass p-8">
        <h1 className="text-xl font-semibold text-white">Shipments</h1>
        <p className="mt-2 max-w-xl text-sm text-zinc-400">No bookings yet. A shipment shows here once a customer says yes and we book the flight.</p>
      </div></div>
    );
  }
  const t = data.totals;
  const loaded = detail && detail.id === activeId ? detail : null;

  return (
    <div className="h-full overflow-y-auto p-2">
      <div className="mx-auto max-w-[1400px] space-y-3 px-2 py-3">
        <div className="px-1">
          <h1 className="text-xl font-semibold tracking-tight text-white">Shipments</h1>
          <p className="mt-0.5 text-sm text-zinc-500">Everything after the customer said yes. Messages are drafts for you to read; nothing is sent from here.</p>
        </div>

        <div className="grid grid-cols-4 gap-3">
          <Tile label="Active shipments" value={String(t.active)} sub={t.cancelled ? `${t.cancelled} cancelled` : "booked or confirmed"} />
          <Tile label="Waiting for airline" value={String(t.waiting)} sub="booked, not confirmed yet" tone={t.waiting ? "text-sky-300" : "text-white"} />
          <Tile label="Messages to send" value={String(t.drafts)} sub="drafts after the yes" tone={t.drafts ? "text-amber-300" : "text-white"} />
          <Tile label="Invoiced / paid" value={`${t.invoiced} / ${t.paid}`} sub="invoices written / paid" tone={t.paid ? "text-emerald-300" : "text-white"} />
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] items-start gap-3">
          <section className="rounded-2xl glass p-2">
            <div className="flex items-center px-2 py-1.5 text-[11px] uppercase tracking-wide text-zinc-500">
              <span>Newest first</span><span className="num ml-auto">{data.rows.length}</span>
            </div>
            <div className="space-y-0.5">
              {data.rows.map((r) => (
                <button key={r.thread} onClick={() => router.replace(`/shipments?id=${r.thread}`, { scroll: false })}
                  className={`block w-full rounded-xl px-3 py-2.5 text-left transition ${r.thread === activeId ? "glass-2" : "hover:bg-white/[0.04]"}`}>
                  <div className="flex items-center gap-2">
                    <span className="num text-[13px] text-white">{r.booking_ref ?? r.ref}</span>
                    <span className="num text-[13px] text-zinc-300">{r.origin ?? "?"} → {r.destination ?? "?"}</span>
                    {r.flag && <span className={`h-1.5 w-1.5 rounded-full ${r.flag === "red" ? "bg-red-400" : "bg-amber-400"}`} title="Carrier to watch" />}
                    <span className="ml-auto"><StatusChip r={r} /></span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-zinc-500">
                    <span className="truncate">{short(r.customer)}</span>
                    <span className="truncate text-zinc-600">· {r.airline ?? "—"}{r.trucker ? ` · ${r.trucker}` : ""}</span>
                    <span className="num ml-auto shrink-0">{day(r.at)}</span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-3">
                    <Strip r={r} />
                    {r.drafts > 0 && <span className="num ml-auto text-[11px] text-zinc-500">{r.drafts} drafts</span>}
                  </div>
                </button>
              ))}
            </div>
          </section>

          <div>
            {loaded?.s ? <Detail d={loaded.s} />
              : <div className="rounded-2xl glass p-8 text-sm text-zinc-500">{loaded ? "No shipment with this number." : activeId ? "Loading…" : "Select a shipment."}</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
