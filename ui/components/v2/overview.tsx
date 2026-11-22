"use client";
// Relay v2 Overview: four small glass tiles, what Relay is working on today, live activity, shipments.
// Kept small and quiet on purpose (Erik, 22 Nov): one grey for text, colour only as a small dot for state.
// Pricing, carrier and customer tables are one question to Ask Relay.
import Link from "next/link";
import { useId, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { WorldMap } from "@/components/world-map";
import type { DashData, FeedItem, QueueItem, Tone as DTone } from "@/lib/dashboard-types";
import type { OffTrack } from "@/lib/exceptions";
import {
  Badge, Card, CardHead, CountUp, EASE, Item, Reveal, TONE_DOT, Tone,
  ago, clock, day, route, shortMail, statusInfo, useJson, useNow,
} from "@/components/v2/ui";

const TONE: Record<DTone, Tone> = { won: "ok", progress: "info", human: "warn", broken: "bad", over: "idle", neutral: "idle" };
const reqHref = (id: number) => `/v2/requests?id=${id}`;

// ---------- numbers ----------

// The line draws itself in, a soft fill fades in under it, and the newest point keeps breathing.
function Spark({ data }: { data: (number | null)[] }) {
  const id = useId();
  const w = 160, h = 30;
  const vals = data.filter((v): v is number => v != null);
  const max = Math.max(1, ...vals);
  const step = w / Math.max(1, data.length - 1);
  const pts: [number, number][] = [];
  data.forEach((v, i) => { if (v != null) pts.push([i * step, h - 3 - (v / max) * (h - 8)]); });
  if (pts.length < 2) return <div className="h-7" />;
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  const [ex, ey] = pts[pts.length - 1];
  const area = `${d}L${ex.toFixed(1)},${h}L${pts[0][0].toFixed(1)},${h}Z`;
  return (
    <div className="relative h-7 w-full">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-full w-full overflow-visible" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#fff" stopOpacity="0.16" /><stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
        </defs>
        <motion.path d={area} fill={`url(#${id})`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.9, delay: 0.8 }} />
        <motion.path d={d} fill="none" stroke="var(--fg-2)" strokeWidth={1.4} strokeLinecap="round" vectorEffect="non-scaling-stroke"
          initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.5, ease: EASE, delay: 0.15 }} />
      </svg>
      {/* An HTML dot, not an SVG circle: the SVG is stretched to the tile's width and would squash a circle. */}
      <motion.span initial={{ opacity: 0, scale: 0 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.3, delay: 1.5 }}
        className="absolute flex h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2" style={{ left: `${(ex / w) * 100}%`, top: `${(ey / h) * 100}%` }}>
        <span className="absolute inset-0 animate-ping rounded-full bg-[var(--fg)] opacity-60 motion-reduce:hidden" />
        <span className="relative h-1.5 w-1.5 rounded-full bg-[var(--fg)]" />
      </motion.span>
    </div>
  );
}

function Stat({ label, value, format, sub, spark, foot }: { label: string; value: number | null; format: (v: number) => string; sub: string; spark?: (number | null)[]; foot?: React.ReactNode }) {
  return (
    <Item>
      <Card pad={false} className="lg flex h-full flex-col px-4 py-3.5">
        <div className="text-[12px] text-[var(--fg-2)]">{label}</div>
        <div className="mt-1.5 text-[24px] font-semibold leading-none tracking-[-0.04em] text-[var(--fg)]">
          {value == null ? <span className="tnum">-</span> : <CountUp value={value} format={format} />}
        </div>
        <div className="mt-1.5 text-[12px] text-[var(--fg-3)]">{sub}</div>
        {spark && <div className="mt-auto pt-2.5"><Spark data={spark} /></div>}
        {foot && <div className="mt-auto pt-2.5">{foot}</div>}
      </Card>
    </Item>
  );
}

// ---------- today's work ----------

