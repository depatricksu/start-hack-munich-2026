"use client";
// Relay v2 Overview: four numbers, today's work (needs you, off track, in flight), live activity, shipments.
// Less than the classic dashboard on purpose: pricing, carrier and customer tables are one question to Ask Relay.
import Link from "next/link";
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { WorldMap } from "@/components/world-map";
import type { DashData, FeedItem, QueueItem, Tone as DTone } from "@/lib/dashboard-types";
import type { OffTrack } from "@/lib/exceptions";
import {
  Badge, Card, CardHead, CountUp, EASE, Item, Reveal, StatusBadge, TONE_DOT, TONE_TEXT, Tone,
  ago, clock, day, route, shortMail, useJson, useNow,
} from "@/components/v2/ui";

const TONE: Record<DTone, Tone> = { won: "ok", progress: "info", human: "warn", broken: "bad", over: "idle", neutral: "idle" };
const reqHref = (id: number) => `/v2/requests?id=${id}`;

// ---------- numbers ----------

function Spark({ data }: { data: (number | null)[] }) {
  const w = 160, h = 32;
  const vals = data.filter((v): v is number => v != null);
  const max = Math.max(1, ...vals);
  const step = w / Math.max(1, data.length - 1);
  let d = "";
  data.forEach((v, i) => {
    if (v == null) return;
    d += `${d ? "L" : "M"}${(i * step).toFixed(1)},${(h - 3 - (v / max) * (h - 6)).toFixed(1)}`;
  });
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-8 w-full" preserveAspectRatio="none" aria-hidden>
      <motion.path d={d} fill="none" stroke="var(--fg-3)" strokeWidth={1.25} vectorEffect="non-scaling-stroke"
        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.1, ease: EASE, delay: 0.2 }} />
    </svg>
  );
}

function Stat({ label, value, format, sub, spark, foot }: { label: string; value: number | null; format: (v: number) => string; sub: string; spark?: (number | null)[]; foot?: React.ReactNode }) {
  return (
    <Item>
      <Card className="flex h-full flex-col">
        <div className="text-[13px] text-[var(--fg-2)]">{label}</div>
        <div className="mt-2 text-[32px] font-semibold leading-none tracking-[-0.04em] text-[var(--fg)]">
          {value == null ? <span className="tnum">-</span> : <CountUp value={value} format={format} />}
        </div>
        <div className="mt-2 text-[13px] text-[var(--fg-3)]">{sub}</div>
        {spark && <div className="mt-auto pt-3"><Spark data={spark} /></div>}
        {foot && <div className="mt-auto pt-3">{foot}</div>}
      </Card>
    </Item>
  );
}

// ---------- today's work ----------

function Group({ title, count, tone, children, empty }: { title: string; count: number; tone: Tone; children: React.ReactNode; empty: string }) {
  return (
    <div className="border-t border-[var(--hair)] pt-4 first:border-t-0 first:pt-0">
      <div className="mb-2 flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${count ? TONE_DOT[tone] : "bg-[var(--bg-3)]"}`} />
        <h3 className="text-[13px] font-medium text-[var(--fg)]">{title}</h3>
        <span className="tnum text-[12px] text-[var(--fg-3)]">{count}</span>
      </div>
      {count ? children : <p className="py-1 pl-3.5 text-[13px] text-[var(--fg-3)]">{empty}</p>}
    </div>
  );
}

function Row({ href, children, tone }: { href: string; children: React.ReactNode; tone?: Tone }) {
  return (
    <Link href={href} className={`group flex items-center gap-4 rounded-lg px-3.5 py-2.5 transition-colors hover:bg-[var(--bg-2)] ${tone === "warn" ? "bg-[var(--warn-soft)]/40" : ""}`}>
      {children}
      <ArrowUpRight size={14} className="shrink-0 text-[var(--fg-3)] opacity-0 transition-opacity group-hover:opacity-100" />
    </Link>
  );
}

