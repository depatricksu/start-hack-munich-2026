"use client";
// Forwarder dashboard (/dashboard). Server sends the first DashData; this polls /api/dashboard every 5 s.
// Color means state only: green won, blue in progress, amber needs a person, red broken/late, grey over.
import Link from "next/link";
import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowRight, Check } from "lucide-react";
import { WorldMap } from "@/components/world-map";
import type { DashData, FeedItem, Kpi, QueueItem, Shipment, Tone } from "@/lib/dashboard-types";

const TONE: Record<Tone, { chip: string; dot: string; text: string }> = {
  won: { chip: "bg-emerald-400/12 text-emerald-300 ring-emerald-400/20", dot: "bg-emerald-400", text: "text-emerald-300" },
  progress: { chip: "bg-sky-400/12 text-sky-300 ring-sky-400/20", dot: "bg-sky-400", text: "text-sky-300" },
  human: { chip: "bg-amber-400/12 text-amber-300 ring-amber-400/25", dot: "bg-amber-400", text: "text-amber-300" },
  broken: { chip: "bg-red-400/12 text-red-300 ring-red-400/25", dot: "bg-red-400", text: "text-red-300" },
  over: { chip: "bg-white/6 text-zinc-400 ring-white/10", dot: "bg-zinc-500", text: "text-zinc-400" },
  neutral: { chip: "bg-white/6 text-zinc-300 ring-white/10", dot: "bg-zinc-400", text: "text-zinc-300" },
};

const reqHref = (id: number) => `/requests?id=${id}`;
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
const day = (t: number) => new Date(t * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
function ago(s: number): string {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
  return `${Math.floor(s / 86400)} d`;
}
const route = (o: string | null, d: string | null) => `${o ?? "???"} → ${d ?? "???"}`;
const label = (s: string) => s.replaceAll("_", " ");
const shortMail = (m: string) => m.split("@")[0];

function Panel({ title, caption, right, children, className = "" }: {
  title: string; caption?: string; right?: React.ReactNode; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={`rounded-2xl glass p-4 ${className}`}>
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="num text-[11px] uppercase tracking-wider text-zinc-400">{title}</h2>
        {caption && <span className="num text-[10px] text-zinc-600">{caption}</span>}
        <span className="flex-1" />
        {right}
      </div>
      {children}
    </section>
  );
}

function Chip({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${TONE[tone].chip}`}>{children}</span>;
}
function Dot({ tone, className = "" }: { tone: Tone; className?: string }) {
  return <span className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${TONE[tone].dot} ${className}`} />;
}

// ---------- status line + KPIs ----------

function StatusLine({ d, now }: { d: DashData; now: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-1 text-sm">
      <h1 className="text-lg font-semibold tracking-tight text-white">Dashboard</h1>
      <Link href="/requests" className={`inline-flex items-center gap-2 rounded-full px-2.5 py-1 ring-1 ring-inset ${d.needsYou ? TONE.human.chip : TONE.over.chip}`}>
        <Dot tone={d.needsYou ? "human" : "over"} />Needs you: <span className="num font-semibold">{d.needsYou}</span>
      </Link>
      {d.portal.state !== "unknown" && d.portal.at && (
        <span className={`inline-flex items-center gap-2 ${d.portal.state === "down" ? TONE.broken.text : "text-zinc-400"}`}>
          <Dot tone={d.portal.state === "down" ? "broken" : "neutral"} />
          {d.portal.text} <span className="num text-zinc-500">{clock(d.portal.at)}</span>
        </span>
      )}
      {d.lastMail && (
        <span className="text-zinc-400">Last mail <span className="num text-zinc-300">{clock(d.lastMail)}</span> <span className="num text-zinc-500">({ago(now - d.lastMail)} ago)</span></span>
      )}
      <span className="flex-1" />
      <span className={`num text-[11px] ${d.source === "live" ? "text-zinc-500" : "text-amber-300"}`}>
        {d.source === "live" ? (d.windowIsNow ? "live data" : `data ends ${day(d.windowEnd)} ${clock(d.windowEnd)}`) : "demo data"}
      </span>
    </div>
  );
}

function Spark({ data }: { data: (number | null)[] }) {
  const w = 120, h = 28;
  const vals = data.filter((v): v is number => v != null);
  const max = Math.max(1, ...vals);
  const step = w / (data.length - 1);
  const segs: string[] = [];
  let cur = "";
  data.forEach((v, i) => {
    if (v == null) { if (cur) segs.push(cur); cur = ""; return; }
    cur += `${cur ? "L" : "M"}${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`;
  });
  if (cur) segs.push(cur);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-7 w-full" preserveAspectRatio="none" aria-hidden>
      <line x1={0} y1={h - 1} x2={w} y2={h - 1} stroke="rgba(255,255,255,0.08)" />
      {segs.map((p, i) => <path key={i} d={p} fill="none" stroke="rgba(255,255,255,0.55)" strokeWidth={1.3} vectorEffect="non-scaling-stroke" />)}
    </svg>
  );
}

