"use client";
import { useEffect, useState } from "react";
import { EXPIRY_S, Option, Status } from "@/lib/types";

const CHIP: Record<Status, { label: string; cls: string; dot?: boolean }> = {
  new: { label: "New", cls: "bg-sky-50 text-sky-700 ring-sky-200", dot: true },
  waiting_bids: { label: "Waiting for bids", cls: "bg-amber-50 text-amber-800 ring-amber-200", dot: true },
  sending: { label: "Sending", cls: "bg-sky-50 text-sky-700 ring-sky-200", dot: true },
  quoted: { label: "Quoted", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  booking: { label: "Booking", cls: "bg-indigo-50 text-indigo-700 ring-indigo-200", dot: true },
  booking_requested: { label: "Booking requested", cls: "bg-indigo-50 text-indigo-700 ring-indigo-200", dot: true },
  booked: { label: "Booked", cls: "bg-emerald-600 text-white ring-emerald-600" },
  confirmed: { label: "Confirmed", cls: "bg-emerald-700 text-white ring-emerald-700" },
  lost: { label: "Lost", cls: "bg-zinc-100 text-zinc-600 ring-zinc-300" },
  needs_human: { label: "Needs you", cls: "bg-red-50 text-red-700 ring-red-300" },
  expired: { label: "Expired", cls: "bg-zinc-100 text-zinc-500 ring-zinc-200" },
  failed: { label: "Failed", cls: "bg-red-600 text-white ring-red-600" },
};

export function StatusChip({ status, lg }: { status: Status; lg?: boolean }) {
  const c = CHIP[status] ?? { label: String(status).replaceAll("_", " "), cls: "bg-zinc-100 text-zinc-600 ring-zinc-200" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full ring-1 ring-inset font-medium ${c.cls} ${lg ? "px-2.5 py-1 text-sm" : "px-2 py-0.5 text-xs"}`}>
      {c.dot && <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-current" />}
      {c.label}
    </span>
  );
}

// Seconds elapsed from arrival, live.
function useClock(): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(t); }, []);
  return now;
}

// Compact countdown used in list rows.
export function Countdown({ receivedAt, quotedAt, status }: { receivedAt: number; quotedAt: number | null; status: Status }) {
  const now = useClock();
  if (quotedAt) {
    const s = Math.round(quotedAt - receivedAt);
    return <span className={`num text-xs ${s <= 120 ? "text-emerald-700" : "text-amber-700"}`}>quoted in {s}s</span>;
  }
  if (status === "expired") return <span className="num text-xs text-zinc-400">expired</span>;
  const left = Math.round(receivedAt + EXPIRY_S - now);
  if (left <= 0) return <span className="num text-xs text-red-600">expired</span>;
  const m = Math.floor(left / 60), s = left % 60;
  return <span className={`num text-xs ${left < 120 ? "text-red-600 font-semibold" : "text-zinc-500"}`}>{m}:{String(s).padStart(2, "0")} left</span>;
}

// Hero clock for the operator panel. The system is scored on speed, so the clock is the loudest thing on screen.
export function BigClock({ receivedAt, quotedAt, status }: { receivedAt: number; quotedAt: number | null; status: Status }) {
  const now = useClock();
  const settled = status === "expired" || status === "failed" || status === "lost";

  if (quotedAt) {
    const s = Math.round(quotedAt - receivedAt);
    const good = s <= 120;
    return (
      <div>
        <div className="flex items-baseline gap-2">
          <span className={`num text-4xl font-semibold tracking-tight ${good ? "text-emerald-600" : "text-amber-600"}`}>{s}s</span>
          <span className="text-sm text-zinc-500">to quote</span>
        </div>
        <div className="mt-1 text-xs text-zinc-500">{good ? "Full time points (under 120 s)" : "Over 120 s — partial time points"}</div>
      </div>
    );
  }

  const left = Math.round(receivedAt + EXPIRY_S - now);
  const elapsed = Math.max(0, EXPIRY_S - left);
  const pct = Math.min(100, (elapsed / EXPIRY_S) * 100);
  const expired = left <= 0 || settled;
  const m = Math.max(0, Math.floor(left / 60)), s = Math.max(0, left % 60);
  const tone = expired ? "text-zinc-400" : left < 120 ? "text-red-600" : left < 240 ? "text-amber-600" : "text-zinc-800";
  const barTone = expired ? "bg-zinc-300" : left < 120 ? "bg-red-500" : left < 240 ? "bg-amber-400" : "bg-emerald-500";
  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className={`num text-4xl font-semibold tracking-tight ${tone}`}>{expired ? "0:00" : `${m}:${String(s).padStart(2, "0")}`}</span>
        <span className="text-sm text-zinc-500">{expired ? "expired" : "until this RFQ expires"}</span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-zinc-100">
        <div className={`h-1.5 rounded-full transition-all ${barTone}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-zinc-400">
        <span className="num">{Math.round(elapsed)}s elapsed</span>
        <span>full points under 120 s</span>
      </div>
    </div>
  );
}

export function money(total: string, currency = "EUR") {
  return `${Number(total).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

// Cheapest option by euro value. Score counts a quote only within 5% of the best price, so the best is worth marking.
export function bestOption(options: Option[]): Option | null {
  const priced = options.filter((o) => Number(o.total_eur) > 0);
  if (!priced.length) return null;
  return priced.reduce((a, b) => (Number(b.total_eur) < Number(a.total_eur) ? b : a));
}

export function sameOption(a: Option | null, b: Option | null): boolean {
  return !!a && !!b && a.airline === b.airline && a.total === b.total;
}

export const LANG_FLAG: Record<string, string> = { en: "EN", de: "DE", fr: "FR", it: "IT", es: "ES" };
