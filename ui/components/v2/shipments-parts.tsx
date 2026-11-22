"use client";
// Relay v2 Shipments: the pieces of the detail pane and the list rows.
// Honesty rule: steps up to "Paid" come from real mails and events. Departed / Arrived / Delivered are
// estimated from booking time + transit days, so they are drawn dashed and labeled "estimated".
import { ReactNode, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown, Copy } from "lucide-react";
import type { Line, Message, ShipmentDetail, ShipmentRow, Step } from "@/lib/shipments";
import type { ShipmentUpdates, Update } from "@/lib/carriers";
import {
  Badge, Card, CardHead, EASE, Skeleton, Tone, clock, day, money, route, useJson,
} from "@/components/v2/ui";

// ---------- small shared bits ----------

export function shipStatus(s: string): [string, Tone] {
  if (s === "cancelled") return ["Cancelled", "idle"];
  if (s === "booked") return ["Waiting for airline", "idle"];
  if (s === "confirmed") return ["Confirmed", "ok"];
  return [s.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()), "idle"];
}
export function ShipBadge({ status }: { status: string }) {
  const [l, t] = shipStatus(status);
  return <Badge tone={t}>{l}</Badge>;
}

const when = (t: number | null) => (t ? `${day(t)} ${clock(t)}` : "");
const text = (l: Line) => l.map((s) => s.t).join("");

export function Kpi({ label, sub, children, tone }: { label: string; sub: ReactNode; children: ReactNode; tone?: string }) {
  return (
    <Card className="h-full">
      <div className="eyebrow">{label}</div>
      <div className={`mt-2 text-[28px] font-semibold leading-none tracking-[-0.03em] ${tone ?? "text-[var(--fg)]"}`}>{children}</div>
      <div className="mt-2 text-[13px] text-[var(--fg-2)]">{sub}</div>
    </Card>
  );
}

// ---------- list row strip ----------

// Tiny step strip for a list row: real steps as solid bars, estimated ones as dashed outlines.
export function Strip({ r }: { r: ShipmentRow }) {
  const over = r.status === "cancelled";
  const real = r.steps.filter((s) => !s.sim), sim = r.steps.filter((s) => s.sim);
  return (
    <div className="flex items-center gap-[3px]" aria-label={`${real.filter((s) => s.done).length} of ${real.length} steps done`}>
      {real.map((s) => (
        <span key={s.key} title={`${s.label}${s.done ? `, ${when(s.at)}` : ""}`}
          className={`h-1 w-4 rounded-full ${over ? "bg-[var(--bg-3)]" : s.problem ? "bg-[var(--bad)]" : s.done ? "bg-[var(--fg-2)]" : "bg-[var(--bg-3)]"}`} />
      ))}
      <span className="w-1.5" />
      {sim.map((s) => (
        <span key={s.key} title={`${s.label}, estimated`}
          className={`h-1.5 w-3 rounded-full border border-dashed ${!over && s.done ? "border-[var(--fg-3)]" : "border-[var(--hair-2)]"}`} />
      ))}
    </div>
  );
}

// ---------- horizontal stepper ----------

const col = { hidden: { opacity: 0, y: 4 }, show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: EASE } } };
const line = { hidden: { scaleX: 0 }, show: { scaleX: 1, transition: { duration: 0.4, ease: EASE } } };

function Node({ s, next, over }: { s: Step; next: boolean; over: boolean }) {
  if (s.sim) {
    const lit = !over && s.done;
    return (
      <span className={`flex h-[14px] w-[14px] items-center justify-center rounded-full border border-dashed ${lit ? "border-[var(--fg-2)]" : "border-[var(--hair-2)]"}`}>
        {lit && <span className="h-1 w-1 rounded-full bg-[var(--fg-2)]" />}
      </span>
    );
  }
  if (over) return <span className={`h-[14px] w-[14px] rounded-full ${s.done ? "bg-[var(--fg-3)]" : "border border-[var(--hair-2)]"}`} />;
  if (s.problem) return <span className="h-[14px] w-[14px] rounded-full bg-[var(--bad)]" />;
  if (s.done) return <span className="flex h-[14px] w-[14px] items-center justify-center rounded-full bg-[var(--fg)]"><Check size={9} strokeWidth={3.5} className="text-[var(--bg)]" /></span>;
  if (next) return <span className="h-[14px] w-[14px] rounded-full border-2 border-[var(--fg-2)]" />;
  return <span className="h-[14px] w-[14px] rounded-full border border-[var(--hair-2)]" />;
}

