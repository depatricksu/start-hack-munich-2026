"use client";
// Shared building blocks for Relay v2. Every screen uses these, so spacing, color and motion stay the same.
import { ReactNode, useEffect, useRef, useState } from "react";
import { animate, motion, useInView, useReducedMotion } from "motion/react";

// ---------- motion ----------

// One easing for the whole app: fast start, soft landing.
export const EASE = [0.16, 1, 0.3, 1] as const;
export const SPRING = { type: "spring", stiffness: 380, damping: 34 } as const;

// Children rise in one after another. Used for the first paint of a screen, not for every update.
export const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.045, delayChildren: 0.02 } } };
export const rise = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.45, ease: EASE } },
};

export function Reveal({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <motion.div variants={stagger} initial="hidden" animate="show" className={className}>{children}</motion.div>;
}
export function Item({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <motion.div variants={rise} className={className}>{children}</motion.div>;
}

// A number that counts up once when it comes into view (and jumps straight to new values after that).
export function CountUp({ value, format = (v) => Math.round(v).toLocaleString("en-GB"), className = "" }:
  { value: number; format?: (v: number) => string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const seen = useInView(ref, { once: true });
  const reduce = useReducedMotion();
  const first = useRef(true);
  useEffect(() => {
    const el = ref.current;
    if (!el || !seen) return;
    if (reduce || !first.current) { el.textContent = format(value); return; }
    first.current = false;
    const c = animate(0, value, { duration: 0.9, ease: EASE, onUpdate: (v) => { el.textContent = format(v); } });
    return () => c.stop();
  }, [value, seen, reduce, format]);
  return <span ref={ref} className={`tnum ${className}`}>{format(reduce ? value : 0)}</span>;
}

// ---------- surfaces ----------

export function Card({ children, className = "", pad = true }: { children: ReactNode; className?: string; pad?: boolean }) {
  return <section className={`card ${pad ? "p-5" : ""} ${className}`}>{children}</section>;
}

export function CardHead({ title, hint, right }: { title: string; hint?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex items-baseline gap-3">
      <h2 className="text-[15px] font-semibold tracking-[-0.01em] text-[var(--fg)]">{title}</h2>
      {hint && <span className="text-[13px] text-[var(--fg-3)]">{hint}</span>}
      <span className="flex-1" />
      {right}
    </div>
  );
}

export function PageHead({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex items-end gap-4">
      <div className="min-w-0">
        <h1 className="text-[28px] font-semibold leading-tight tracking-[-0.04em] text-[var(--fg)]">{title}</h1>
        {sub && <p className="mt-1 text-[14px] text-[var(--fg-2)]">{sub}</p>}
      </div>
      <span className="flex-1" />
      {right}
    </div>
  );
}

// ---------- state ----------

export type Tone = "ok" | "warn" | "bad" | "info" | "idle";
const TONE: Record<Tone, string> = {
  ok: "bg-[var(--ok-soft)] text-[var(--ok)]",
  warn: "bg-[var(--warn-soft)] text-[var(--warn)]",
  bad: "bg-[var(--bad-soft)] text-[var(--bad)]",
  info: "bg-[var(--accent-soft)] text-[var(--accent)]",
  idle: "bg-[var(--bg-3)] text-[var(--fg-2)]",
};
export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-[var(--ok)]", warn: "text-[var(--warn)]", bad: "text-[var(--bad)]", info: "text-[var(--accent)]", idle: "text-[var(--fg-2)]",
};
export const TONE_DOT: Record<Tone, string> = {
  ok: "bg-[var(--ok)]", warn: "bg-[var(--warn)]", bad: "bg-[var(--bad)]", info: "bg-[var(--accent)]", idle: "bg-[var(--fg-3)]",
};

export function Badge({ tone = "idle", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`inline-flex h-[22px] shrink-0 items-center whitespace-nowrap rounded-full px-2.5 text-[12px] font-medium ${TONE[tone]}`}>{children}</span>;
}

// Request statuses in a forwarder's words, with one tone each.
const STATUS: Record<string, [string, Tone]> = {
  new: ["New", "info"], waiting_bids: ["Getting prices", "info"], sending: ["Sending", "info"],
  quoted: ["Quoted", "idle"], booking: ["Booking", "info"], booking_requested: ["Booking", "info"],
  booked: ["Booked", "ok"], confirmed: ["Confirmed", "ok"], awaiting_docs: ["Waiting for documents", "warn"],
  lost: ["Lost", "idle"], cancelled: ["Cancelled", "idle"], expired: ["Expired", "idle"],
  needs_human: ["Needs you", "warn"], failed: ["Failed", "bad"], declined: ["Declined", "idle"],
};
export function statusInfo(s: string): [string, Tone] {
  return STATUS[s] ?? [s.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()), "idle"];
}
export function StatusBadge({ status }: { status: string }) {
  const [label, tone] = statusInfo(status);
  return <Badge tone={tone}>{label}</Badge>;
}

// ---------- controls ----------

// Segmented control with a sliding background. `id` keeps two of them on one page apart.
export function Segmented<T extends string>({ id, value, options, onChange }:
  { id: string; value: T; options: { value: T; label: string; count?: number }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-[var(--hair-2)] bg-[var(--bg-1)] p-0.5">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={`relative h-7 rounded-md px-3 text-[13px] font-medium transition-colors ${value === o.value ? "text-[var(--fg)]" : "text-[var(--fg-3)] hover:text-[var(--fg-2)]"}`}>
          {value === o.value && <motion.span layoutId={`seg-${id}`} transition={SPRING} className="absolute inset-0 rounded-md bg-[var(--bg-3)]" />}
          <span className="relative flex items-center gap-1.5">
            {o.label}
            {o.count != null && <span className="tnum text-[11px] text-[var(--fg-3)]">{o.count}</span>}
          </span>
        </button>
      ))}
    </div>
  );
}

// ---------- formatting ----------

export const route = (o?: string | null, d?: string | null) => `${o && o !== "null" ? o : "???"} → ${d && d !== "null" ? d : "???"}`;
export const shortMail = (m: string) => m.split("@")[0];
export const eur = (n: number) => `€${Math.round(n).toLocaleString("en-GB")}`;
export function money(total: string | number, currency = "EUR") {
  return `${Number(total).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}
export const clock = (t: number) => new Date(t * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
export const day = (t: number) => new Date(t * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
export function ago(s: number): string {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d`;
}

// Poll a JSON endpoint. Keeps the last good answer when a poll fails.
export function useJson<T>(url: string | null, every = 4000): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    const load = () => fetch(url, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).then((d) => { if (alive && d) setData(d); }).catch(() => {});
    load();
    const t = setInterval(load, every);
    return () => { alive = false; clearInterval(t); };
  }, [url, every]);
  return data;
}

// Ticking clock in seconds, for "x ago" labels.
export function useNow(every = 1000): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), every); return () => clearInterval(t); }, [every]);
  return now;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}
