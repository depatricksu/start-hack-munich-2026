"use client";
import { useEffect, useState } from "react";
import { EXPIRY_S, Option, Status } from "@/lib/types";

// Glass monochrome, with one colour: green = won (booked, confirmed), the same green the dashboard uses.
// White = quote is out, faint glass = in progress or over. No red, no pulsing.
const WON = "bg-emerald-400/12 text-emerald-300 ring-emerald-400/25";
const CHIP: Record<Status, { label: string; cls: string; dot?: boolean }> = {
  new: { label: "New", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  waiting_bids: { label: "Waiting for bids", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  sending: { label: "Sending", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  quoted: { label: "Quoted", cls: "bg-white text-black ring-white" },
  booking: { label: "Booking", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  booking_requested: { label: "Booking requested", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  booked: { label: "Booked", cls: WON },
  confirmed: { label: "Confirmed", cls: WON },
  lost: { label: "Lost", cls: "bg-white/5 text-zinc-500 ring-white/10" },
  needs_human: { label: "Needs you", cls: "bg-white/14 text-white ring-white/25" },
  expired: { label: "Expired", cls: "bg-white/5 text-zinc-500 ring-white/10" },
  failed: { label: "Failed", cls: "bg-white/14 text-white ring-white/25" },
};

export function StatusChip({ status, lg }: { status: Status; lg?: boolean }) {
  const c = CHIP[status] ?? { label: String(status).replaceAll("_", " "), cls: "bg-white/8 text-zinc-300 ring-white/10" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full ring-1 ring-inset font-medium ${c.cls} ${lg ? "px-2.5 py-1 text-sm" : "px-2 py-0.5 text-xs"}`}>
      {c.dot && <span className="inline-block h-1.5 w-1.5 rounded-full bg-current opacity-70" />}
      {c.label}
    </span>
  );
}

function useClock(): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(t); }, []);
  return now;
}

export function Countdown({ receivedAt, quotedAt, status }: { receivedAt: number; quotedAt: number | null; status: Status }) {
  const now = useClock();
  if (quotedAt) return <span className="num text-xs text-zinc-400">{when(receivedAt)}</span>;
  if (status === "expired") return <span className="num text-xs text-zinc-500">expired</span>;
  const left = Math.round(receivedAt + EXPIRY_S - now);
  if (left <= 0) return <span className="num text-xs text-zinc-500">expired</span>;
  const m = Math.floor(left / 60), s = left % 60;
  return <span className={`num text-xs ${left < 120 ? "text-white font-medium" : "text-zinc-400"}`}>{m}:{String(s).padStart(2, "0")} left</span>;
}

export function BigClock({ receivedAt, quotedAt, status }: { receivedAt: number; quotedAt: number | null; status: Status }) {
  const now = useClock();
  const settled = status === "expired" || status === "failed" || status === "lost";

  if (quotedAt) {
    // A forwarder wants the dates, not how many seconds the system took.
    return (
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-zinc-500">Request in</dt><dd className="num text-right text-zinc-200">{when(receivedAt)}</dd>
        <dt className="text-zinc-500">Quote sent</dt><dd className="num text-right text-white">{when(quotedAt)}</dd>
      </dl>
    );
  }

  const left = Math.round(receivedAt + EXPIRY_S - now);
  const elapsed = Math.max(0, EXPIRY_S - left);
  const pct = Math.min(100, (elapsed / EXPIRY_S) * 100);
  const expired = left <= 0 || settled;
  const m = Math.max(0, Math.floor(left / 60)), s = Math.max(0, left % 60);
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className={`num text-4xl font-semibold tracking-tight ${expired ? "text-zinc-500" : "text-white"}`}>{expired ? "0:00" : `${m}:${String(s).padStart(2, "0")}`}</span>
        <span className="text-sm text-zinc-500">{expired ? "expired" : "left to answer"}</span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-white/10">
        <div className={`h-1.5 rounded-full transition-all ${expired ? "bg-white/25" : "bg-white/70"}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-zinc-500">Request in <span className="num">{when(receivedAt)}</span></div>
    </div>
  );
}

export function when(ts: number): string {
  return new Date(ts * 1000).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function money(total: string, currency = "EUR") {
  return `${Number(total).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export function bestOption(options: Option[]): Option | null {
  const priced = options.filter((o) => Number(o.total_eur) > 0);
  if (!priced.length) return null;
  return priced.reduce((a, b) => (Number(b.total_eur) < Number(a.total_eur) ? b : a));
}

export function sameOption(a: Option | null, b: Option | null): boolean {
  return !!a && !!b && a.airline === b.airline && a.total === b.total;
}

export const LANG_FLAG: Record<string, string> = { en: "EN", de: "DE", fr: "FR", it: "IT", es: "ES" };