function Tile({ title, k, fmt, windowLabel }: { title: string; k: Kpi; fmt: (v: number) => string; windowLabel: string }) {
  return (
    <Link href="/requests" className="group rounded-2xl glass px-4 py-3.5 transition hover:bg-white/[0.07]">
      <div className="num text-[11px] uppercase tracking-wider text-zinc-500">{title}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="num text-[28px] font-semibold tracking-tight text-white">{k.value == null ? "—" : fmt(k.value)}</span>
        <span className="text-xs text-zinc-500">{k.sub}</span>
      </div>
      <div className="mt-2"><Spark data={k.spark} /></div>
      <div className="mt-1 flex justify-between text-[11px] text-zinc-500">
        <span className="num">{windowLabel}</span><span className="num">{k.allTime}</span>
      </div>
    </Link>
  );
}

// ---------- queue ----------

function NeedsRow({ q, now }: { q: QueueItem; now: number }) {
  return (
    <div className="flex items-start gap-3 rounded-xl bg-amber-400/[0.06] px-3 py-2.5 ring-1 ring-inset ring-amber-400/15">
      <Dot tone="human" className="mt-2" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="num text-sm font-medium text-white">{route(q.origin, q.destination)}</span>
          <span className="truncate text-xs text-zinc-500">{q.customer}</span>
        </div>
        <div className="mt-0.5 text-sm text-amber-200/90">{q.reason}</div>
      </div>
      <span className="num shrink-0 pt-0.5 text-xs text-amber-300">waiting {ago(now - q.received_at)}</span>
      <Link href={reqHref(q.id)} className="shrink-0 rounded-lg bg-amber-400/15 px-2.5 py-1 text-xs font-medium text-amber-200 ring-1 ring-inset ring-amber-400/25 transition hover:bg-amber-400/25">Open</Link>
    </div>
  );
}