// A status as a small dot and a word: the only colour in a row.
function Quiet({ status }: { status: string }) {
  const [label, tone] = statusInfo(status);
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-[12px] text-[var(--fg-2)]">
      <span className={`h-1.5 w-1.5 rounded-full ${TONE_DOT[tone]}`} />{label}
    </span>
  );
}

function Group({ title, count, dot = "bg-[var(--fg-3)]", children }: { title: string; count: number; dot?: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-white/[0.06] pt-3 first:border-t-0 first:pt-0">
      <div className="mb-1 flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
        <h3 className="text-[12px] font-medium text-[var(--fg-2)]">{title}</h3>
        <span className="tnum text-[12px] text-[var(--fg-3)]">{count}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="group flex items-center gap-3 rounded-full px-3 py-1.5 transition-colors hover:bg-white/[0.05]">
      {children}
      <ArrowUpRight size={13} className="shrink-0 text-[var(--fg-3)] opacity-0 transition-opacity group-hover:opacity-100" />
    </Link>
  );
}

function OffRow({ x, now }: { x: OffTrack; now: number }) {
  return (
    <Row href={x.href}>
      <span className="tnum w-24 shrink-0 text-[13px] font-medium text-[var(--fg)]">{x.route ?? "-"}</span>
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg-2)]">{x.title} <span className="text-[var(--fg-3)]">· {shortMail(x.customer)}</span></span>
      <span className="tnum shrink-0 text-[12px] text-[var(--fg-3)]">{ago(now - x.since)}</span>
    </Row>
  );
}

function FlightRow({ q, now }: { q: QueueItem; now: number }) {
  return (
    <Row href={reqHref(q.id)}>
      <span className="tnum w-24 shrink-0 text-[13px] font-medium text-[var(--fg)]">{route(q.origin, q.destination)}</span>
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg-2)]">{shortMail(q.customer)}</span>
      <Quiet status={String(q.status)} />
      <span className="tnum w-28 shrink-0 whitespace-nowrap text-right text-[12px] text-[var(--fg-3)]">
        {q.quoted_at != null ? `quoted ${ago(now - q.quoted_at)} ago` : `${ago(now - q.received_at)} old`}
      </span>
    </Row>
  );
}

function DoneRow({ q }: { q: QueueItem }) {
  return (
    <Row href={reqHref(q.id)}>
      <span className="tnum w-24 shrink-0 text-[13px] text-[var(--fg)]">{route(q.origin, q.destination)}</span>
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg-2)]">{shortMail(q.customer)}</span>
      <span className="tnum shrink-0 text-right text-[13px] text-[var(--fg-2)]">{q.price ?? "-"}</span>
      <span className="flex w-24 shrink-0 justify-end"><Quiet status={String(q.status)} /></span>
    </Row>
  );
}

// Only what is going on: requests being worked on, shipments off plan (when there are any), the last ones done.
// A request Relay stopped on is not listed here; the bell in the top bar shows it.
function Today({ d, off, now }: { d: DashData; off: OffTrack[]; now: number }) {
  const { done, doneTotal } = d.queue;
  // A request that is already in "Off track" (e.g. waiting for documents) is not listed twice.
  const offIds = new Set(off.map((x) => x.href));
  const flight = d.queue.flight.filter((q) => !offIds.has(reqHref(q.id)));
  const quiet = flight.length === 0 && off.length === 0;
  return (
    <Card pad={false} className="lg h-full px-4 py-3.5">
      <CardHead title="Today" hint={quiet ? "nothing open right now" : "what Relay is working on"}
        right={<Link href="/v2/requests" className="text-[12px] text-[var(--fg-2)] hover:text-[var(--fg)]">All requests</Link>} />
      <div className="space-y-3">
        {flight.length > 0 && (
          <Group title="In flight" count={flight.length} dot="bg-[var(--fg)]">
            <div>{flight.map((q) => <FlightRow key={q.id} q={q} now={now} />)}</div>
          </Group>
        )}
        {off.length > 0 && (
          <Group title="Off track" count={off.length} dot={off.some((x) => x.tone === "bad") ? "bg-[var(--bad)]" : "bg-[var(--warn)]"}>
            <div>{off.slice(0, 3).map((x) => <OffRow key={x.id} x={x} now={now} />)}</div>
          </Group>
        )}
        <Group title="Just finished" count={Math.min(6, done.length)}>
          {done.length === 0 ? <p className="px-3 py-1 text-[13px] text-[var(--fg-3)]">Nothing finished yet.</p> : (
            <div>{done.slice(0, 6).map((q) => <DoneRow key={q.id} q={q} />)}</div>
          )}
          {doneTotal > 6 && (
            <Link href="/v2/requests?filter=done" className="mt-0.5 inline-flex items-center gap-1 px-3 py-1 text-[12px] text-[var(--fg-2)] hover:text-[var(--fg)]">
              All <span className="tnum">{doneTotal}</span> finished <ArrowRight size={12} />
            </Link>
          )}
        </Group>
      </div>
    </Card>
  );
}

