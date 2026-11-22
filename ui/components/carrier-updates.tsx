"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import type { ShipmentUpdates, Tone, Update } from "@/lib/carriers";

// Color = state only: green done, blue in progress / info, amber needs a person, red delay or cancel, grey over.
export const TONE: Record<Tone, string> = {
  green: "bg-emerald-400/12 text-emerald-300 ring-emerald-400/25",
  blue: "bg-sky-400/12 text-sky-300 ring-sky-400/25",
  amber: "bg-amber-400/12 text-amber-300 ring-amber-400/25",
  red: "bg-red-400/12 text-red-300 ring-red-400/25",
  grey: "bg-white/5 text-zinc-400 ring-white/10",
};

export const at = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
export const carrierHref = (name: string) => `/carriers?id=${encodeURIComponent(name)}`;

export function Chip({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${TONE[tone]}`}>{children}</span>;
}

export function Told({ u }: { u: Update }) {
  if (u.told === "n/a") return null;
  return u.told === "yes"
    ? <span className="text-[11px] text-emerald-300/90" title={`Mail to the customer ${at(u.told_at)}`}>Customer told ✓</span>
    : <Chip tone="amber">Customer not told yet</Chip>;
}

const FROM: Record<Update["from"], string> = { carrier: "", customer: "from the customer", us: "by us" };

// One update: type, date, booking, one line, and the original mail on demand.
export function UpdateItem({ u, showCarrier, showShipment }: { u: Update; showCarrier?: boolean; showShipment?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-xl bg-white/[0.02] px-3 py-2.5 ring-1 ring-inset ring-white/7">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={u.tone}>{u.label}</Chip>
        <span className="num text-xs text-zinc-400">{at(u.ts)}</span>
        {FROM[u.from] && <span className="text-[11px] text-zinc-500">{FROM[u.from]}</span>}
        {showCarrier && u.carrier && u.from === "carrier" && (
          <Link href={carrierHref(u.carrier)} className="text-xs text-zinc-300 hover:text-white hover:underline">{u.carrier}</Link>
        )}
        <span className="ml-auto"><Told u={u} /></span>
      </div>
      <div className="mt-1 text-[13px] text-zinc-200">{u.summary}</div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-zinc-500">
        {u.booking_ref && <span>Booking <span className="num text-zinc-300">{u.booking_ref}</span></span>}
        {showShipment && u.thread != null && (
          <Link href={`/shipments?id=${u.thread}`} className="hover:text-white">
            <span className="num text-zinc-300">{u.lane}</span>{u.company && <span> · {u.company}</span>}
          </Link>
        )}
        {u.thread == null && u.from === "carrier" && <span className="text-zinc-500">Not about one of our shipments</span>}
        {u.dates.length > 0 && <span>Dates <span className="num text-zinc-300">{u.dates.join(", ")}</span></span>}
        {u.flight && <span>Flight <span className="num text-zinc-300">{u.flight}</span></span>}
        {u.awb && <span>AWB <span className="num text-zinc-300">{u.awb}</span></span>}
        {u.match && u.match !== "our log" && <span className="text-zinc-600">matched by {u.match}</span>}
        {u.mail && (
          <button onClick={() => setOpen((o) => !o)} className="ml-auto text-zinc-400 hover:text-white">{open ? "Hide mail" : "Show mail"}</button>
        )}
      </div>
      {open && u.mail && (
        <div className="mt-2 rounded-lg bg-black/20 p-3 ring-1 ring-inset ring-white/6">
          <div className="text-xs text-zinc-500"><span className="num">{u.mail.sender}</span> · {u.mail.subject}</div>
          <pre className="num mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-zinc-400">{u.mail.body}</pre>
        </div>
      )}
    </div>
  );
}

// Small block for the shipment detail: what the carriers said about this shipment, newest first.
export function ShipmentCarrierUpdates({ thread }: { thread: number }) {
  const [data, setData] = useState<ShipmentUpdates | null>(null);
  useEffect(() => {
    let alive = true;
    const get = () => fetch(`/api/carriers/shipment/${thread}`, { cache: "no-store" }).then((r) => r.json())
      .then((j: ShipmentUpdates) => { if (alive) setData(j); }).catch(() => {});
    get();
    const t = setInterval(get, 10000);
    return () => { alive = false; clearInterval(t); };
  }, [thread]);
  const d = data && data.thread === thread ? data : null;
  return (
    <section className="rounded-2xl glass p-5">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-white">Carrier updates</h2>
        {d?.status && <span className="text-xs text-zinc-500">Carrier says: <span className="text-zinc-300">{d.status}</span></span>}
        {d && d.not_told > 0 && <span className="ml-auto"><Chip tone="amber">{d.not_told} not told to the customer</Chip></span>}
      </div>
      <p className="mt-0.5 text-xs text-zinc-500">Read from the carriers&apos; mails. Every carrier update should reach the customer.</p>
      <div className="mt-3 space-y-2">
        {!d && <p className="text-[13px] text-zinc-500">Loading…</p>}
        {d && d.updates.length === 0 && <p className="text-[13px] text-zinc-500">No mail from the carriers about this shipment yet.</p>}
        {d?.updates.map((u) => <UpdateItem key={u.id} u={u} />)}
      </div>
    </section>
  );
}