function FlightRow({ q, now }: { q: QueueItem; now: number }) {
  const left = Math.round(q.received_at + 360 - now);
  const quoteOut = q.quoted_at != null;
  return (
    <Link href={reqHref(q.id)} className="flex items-center gap-3 rounded-xl px-3 py-2 transition hover:bg-white/5">
      <Dot tone={!quoteOut && left <= 0 ? "broken" : "progress"} />
      <span className="num w-28 shrink-0 text-sm text-white">{route(q.origin, q.destination)}</span>
      <span className="min-w-0 flex-1 truncate text-xs text-zinc-500">{q.customer}</span>
      <Chip tone="progress">{label(String(q.status))}</Chip>
      {quoteOut
        ? <span className="num w-44 shrink-0 whitespace-nowrap text-right text-xs text-zinc-400">quote out {ago(now - (q.quoted_at as number))} ago</span>
        : left > 0
          ? <span className={`num w-44 shrink-0 text-right text-xs ${left < 120 ? "text-sky-200" : "text-sky-300/80"}`}>{Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")} to expiry</span>
          : <span className="num w-44 shrink-0 text-right text-xs text-red-300">past expiry</span>}
    </Link>
  );
}

function DoneRow({ q }: { q: QueueItem }) {
  return (
    <Link href={reqHref(q.id)} className="flex items-center gap-3 rounded-lg px-3 py-1.5 transition hover:bg-white/5">
      <Dot tone={q.tone} />
      <span className="num w-28 shrink-0 text-[13px] text-zinc-200">{route(q.origin, q.destination)}</span>
      <span className="min-w-0 flex-1 truncate text-xs text-zinc-500">{shortMail(q.customer)}</span>
      <span className={`w-20 shrink-0 text-xs ${TONE[q.tone].text}`}>{label(String(q.status))}</span>
      <span className="num w-28 shrink-0 text-right text-[13px] text-zinc-300">{q.price ?? "—"}</span>
    </Link>
  );
}

function Queue({ d, now }: { d: DashData; now: number }) {
  const { needs, flight, done, doneTotal } = d.queue;
  const head = (t: string, n: number, tone: Tone) => (
    <div className="mb-1.5 mt-3 flex items-center gap-2 px-1 first:mt-0">
      <Dot tone={tone} /><span className="text-xs font-medium text-zinc-300">{t}</span><span className="num text-xs text-zinc-500">{n}</span>
    </div>
  );
  return (
    <Panel title="The queue" right={<Link href="/requests" className="text-xs text-zinc-400 hover:text-white">All requests</Link>} className="flex min-h-0 flex-col">
      <div className="rail min-h-0 flex-1 overflow-y-auto pr-1">
        {head("Needs you", needs.length, "human")}
        {needs.length ? <div className="space-y-1.5">{needs.map((q) => <NeedsRow key={q.id} q={q} now={now} />)}</div>
          : <p className="px-3 py-1 text-sm text-zinc-500">Nothing waiting for a person.</p>}
        {head("In flight", flight.length, "progress")}
        {flight.length ? <div>{flight.map((q) => <FlightRow key={q.id} q={q} now={now} />)}</div>
          : <p className="px-3 py-1 text-sm text-zinc-500">No open requests.</p>}
        {head("Done", doneTotal, "over")}
        {done.length ? <div>{done.map((q) => <DoneRow key={q.id} q={q} />)}</div>
          : <p className="px-3 py-1 text-sm text-zinc-500">Nothing finished yet.</p>}
        {doneTotal > done.length && (
          <Link href="/requests" className="mt-1 inline-flex items-center gap-1 px-3 py-1.5 text-xs text-zinc-400 hover:text-white">
            Show all <span className="num">{doneTotal}</span><ArrowRight size={12} />
          </Link>
        )}
      </div>
    </Panel>
  );
}

// ---------- live feed ----------

const DOT_TONE = (s: string, late: boolean): Tone => (late ? "broken" : s === "ok" ? "progress" : s === "declined" ? "over" : s === "asked" ? "neutral" : "human");

function FeedRow({ f, i, now }: { f: FeedItem; i: number; now: number }) {
  const big = i === 0;
  const body = (
    <div className={`flex items-start gap-3 rounded-xl px-3 ${big ? "py-3" : "py-2"} transition hover:bg-white/5`}>
      <Dot tone={f.tone} className={big ? "mt-2" : "mt-1.5"} />
      <div className="min-w-0 flex-1">
        <div className={`${big ? "text-[15px] font-medium text-white" : "text-sm text-zinc-200"} truncate`}>
          <span className={f.tone === "neutral" ? "" : TONE[f.tone].text}>{f.label}</span>
        </div>
        {(f.detail || f.dots) && (
          <div className="mt-0.5 flex items-center gap-2 text-xs text-zinc-500">
            {f.dots && (
              <span className="flex items-center gap-1" title={f.dots.map((x) => `${x.carrier}: ${x.status}${x.late ? " (late)" : ""}`).join("\n")}>
                {f.dots.map((x, k) => <Dot key={k} tone={DOT_TONE(x.status, x.late)} />)}
                <span className="num ml-1">{f.dots.length}</span>
              </span>
            )}
            {f.detail && <span className="num truncate">{f.detail}</span>}
          </div>
        )}
      </div>
      <span className="num shrink-0 pt-0.5 text-[11px] text-zinc-500">{ago(now - f.ts)}</span>
    </div>
  );
  return f.thread ? <Link href={reqHref(f.thread)}>{body}</Link> : body;
}

function Feed({ d, now }: { d: DashData; now: number }) {
  const reduce = useReducedMotion();
  return (
    <Panel title="Live activity" caption="newest on top" className="flex min-h-0 flex-col">
      {d.feed.length === 0 ? <p className="text-sm text-zinc-500">No activity yet.</p> : (
        <ul className="min-h-0 flex-1 overflow-hidden"
          style={{ maskImage: "linear-gradient(to bottom, #000 62%, transparent 100%)", WebkitMaskImage: "linear-gradient(to bottom, #000 62%, transparent 100%)" }}>
          <AnimatePresence initial={false}>
            {d.feed.slice(0, 14).map((f, i) => (
              <motion.li key={f.key} layout={!reduce} initial={reduce ? false : { opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
                exit={reduce ? undefined : { opacity: 0 }} transition={{ duration: 0.25 }}>
                <FeedRow f={f} i={i} now={now} />
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </Panel>
  );
}

// ---------- shipments ----------

const STEPS = ["Booked", "Picked up", "Departed", "Arrived", "Delivered"];

function StepBar({ s }: { s: Shipment }) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex gap-0.5">
        {STEPS.map((_, i) => <span key={i} className={`h-1 w-2 rounded-full ${i <= s.stepIndex ? "bg-emerald-400/70" : "bg-white/10"}`} />)}
      </div>
      <span className="whitespace-nowrap text-xs text-zinc-300">{s.step}</span>
    </div>
  );
}

function Shipments({ d }: { d: DashData }) {
  const arcs = d.shipments.slice(0, 10).map((s) => ({ key: s.ref, from: s.origin, to: s.destination, tone: (s.step === "Delivered" ? "over" : "won") as "won" | "over" }));
  return (
    <Panel title="Shipments in motion" caption="step + ETA simulated from booking time + transit days · no live flight feed"
      right={d.shipmentsTotal > 0 ? <span className="num text-xs text-zinc-500">{d.shipments.length} latest of {d.shipmentsTotal} bookings</span> : undefined}>
      {d.shipments.length === 0 ? <p className="text-sm text-zinc-500">No confirmed bookings yet.</p> : (
        <div className="grid grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)] gap-4">
          <div className="flex items-center rounded-xl bg-black/20 p-2"><WorldMap arcs={arcs} className="h-auto w-full" /></div>
          <div className="rail max-h-[340px] overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-[#0d0e10]/90 backdrop-blur">
                <tr className="num text-[10px] uppercase tracking-wider text-zinc-500">
                  <th className="py-1.5 pl-2 font-normal">Booking</th><th className="font-normal">Customer</th><th className="font-normal">Route</th>
                  <th className="font-normal">Airline</th><th className="whitespace-nowrap font-normal">Step <span className="normal-case text-zinc-600">(sim)</span></th>
                  <th className="whitespace-nowrap pr-2 text-right font-normal">ETA <span className="normal-case text-zinc-600">(sim)</span></th>
                </tr>
              </thead>
              <tbody>
                {d.shipments.map((s) => (
                  <tr key={s.ref} className="border-t border-line align-top">
                    <td className="py-2 pl-2">
                      <Link href={reqHref(s.thread)} className="num text-[13px] text-emerald-300 hover:underline">{s.ref}</Link>
                      <div className="mt-0.5 flex gap-2 whitespace-nowrap text-[10px] text-zinc-500">
                        {s.tracking_answered && <span className="inline-flex items-center gap-0.5"><Check size={10} />tracking answered</span>}
                        {s.customer_informed && <span className="inline-flex items-center gap-0.5"><Check size={10} />informed</span>}
                      </div>
                    </td>
                    <td className="max-w-[120px] truncate py-2 pr-2 text-xs text-zinc-400">{shortMail(s.customer)}</td>
                    <td className="num whitespace-nowrap py-2 pr-3 text-[13px] text-zinc-200">{route(s.origin, s.destination)}</td>
                    <td className="max-w-[120px] truncate py-2 pr-2 text-xs text-zinc-400" title={s.airline ?? ""}>{s.airline ?? "—"}</td>
                    <td className="py-2"><StepBar s={s} /></td>
                    <td className="num whitespace-nowrap py-2 pl-2 pr-2 text-right text-xs text-zinc-400">{s.eta ? `${day(s.eta)} ${clock(s.eta)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Panel>
  );
}

// ---------- bottom tables ----------

const Th = ({ children, right }: { children: React.ReactNode; right?: boolean }) =>
  <th className={`num pb-1.5 text-[10px] font-normal uppercase tracking-wider text-zinc-500 ${right ? "text-right" : ""}`}>{children}</th>;
const n0 = (v: number | null, suf = "") => (v == null ? "—" : `${Math.round(v).toLocaleString("en-GB")}${suf}`);

function Pricing({ d }: { d: DashData }) {
  const rows = [...d.pricing.lanes, d.pricing.total];
  return (
    <Panel title="Pricing" caption="customers who asked for the cheapest">
      {d.pricing.total.quotes === 0 ? <p className="text-sm text-zinc-500">No priced quotes yet.</p> : (
        <table className="w-full text-sm">
          <thead><tr><Th>Lane</Th><Th right>Quotes</Th><Th right>Cheapest</Th><Th right>Over</Th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.lane} className={`border-t border-line ${i === rows.length - 1 ? "text-white" : "text-zinc-300"}`}>
                <td className="num py-1.5 text-[13px]">{r.lane}</td>
                <td className="num text-right text-[13px]">{r.quotes}</td>
                <td className="num text-right text-[13px]" title={`${r.cheapest} of ${r.asks} cheapest-asks got the cheapest option`}>
                  {r.asks ? `${Math.round((r.cheapest / r.asks) * 100)}%` : "—"} <span className="text-zinc-600">{r.asks ? `${r.cheapest}/${r.asks}` : ""}</span>
                </td>
                <td className="num text-right text-[13px]">{r.medianOverPct == null ? "—" : `+${r.medianOverPct.toFixed(1)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-[11px] text-zinc-500">Cheapest = our quote was the lowest option we found. Over = median % above it.</p>
    </Panel>
  );
}

function Carriers({ d }: { d: DashData }) {
  return (
    <Panel title="Carriers" caption="flagged first · price requests by mail">
      {d.carriers.length === 0 ? <p className="text-sm text-zinc-500">No bids asked yet.</p> : (
        <table className="w-full text-sm">
          <thead><tr><Th>Carrier</Th><Th right>Replied</Th><Th right>Median reply</Th><Th right>Median price</Th></tr></thead>
          <tbody>
            {d.carriers.map((c) => (
              <tr key={`${c.carrier}-${c.role}`} className="border-t border-line text-zinc-300">
                <td className="max-w-[170px] py-1.5">
                  <div className="flex items-center gap-1.5 truncate text-[13px]">
                    {c.flag && <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${c.flag === "red" ? "bg-red-400" : "bg-amber-400"}`} />}
                    <span className="truncate">{c.carrier}</span>
                  </div>
                  <div className={`truncate text-[10px] ${c.flag === "red" ? "text-red-300" : c.flag ? "text-amber-300" : "text-zinc-500"}`} title={c.reasons.join(" · ")}>
                    {c.flag ? c.reasons[0] : c.role === "ratedesk" ? "rate desk" : c.role}
                  </div>
                </td>
                <td className="num text-right text-[13px]">{c.replied}<span className="text-zinc-600">/{c.asked}</span></td>
                <td className="num text-right text-[13px]">{c.medianReplyS == null ? "—" : ago(c.medianReplyS)}</td>
                <td className="num text-right text-[13px]">{c.medianEur == null ? "—" : `${n0(c.medianEur)} EUR`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function Customers({ d }: { d: DashData }) {
  return (
    <Panel title="Customers" caption="by requests">
      {d.customers.length === 0 ? <p className="text-sm text-zinc-500">No customers yet.</p> : (
        <table className="w-full text-sm">
          <thead><tr><Th>Customer</Th><Th right>Requests</Th><Th right>Accepted</Th><Th right>Lang</Th></tr></thead>
          <tbody>
            {d.customers.map((c) => (
              <tr key={c.customer} className="border-t border-line text-zinc-300">
                <td className="max-w-[170px] truncate py-1.5 text-[13px]" title={c.customer}>{shortMail(c.customer)}</td>
                <td className="num text-right text-[13px]"><Link href="/requests" className="hover:text-white">{c.requests}</Link></td>
                <td className="num text-right text-[13px]">
                  {c.quotes ? <span className={c.won ? TONE.won.text : ""}>{Math.round((c.won / c.quotes) * 100)}%</span> : "—"}
                  <span className="text-zinc-600"> {c.won}/{c.quotes}</span>
                </td>
                <td className="num text-right text-[11px] uppercase text-zinc-400">{c.languages.join(" ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

// ---------- page ----------

export function DashboardView({ initial }: { initial: DashData }) {
  const [d, setD] = useState(initial);
  const [now, setNow] = useState(initial.now);
  useEffect(() => {
    let alive = true;
    const load = () => fetch("/api/dashboard", { cache: "no-store" }).then((r) => r.json())
      .then((x: DashData) => { if (alive && x && x.kpis) setD(x); }).catch(() => {});
    const poll = setInterval(load, 5000);
    const tick = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => { alive = false; clearInterval(poll); clearInterval(tick); };
  }, []);

  const win = d.windowIsNow ? "last 24 h" : "24 h to last data";
  const eur = (v: number) => `${v.toLocaleString("en-GB")} €`;
  return (
    <div className="h-full overflow-y-auto p-2">
      <div className="mx-auto max-w-[1400px] space-y-3 px-2 py-3">
        <StatusLine d={d} now={now} />
        <div className="grid grid-cols-4 gap-3">
          <Tile title="Requests" k={d.kpis.requests} fmt={(v) => String(v)} windowLabel={win} />
          <Tile title="Accepted" k={d.kpis.accepted} fmt={(v) => `${v}%`} windowLabel={win} />
          <Tile title="Booked value" k={d.kpis.booked} fmt={eur} windowLabel={win} />
          <Tile title="Avg shipment value" k={d.kpis.avg} fmt={eur} windowLabel={win} />
        </div>
        <div className="grid h-[560px] grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] gap-3">
          <Queue d={d} now={now} />
          <Feed d={d} now={now} />
        </div>
        <Shipments d={d} />
        <div className="grid grid-cols-3 gap-3">
          <Pricing d={d} />
          <Carriers d={d} />
          <Customers d={d} />
        </div>
      </div>
    </div>
  );
}
