"use client";
import { useEffect, useState } from "react";
import { EXPIRY_S, Status } from "@/lib/types";

const CHIP: Record<Status, { label: string; cls: string }> = {
  new: { label: "New", cls: "bg-sky-50 text-sky-700 ring-sky-200" },
  waiting_bids: { label: "Waiting for bids", cls: "bg-amber-50 text-amber-800 ring-amber-200" },
  sending: { label: "Sending", cls: "bg-sky-50 text-sky-700 ring-sky-200" },
  quoted: { label: "Quoted", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  booking: { label: "Booking", cls: "bg-indigo-50 text-indigo-700 ring-indigo-200" },
  booking_requested: { label: "Booking requested", cls: "bg-indigo-50 text-indigo-700 ring-indigo-200" },
  booked: { label: "Booked", cls: "bg-emerald-600 text-white ring-emerald-600" },
  confirmed: { label: "Confirmed", cls: "bg-emerald-700 text-white ring-emerald-700" },
  lost: { label: "Lost", cls: "bg-zinc-100 text-zinc-600 ring-zinc-300" },
  needs_human: { label: "Needs human", cls: "bg-red-50 text-red-700 ring-red-300" },
  expired: { label: "Expired", cls: "bg-zinc-100 text-zinc-500 ring-zinc-200" },
  failed: { label: "Failed", cls: "bg-red-600 text-white ring-red-600" },
};

export function StatusChip({ status }: { status: Status }) {
  const c = CHIP[status] ?? { label: String(status).replaceAll("_", " "), cls: "bg-zinc-100 text-zinc-600 ring-zinc-200" };
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${c.cls}`}>{c.label}</span>;
}

// Countdown to expiry = arrival + 360 s. NOT the bid-wait deadline.
export function Countdown({ receivedAt, quotedAt, status }: { receivedAt: number; quotedAt: number | null; status: Status }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(t); }, []);
  if (quotedAt) {
    const s = Math.round(quotedAt - receivedAt);
    const good = s <= 120;
    return <span className={`num text-xs ${good ? "text-emerald-700" : "text-amber-700"}`}>quoted in {s}s</span>;
  }
  if (status === "expired") return <span className="num text-xs text-zinc-400">expired</span>;
  const left = Math.round(receivedAt + EXPIRY_S - now);
  if (left <= 0) return <span className="num text-xs text-red-600">expired</span>;
  const m = Math.floor(left / 60), s = left % 60;
  const urgent = left < 120;
  return <span className={`num text-xs ${urgent ? "text-red-600 font-semibold" : "text-zinc-500"}`}>{m}:{String(s).padStart(2, "0")} left</span>;
}

export function money(total: string, currency = "EUR") {
  return `${Number(total).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export const LANG_FLAG: Record<string, string> = { en: "EN", de: "DE", fr: "FR", it: "IT", es: "ES" };
