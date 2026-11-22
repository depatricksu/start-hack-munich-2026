"use client";
import { useEffect, useState } from "react";
import { EXPIRY_S, Option, Status } from "@/lib/types";

// Glass monochrome: white = done, faint glass = in progress/attention. No red, no pulsing.
const CHIP: Record<Status, { label: string; cls: string; dot?: boolean }> = {
  new: { label: "New", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  waiting_bids: { label: "Waiting for bids", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  sending: { label: "Sending", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  quoted: { label: "Quoted", cls: "bg-white text-black ring-white" },
  booking: { label: "Booking", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  booking_requested: { label: "Booking requested", cls: "bg-white/8 text-zinc-300 ring-white/10", dot: true },
  booked: { label: "Booked", cls: "bg-white text-black ring-white" },
  confirmed: { label: "Confirmed", cls: "bg-white text-black ring-white" },
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
  if (quotedAt) {
    const s = Math.round(quotedAt - receivedAt);
    return <span className="num text-xs text-zinc-300">quoted in {s}s</span>;
  }
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
    const s = Math.round(quotedAt - receivedAt);
    return (
      <div>
        <div className="flex items-baseline gap-2">
          <span className="num text-4xl font-semibold tracking-tight text-white">{s}s</span>
          <span className="text-sm text-zinc-500">to quote</span>
        </div>
        <div className="mt-1 text-xs text-zinc-500">{s <= 120 ? "Full time points (under 120 s)" : "Over 120 s"}</div>
      </div>
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
        <span className="text-sm text-zinc-500">{expired ? "expired" : "until this RFQ expires"}</span>
      </div>
      <div className="mt-2 h-1.5 w-full rounded-full bg-white/10">
        <div className={`h-1.5 rounded-full transition-all ${expired ? "bg-white/25" : "bg-white/70"}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-zinc-500">
        <span className="num">{Math.round(elapsed)}s elapsed</span>
        <span>full points under 120 s</span>
      </div>
    </div>
  );
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