function NeedsRow({ q, now }: { q: QueueItem; now: number }) {
  return (
    <Row href={reqHref(q.id)} tone="warn">
      <span className="tnum w-28 shrink-0 text-[13px] font-medium text-[var(--fg)]">{route(q.origin, q.destination)}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] text-[var(--warn)]">{q.reason ?? "Relay could not finish this alone"}</span>
        <span className="block truncate text-[12px] text-[var(--fg-3)]">{shortMail(q.customer)}</span>
      </span>
      <span className="tnum shrink-0 text-[12px] text-[var(--warn)]">waiting {ago(now - q.received_at)}</span>
    </Row>
  );
}

function OffRow({ x, now }: { x: OffTrack; now: number }) {
  return (
    <Row href={x.href}>
      <span className="tnum w-28 shrink-0 text-[13px] font-medium text-[var(--fg)]">{x.route ?? "-"}</span>
      <span className="min-w-0 flex-1">
        <span className={`block truncate text-[13px] ${TONE_TEXT[x.tone]}`}>{x.title}</span>
        <span className="block truncate text-[12px] text-[var(--fg-3)]">{shortMail(x.customer)}. {x.action}</span>
      </span>
      <span className="tnum shrink-0 text-[12px] text-[var(--fg-3)]">{ago(now - x.since)}</span>
    </Row>
  );
}

function FlightRow({ q, now }: { q: QueueItem; now: number }) {
  return (
    <Row href={reqHref(q.id)}>
      <span className="tnum w-28 shrink-0 text-[13px] font-medium text-[var(--fg)]">{route(q.origin, q.destination)}</span>
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg-2)]">{shortMail(q.customer)}</span>
      <StatusBadge status={String(q.status)} />
      <span className="tnum w-32 shrink-0 whitespace-nowrap text-right text-[12px] text-[var(--fg-3)]">
        {q.quoted_at != null ? `quoted ${ago(now - q.quoted_at)} ago` : `${ago(now - q.received_at)} old`}
      </span>
    </Row>
  );
}

function DoneRow({ q }: { q: QueueItem }) {
  return (
    <Row href={reqHref(q.id)}>
      <span className="tnum w-28 shrink-0 text-[13px] text-[var(--fg)]">{route(q.origin, q.destination)}</span>
      <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg-2)]">{shortMail(q.customer)}</span>
      <span className="tnum w-28 shrink-0 text-right text-[13px] text-[var(--fg-2)]">{q.price ?? "-"}</span>
      <span className="w-24 shrink-0 text-right"><StatusBadge status={String(q.status)} /></span>
    </Row>
  );
}