export function Stepper({ d }: { d: ShipmentDetail }) {
  const over = d.status === "cancelled";
  const steps = d.steps;
  const nReal = steps.filter((s) => !s.sim).length;
  const nextKey = over ? null : steps.find((s) => !s.sim && !s.done)?.key;
  return (
    <div>
      <div className="mb-3 grid gap-x-0" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        <div className="eyebrow" style={{ gridColumn: `span ${nReal}` }}>From our mails and events</div>
        <div className="eyebrow border-l border-dashed border-[var(--hair-2)] pl-3" style={{ gridColumn: `span ${steps.length - nReal}` }}>
          Estimated, no flight feed
        </div>
      </div>
      <motion.ol initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: 0.05 } } }}
        className="grid" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        {steps.map((s, i) => {
          const nx = steps[i + 1];
          const dashed = !!nx?.sim;
          const filled = !over && s.done && !!nx?.done;
          const timeText = s.sim
            ? (over ? "Not flying" : s.at ? `${s.done ? "" : "about "}${day(s.at)}` : "After confirmation")
            : s.problem ? "Overdue" : s.done ? when(s.at) : "Not yet";
          return (
            <motion.li key={s.key} variants={col} className={`relative pr-2 ${s.sim && !steps[i - 1]?.sim ? "border-l border-dashed border-[var(--hair-2)] pl-3" : ""}`}>
              <div className="relative flex h-[14px] items-center">
                <Node s={s} next={s.key === nextKey} over={over} />
                {nx && (
                  <motion.span variants={line} style={{ originX: 0 }}
                    className={`absolute left-[20px] right-[2px] top-1/2 h-0 border-t ${dashed ? "border-dashed" : ""} ${filled ? "border-[var(--fg-3)]" : "border-[var(--hair-2)]"}`} />
                )}
              </div>
              <div className={`mt-2 text-[13px] leading-snug ${s.sim ? "text-[var(--fg-3)]" : s.done && !over ? "text-[var(--fg)]" : "text-[var(--fg-2)]"}`}>{s.label}</div>
              <div className={`tnum mt-0.5 text-[12px] ${s.problem && !over ? "text-[var(--bad)]" : "text-[var(--fg-3)]"}`}>{timeText}</div>
            </motion.li>
          );
        })}
      </motion.ol>
    </div>
  );
}

// ---------- facts + invoice ----------