// ---------- live activity ----------

function Feed({ items, now }: { items: FeedItem[]; now: number }) {
  return (
    <Card pad={false} className="lg flex h-full min-h-0 flex-col px-4 py-3.5">
      <CardHead title="Live activity" hint="newest first" />
      {items.length === 0 ? <p className="text-[13px] text-[var(--fg-3)]">No activity yet.</p> : (
        <ol className="relative min-h-0 flex-1 overflow-hidden"
          style={{ maskImage: "linear-gradient(to bottom, #000 78%, transparent)", WebkitMaskImage: "linear-gradient(to bottom, #000 78%, transparent)" }}>
          <AnimatePresence initial={false}>
            {items.slice(0, 9).map((f) => {
              const body = (
                <div className="flex items-baseline gap-2.5 py-1.5 pr-1">
                  <span className={`relative top-[-1px] h-1.5 w-1.5 shrink-0 self-center rounded-full ${TONE_DOT[TONE[f.tone]]}`} />
                  <div className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg)]">
                    {f.label}{f.detail && <span className="tnum text-[12px] text-[var(--fg-3)]"> · {f.detail}</span>}
                  </div>
                  <span className="tnum shrink-0 text-[12px] text-[var(--fg-3)]">{ago(now - f.ts)}</span>
                </div>
              );
              return (
                <motion.li key={f.key} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.3, ease: EASE }}>
                  {f.thread ? <Link href={reqHref(f.thread)} className="block transition-opacity hover:opacity-70">{body}</Link> : body}
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ol>
      )}
    </Card>
  );
}

// ---------- shipments ----------

const STEPS = ["Booked", "Picked up", "Departed", "Arrived", "Delivered"];