function Today({ d, off, now }: { d: DashData; off: OffTrack[]; now: number }) {
  const { needs, done, doneTotal } = d.queue;
  // A request that is already in "Off track" (e.g. waiting for documents) is not listed twice.
  const offIds = new Set(off.map((x) => x.href));
  const flight = d.queue.flight.filter((q) => !offIds.has(reqHref(q.id)));
  return (
    <Card className="h-full">
      <CardHead title="Today" hint="what Relay is working on" right={<Link href="/v2/requests" className="text-[13px] text-[var(--fg-2)] hover:text-[var(--fg)]">All requests</Link>} />
      <div className="space-y-4">
        <Group title="Needs you" count={needs.length} tone="warn" empty="Nothing waiting for a person.">
          <div className="space-y-1">{needs.map((q) => <NeedsRow key={q.id} q={q} now={now} />)}</div>
        </Group>
        <Group title="Off track" count={off.length} tone={off.some((x) => x.tone === "bad") ? "bad" : "warn"} empty="Every shipment is on plan.">
          <div className="space-y-1">{off.slice(0, 5).map((x) => <OffRow key={x.id} x={x} now={now} />)}</div>
        </Group>
        <Group title="In flight" count={flight.length} tone="info" empty="No open requests right now.">
          <div className="space-y-1">{flight.map((q) => <FlightRow key={q.id} q={q} now={now} />)}</div>
        </Group>
        <Group title="Just finished" count={Math.min(5, done.length)} tone="idle" empty="Nothing finished yet.">
          <div>{done.slice(0, 5).map((q) => <DoneRow key={q.id} q={q} />)}</div>
          {doneTotal > 5 && (
            <Link href="/v2/requests?filter=done" className="mt-1 inline-flex items-center gap-1 px-3.5 py-1.5 text-[13px] text-[var(--fg-2)] hover:text-[var(--fg)]">
              All <span className="tnum">{doneTotal}</span> finished <ArrowRight size={13} />
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
    <Card className="flex h-full min-h-0 flex-col">
      <CardHead title="Live activity" hint="newest first" />
      {items.length === 0 ? <p className="text-[13px] text-[var(--fg-3)]">No activity yet.</p> : (
        <ol className="relative min-h-0 flex-1 overflow-hidden"
          style={{ maskImage: "linear-gradient(to bottom, #000 75%, transparent)", WebkitMaskImage: "linear-gradient(to bottom, #000 75%, transparent)" }}>
          <span className="absolute bottom-0 left-[5px] top-2 w-px bg-[var(--hair)]" aria-hidden />
          <AnimatePresence initial={false}>
            {items.slice(0, 12).map((f) => {
              const tone = TONE[f.tone];
              const body = (
                <div className="flex gap-3 rounded-lg py-2 pr-2">
                  <span className={`relative z-10 mt-[7px] h-[11px] w-[11px] shrink-0 rounded-full border-2 border-[var(--bg-1)] ${TONE_DOT[tone]}`} />
                  <div className="min-w-0 flex-1">
                    <div className={`truncate text-[13px] ${tone === "idle" ? "text-[var(--fg)]" : TONE_TEXT[tone]}`}>{f.label}</div>
                    {f.detail && <div className="tnum truncate text-[12px] text-[var(--fg-3)]">{f.detail}</div>}
                  </div>
                  <span className="tnum shrink-0 pt-0.5 text-[12px] text-[var(--fg-3)]">{ago(now - f.ts)}</span>
                </div>
              );
              return (
                <motion.li key={f.key} layout initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.3, ease: EASE }}>
                  {f.thread ? <Link href={reqHref(f.thread)} className="block transition-opacity hover:opacity-80">{body}</Link> : body}
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
      <Reveal className="mx-auto max-w-[1360px] space-y-4 px-6 py-7">
        <Item className="flex items-end gap-4">
          <div>
            <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.04em]">Overview</h1>
            <p className="mt-1 text-[14px] text-[var(--fg-2)]">
              {last ? <>Last mail at <span className="tnum text-[var(--fg)]">{clock(last)}</span>, {ago(now - last)} ago.</> : "No mail yet."}
              {d.portal.state === "down" && <span className="ml-2 text-[var(--bad)]">Airline prices are unavailable right now.</span>}
            </p>
          </div>
          <span className="flex-1" />
          {d.source !== "live" && <Badge tone="warn">Demo data</Badge>}
        </Item>

        <div className="grid grid-cols-4 gap-4">
          <Stat label="Requests" value={k.requests.value} format={(v) => String(Math.round(v))} sub="in the last 24 hours" spark={k.requests.spark} />
          <Stat label="Won" value={k.accepted.value} format={(v) => `${Math.round(v)}%`} sub={k.accepted.sub} spark={k.accepted.spark} />
          <Stat label="Booked value" value={k.booked.value} format={(v) => `€${Math.round(v).toLocaleString("en-GB")}`} sub={k.booked.sub} spark={k.booked.spark} />
          <Stat label="Time to quote" value={quoteSeconds} format={(v) => (v < 60 ? `${Math.round(v)}s` : `${Math.floor(v / 60)}m ${Math.round(v % 60)}s`)} sub="median, mail in to quote out"
            foot={quoteSeconds != null && quoteSeconds < 120 ? <Badge tone="ok">Inside the 2 minute target</Badge> : undefined} />
        </div>

        <Item className="grid h-[600px] grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] gap-4">
          <div className="scroll-thin min-h-0 overflow-y-auto rounded-xl"><Today d={d} off={off} now={now} /></div>
          <Feed items={d.feed} now={now} />
        </Item>

        <Item><Shipments d={d} /></Item>
      </Reveal>
    </div>
  );
}