function Facts({ d }: { d: ShipmentDetail }) {
  if (!d.facts.length) return null;
  return (
    <div>
      <h3 className="eyebrow mb-3">From our records</h3>
      <dl className="grid grid-cols-[96px_minmax(0,1fr)] gap-x-4 gap-y-2 text-[13px]">
        {d.facts.map((f) => (
          <div key={f.k} className="contents">
            <dt className="text-[var(--fg-3)]">{f.k}</dt>
            <dd className={f.open ? "text-[var(--warn)]" : "text-[var(--fg)]"}>{f.v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function InvoiceLine({ d }: { d: ShipmentDetail }) {
  const inv = d.invoice;
  let label = "", tone: Tone = "idle";
  if (inv) {
    if (inv.status === "paid") { label = `Paid ${inv.paid_at ? day(inv.paid_at) : ""}`.trim(); tone = "ok"; }
    else if (inv.status === "cancelled") label = "Cancelled";
    else if (inv.status === "paid_reported") { label = "Customer says paid"; tone = "warn"; }
    else if (inv.overdue_days > 0 || inv.status === "overdue_human") { label = `${inv.overdue_days} days late`; tone = "bad"; }
    else label = "Open";
  }
  return (
    <div>
      <h3 className="eyebrow mb-3">Invoice</h3>
      {inv ? (
        <Link href="/v2/invoices" className="flex items-center gap-3 rounded-md border border-[var(--hair)] px-3 py-2.5 transition-colors duration-150 hover:bg-[var(--bg-2)]">
          <span className="tnum whitespace-nowrap text-[13px] text-[var(--fg)]">{inv.number}</span>
          <span className="tnum whitespace-nowrap text-[13px] text-[var(--fg-2)]">{money(inv.amount, inv.currency)}</span>
          <span className="flex-1" />
          {!inv.sent && inv.status !== "paid" && <span className="whitespace-nowrap text-[12px] text-[var(--fg-3)]">Not mailed</span>}
          <Badge tone={tone}>{label}</Badge>
        </Link>
      ) : <p className="text-[13px] text-[var(--fg-2)]">{d.status === "cancelled" ? "No invoice. The booking was cancelled before the airline confirmed." : "No invoice yet. It is written when the airline confirms."}</p>}
    </div>
  );
}

// ---------- carrier updates ----------

const UTONE: Record<Update["tone"], Tone> = { green: "ok", blue: "idle", amber: "warn", red: "bad", grey: "idle" };

function UpdateRow({ u }: { u: Update }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-t border-[var(--hair)] py-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={UTONE[u.tone]}>{u.label}</Badge>
        <span className="tnum text-[12px] text-[var(--fg-3)]">{when(u.ts)}</span>
        {u.from === "carrier" && u.carrier && <span className="text-[13px] text-[var(--fg-2)]">{u.carrier}</span>}
        {u.from === "customer" && <span className="text-[13px] text-[var(--fg-2)]">from the customer</span>}
        {u.from === "us" && <span className="text-[13px] text-[var(--fg-2)]">by us</span>}
        <span className="flex-1" />
        {u.told === "yes" && <span className="flex items-center gap-1 text-[12px] text-[var(--fg-2)]"><Check size={12} className="text-[var(--ok)]" />Customer told</span>}
        {u.told === "no" && <Badge tone="warn">Customer not told yet</Badge>}
      </div>
      <p className="mt-1.5 text-[13px] text-[var(--fg)]">{u.summary}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-[var(--fg-3)]">
        {u.dates.length > 0 && <span>Dates <span className="tnum text-[var(--fg-2)]">{u.dates.join(", ")}</span></span>}
        {u.flight && <span>Flight <span className="tnum text-[var(--fg-2)]">{u.flight}</span></span>}
        {u.awb && <span>AWB <span className="tnum text-[var(--fg-2)]">{u.awb}</span></span>}
        {u.mail && (
          <button onClick={() => setOpen((o) => !o)} className="ml-auto text-[12px] text-[var(--fg-2)] transition-colors duration-150 hover:text-[var(--fg)]">
            {open ? "Hide mail" : "Show mail"}
          </button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && u.mail && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }} className="overflow-hidden">
            <div className="mt-2 rounded-md border border-[var(--hair)] bg-[var(--bg)] p-3">
              <div className="text-[12px] text-[var(--fg-3)]"><span className="tnum">{u.mail.sender}</span>, {u.mail.subject}</div>
              <pre className="tnum mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--fg-2)] scroll-thin">{u.mail.body}</pre>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

function CarrierUpdates({ thread }: { thread: number }) {
  const raw = useJson<ShipmentUpdates>(`/api/carriers/shipment/${thread}`, 10000);
  const d = raw && raw.thread === thread ? raw : null;
  return (
    <Card>
      <CardHead title="Carrier updates" hint={d?.status ? `Carrier says: ${d.status}` : "What the carriers wrote"}
        right={d && d.not_told > 0 ? <Badge tone="warn">{d.not_told} not told to the customer</Badge> : undefined} />
      {!d && <div className="space-y-2"><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /></div>}
      {d && d.updates.length === 0 && <p className="text-[13px] text-[var(--fg-2)]">No mail from the carriers about this shipment yet.</p>}
      {d && d.updates.length > 0 && <ul>{d.updates.map((u) => <UpdateRow key={u.id} u={u} />)}</ul>}
    </Card>
  );
}

// ---------- after-the-yes messages ----------

function Segs({ line: l }: { line: Line }) {
  return (
    <>
      {l.map((s, i) => s.k === "record"
        ? <span key={i} className="text-[var(--fg)] underline decoration-[var(--fg-3)] decoration-dotted underline-offset-[3px]">{s.t}</span>
        : s.k === "open"
          ? <span key={i} className="rounded bg-[var(--warn-soft)] px-1 text-[var(--warn)]">{s.t}</span>
          : <span key={i}>{s.t}</span>)}
    </>
  );
}

function MessageRow({ m }: { m: Message }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = () => {
    const parts = [m.address ? `To: ${m.address}` : `To: ${text(m.to)}`, `Subject: ${text(m.subject)}`, "", ...m.body.map(text)];
    navigator.clipboard?.writeText(parts.join("\n")).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1400); }).catch(() => {});
  };
  return (
    <li className="border-t border-[var(--hair)] first:border-t-0">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="-mx-2 flex w-[calc(100%+16px)] items-center gap-3 rounded-md px-2 py-2.5 text-left transition-colors duration-150 hover:bg-[var(--bg-2)]">
        <span className="eyebrow w-44 shrink-0 truncate">{m.role}</span>
        <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg)]">{m.title}</span>
        <span className="hidden shrink-0 text-[12px] text-[var(--fg-3)] xl:inline">{m.when}</span>
        {m.state === "sent" ? <Badge tone="ok">Sent {m.sent_at ? day(m.sent_at) : ""}</Badge> : <Badge>Draft</Badge>}
        <ChevronDown size={14} className={`shrink-0 text-[var(--fg-3)] transition-transform duration-150 ${open ? "rotate-180" : ""}`} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }} className="overflow-hidden">
            <div className="pb-4 pt-1">
              <p className="text-[13px] text-[var(--fg-2)]">{m.why}</p>
              <div className="mt-3 space-y-1 text-[13px] text-[var(--fg-2)]">
                <div className="flex gap-3"><span className="w-16 shrink-0 text-[var(--fg-3)]">To</span>
                  <span className="min-w-0"><Segs line={m.to} />
                    {m.address ? <span className="tnum ml-2 text-[12px] text-[var(--fg-3)]">{m.address}</span>
                      : !m.recipients && <span className="ml-2 rounded bg-[var(--warn-soft)] px-1 text-[12px] text-[var(--warn)]">address open</span>}
                  </span>
                </div>
                {m.recipients && (
                  <div className="pl-[76px] text-[12px] text-[var(--fg-3)]">
                    {m.recipients.map((r) => (
                      <div key={r.name}>{r.name} <span className="tnum">{r.address ?? ""}</span>{r.offer && <span className="tnum">, offered {r.offer} (not in the mail)</span>}</div>
                    ))}
                    <div>Each gets the mail on its own.</div>
                  </div>
                )}
                <div className="flex gap-3"><span className="w-16 shrink-0 text-[var(--fg-3)]">Subject</span><span className="min-w-0 text-[var(--fg)]"><Segs line={m.subject} /></span></div>
              </div>
              <pre className="tnum mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-[var(--hair)] bg-[var(--bg)] p-3 text-[12.5px] leading-relaxed text-[var(--fg-2)] scroll-thin">
                {m.body.map((l, i) => <div key={i}>{l.length ? <Segs line={l} /> : " "}</div>)}
              </pre>
              <div className="mt-2 flex justify-end">
                <button onClick={copy} className="btn btn-ghost h-7 px-2.5 text-[12px]">
                  {copied ? <Check size={12} /> : <Copy size={12} />}{copied ? "Copied" : "Copy text"}
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  );
}