function Shipments({ d }: { d: DashData }) {
  const [hover, setHover] = useState<string | null>(null);
  const rows = d.shipments.slice(0, 5);
  const arcs = d.shipments.slice(0, 10).map((s) => ({ key: s.ref, from: s.origin, to: s.destination, tone: (s.step === "Delivered" ? "over" : "won") as "won" | "over" }));
  return (
    <Card>
      <CardHead title="Shipments in motion" hint="flight steps are estimated from booking time and transit days"
        right={<Link href="/v2/shipments" className="inline-flex items-center gap-1 text-[13px] text-[var(--fg-2)] hover:text-[var(--fg)]">All <span className="tnum">{d.shipmentsTotal}</span> shipments <ArrowRight size={13} /></Link>} />
      {rows.length === 0 ? <p className="text-[13px] text-[var(--fg-3)]">No confirmed bookings yet.</p> : (
        <div className="grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-center gap-6">
          <div className="rounded-lg bg-[var(--bg)] p-3 opacity-90"><WorldMap arcs={arcs} className="h-auto w-full" /></div>
          <div>
            {rows.map((s) => (
              <Link key={s.ref} href={`/v2/shipments?id=${s.thread}`} onMouseEnter={() => setHover(s.ref)} onMouseLeave={() => setHover(null)}
                className="relative grid grid-cols-[110px_minmax(0,1fr)_minmax(0,1fr)_120px_90px] items-center gap-3 rounded-lg px-3 py-2.5 text-[13px]">
                {hover === s.ref && <motion.span layoutId="v2-ship-hover" transition={{ type: "spring", stiffness: 500, damping: 40 }} className="absolute inset-0 rounded-lg bg-[var(--bg-2)]" />}
                <span className="tnum relative text-[var(--fg)]">{s.ref}</span>
                <span className="tnum relative text-[var(--fg)]">{route(s.origin, s.destination)}</span>
                <span className="relative truncate text-[var(--fg-2)]">{s.airline ?? "-"}</span>
                <span className="relative flex items-center gap-2">
                  <span className="flex gap-0.5">{STEPS.map((_, i) => <span key={i} className={`h-1 w-2.5 rounded-full ${i <= s.stepIndex ? "bg-[var(--ok)]" : "bg-[var(--bg-3)]"}`} />)}</span>
                  <span className="truncate text-[12px] text-[var(--fg-2)]">{s.step}</span>
                </span>
                <span className="tnum relative text-right text-[12px] text-[var(--fg-3)]">{s.eta ? `${day(s.eta)} ${clock(s.eta)}` : "-"}</span>
              </Link>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------- page ----------

export function Overview({ initial, initialOff, quoteSeconds }: { initial: DashData; initialOff: OffTrack[]; quoteSeconds: number | null }) {
  const d = useJson<DashData>("/api/dashboard", 5000) ?? initial;
  const off = useJson<{ items: OffTrack[] }>("/api/exceptions", 15000)?.items ?? initialOff;
  const now = useNow();
  const k = d.kpis;
  const last = d.lastMail;
  return (
    <div className="scroll-thin h-full overflow-y-auto">
      <Reveal className="mx-auto max-w-[1360px] space-y-3 px-6 pb-6 pt-3">
        <Item className="flex items-end gap-4 px-1">
          <div className="flex items-baseline gap-3">
            <h1 className="text-[20px] font-semibold leading-tight tracking-[-0.03em]">Overview</h1>
            <p className="text-[13px] text-[var(--fg-2)]">
              {last ? <>Last mail at <span className="tnum text-[var(--fg)]">{clock(last)}</span>, {ago(now - last)} ago.</> : "No mail yet."}
              {d.portal.state === "down" && <span className="ml-2 text-[var(--bad)]">Airline prices are unavailable right now.</span>}
            </p>
          </div>
          <span className="flex-1" />
          {d.source !== "live" && <Badge tone="warn">Demo data</Badge>}
        </Item>

        <div className="grid grid-cols-4 gap-3">
          <Stat label="Requests" value={k.requests.value} format={(v) => String(Math.round(v))} sub="in the last 24 hours" spark={k.requests.spark} />
          <Stat label="Won" value={k.accepted.value} format={(v) => `${Math.round(v)}%`} sub={k.accepted.sub} spark={k.accepted.spark} />
          <Stat label="Booked value" value={k.booked.value} format={(v) => `€${Math.round(v).toLocaleString("en-GB")}`} sub={k.booked.sub} spark={k.booked.spark} />
          <Stat label="Time to quote" value={quoteSeconds} format={(v) => (v < 60 ? `${Math.round(v)}s` : `${Math.floor(v / 60)}m ${Math.round(v % 60)}s`)} sub="median, mail in to quote out"
            foot={quoteSeconds != null && quoteSeconds < 120
              ? <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--fg-2)]"><span className="h-1.5 w-1.5 rounded-full bg-[var(--ok)]" />Inside the 2 minute target</span>
              : undefined} />
        </div>

        <Item className="grid h-[364px] grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-3">
          <div className="scroll-thin min-h-0 overflow-y-auto rounded-[22px]"><Today d={d} off={off} now={now} /></div>
          <Feed items={d.feed} now={now} />
        </Item>

        <Item><Shipments d={d} /></Item>
      </Reveal>
    </div>
  );
}