function Messages({ d }: { d: ShipmentDetail }) {
  const sent = d.messages.filter((m) => m.state === "sent").length;
  return (
    <Card>
      <CardHead title="After the yes" hint={`${d.messages.length} messages, ${sent} sent`} />
      <p className="-mt-2 mb-3 text-[13px] text-[var(--fg-2)]">
        What each party should hear, built from our records. Nothing here is sent from this page.{" "}
        <span className="text-[var(--fg)] underline decoration-[var(--fg-3)] decoration-dotted underline-offset-[3px]">Underlined</span> is from our records,{" "}
        <span className="rounded bg-[var(--warn-soft)] px-1 text-[var(--warn)]">marked</span> is still open.
      </p>
      {d.note && <p className="mb-3 text-[13px] text-[var(--fg-2)]">{d.note}</p>}
      {d.messages.length ? <ul>{d.messages.map((m) => <MessageRow key={m.id} m={m} />)}</ul>
        : <p className="text-[13px] text-[var(--fg-2)]">No messages for this shipment.</p>}
    </Card>
  );
}

// ---------- the detail pane ----------

export function Detail({ d }: { d: ShipmentDetail }) {
  return (
    <div className="space-y-4">
      <Card className="p-6">
        <div className="flex items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="tnum text-[22px] font-semibold tracking-[-0.02em] text-[var(--fg)]">{route(d.origin, d.destination)}</div>
            <div className="mt-1 text-[14px] text-[var(--fg-2)]">{d.company} <span className="text-[var(--fg-3)]">{d.customer}</span></div>
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-[var(--fg-3)]">
              <span>Booking <span className="tnum text-[var(--fg)]">{d.booking_ref ?? "not yet"}</span></span>
              <span>Our ref <span className="tnum text-[var(--fg)]">{d.ref}</span></span>
              <span>Airline <span className="text-[var(--fg)]">{d.airline ?? "not chosen"}</span></span>
              {d.trucker && <span>Trucker <span className="text-[var(--fg)]">{d.trucker}</span></span>}
              {d.price && <span>Price <span className="tnum text-[var(--fg)]">{d.price}</span></span>}
            </div>
          </div>
          <ShipBadge status={d.status} />
          <Link href={`/v2/requests?id=${d.thread}`} className="btn btn-ghost h-7 px-2.5 text-[12px]">Open request</Link>
        </div>

        {d.watch.map((w) => (
          <div key={w.carrier} className="mt-4 flex items-center gap-3 rounded-md border border-[var(--hair)] px-3 py-2">
            <span className={`h-1.5 w-1.5 rounded-full ${w.level === "red" ? "bg-[var(--bad)]" : "bg-[var(--warn)]"}`} />
            <span className="text-[13px] text-[var(--fg)]">Watch {w.carrier}</span>
            <span className="text-[13px] text-[var(--fg-2)]">{w.reasons.join(", ")}</span>
          </div>
        ))}

        <div className="mt-6 border-t border-[var(--hair)] pt-5"><Stepper d={d} /></div>

        <div className="mt-6 grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] gap-8 border-t border-[var(--hair)] pt-5">
          <Facts d={d} />
          <InvoiceLine d={d} />
        </div>
      </Card>
      <CarrierUpdates thread={d.thread} />
      <Messages d={d} />
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="space-y-4">
      <Card className="p-6">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="mt-3 h-4 w-72" />
        <Skeleton className="mt-6 h-16 w-full" />
        <div className="mt-6 grid grid-cols-2 gap-8"><Skeleton className="h-40" /><Skeleton className="h-12" /></div>
      </Card>
      <Card><Skeleton className="h-4 w-40" /><Skeleton className="mt-4 h-12 w-full" /></Card>
    </div>
  );
}
