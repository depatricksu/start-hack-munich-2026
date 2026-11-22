"use client";
import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import type { Carrier, CarriersData, Update } from "@/lib/carriers";
import { at, carrierHref, Chip, UpdateItem } from "@/components/carrier-updates";

const day = (ts: number | null) => (ts ? new Date(ts * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) : "");
const pct = (a: number, b: number) => (b ? `${Math.round((a / b) * 100)}%` : "—");
const ROLE: Record<Carrier["role"], string> = { airline: "Airline", trucker: "Trucker", "rate desk": "Rate desk" };

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: string }) {
  return (
    <div className="rounded-2xl glass px-5 py-4">
      <div className="num text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`num mt-1.5 text-3xl font-semibold tracking-tight ${tone ?? "text-white"}`}>{value}</div>
      <div className="mt-1 text-xs text-zinc-500">{sub}</div>
    </div>
  );
}

function ShipStatus({ s }: { s: string }) {
  return s === "cancelled" ? <Chip tone="grey">Cancelled</Chip> : s === "booked" ? <Chip tone="blue">Waiting for airline</Chip> : <Chip tone="green">Confirmed</Chip>;
}

function FlagDot({ c }: { c: Carrier }) {
  if (!c.flag) return null;
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${c.flag.level === "red" ? "bg-red-400" : "bg-amber-400"}`} title="Carrier to watch" />;
}

function CarrierDetail({ c, updates }: { c: Carrier; updates: Update[] }) {
  const mine = updates.filter((u) => u.carrier === c.name && u.from === "carrier");
  const notTold = mine.filter((u) => u.told === "no").length;
  return (
    <div className="space-y-3">
      <section className="rounded-2xl glass p-5">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-2xl font-semibold tracking-tight text-white">{c.name}</h2>
              <FlagDot c={c} />
            </div>
            <div className="mt-1 text-sm text-zinc-400">{ROLE[c.role]}{c.email && <span className="num ml-2 text-xs text-zinc-500">{c.email}</span>}</div>
          </div>
        </div>

        {c.flag && (
          <div className={`mt-3 rounded-xl px-4 py-2.5 ring-1 ring-inset ${c.flag.level === "red" ? "bg-red-400/[0.06] ring-red-400/25" : "bg-amber-400/[0.06] ring-amber-400/25"}`}>
            <div className={`text-sm ${c.flag.level === "red" ? "text-red-300" : "text-amber-300"}`}>Watch: {c.flag.reasons.join(" · ")}</div>
            {c.flag.requests.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-x-2 text-xs text-zinc-500">
                <span>Requests:</span>
                {c.flag.requests.map((id) => <Link key={id} href={`/requests?id=${id}`} className="num text-zinc-300 hover:text-white hover:underline">#{id}</Link>)}
              </div>
            )}
          </div>
        )}

        <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-zinc-400">Record</h3>
        <dl className="grid grid-cols-[auto_1fr_auto_1fr] gap-x-4 gap-y-1 text-[13px]">
          <dt className="text-zinc-500">Price requests</dt>
          <dd className="num text-zinc-200">{c.asked ? `${c.answered} of ${c.asked} answered (${pct(c.answered, c.asked)})` : "never asked"}</dd>
          <dt className="text-zinc-500">Usual answer time</dt>
          <dd className="text-zinc-200">{c.answer_time ?? "—"}</dd>
          <dt className="text-zinc-500">Said no to the lane</dt>
          <dd className="num text-zinc-200">{c.declined}</dd>
          <dt className="text-zinc-500">Shipments with us</dt>
          <dd className="num text-zinc-200">{c.shipments}{c.cancelled > 0 && <span className="text-zinc-500"> · {c.cancelled} cancelled</span>}</dd>
          <dt className="text-zinc-500">Mails about bookings</dt>
          <dd className="num text-zinc-200">{mine.length}{c.last_update && <span className="text-zinc-500"> · last {at(c.last_update)}</span>}</dd>
          <dt className="text-zinc-500">Customers not told</dt>
          <dd className={`num ${notTold ? "text-amber-300" : "text-zinc-200"}`}>{notTold}</dd>
        </dl>
      </section>

      <section className="rounded-2xl glass p-5">
        <h2 className="text-sm font-semibold text-white">Customers we ship with them</h2>
        <p className="mt-0.5 text-xs text-zinc-500">The client and the carrier on the same shipment. A carrier problem is the client&apos;s problem.</p>
        <div className="mt-3 space-y-3">
          {c.customers.length === 0 && <p className="text-[13px] text-zinc-500">No shipment booked with {c.name} yet.</p>}
          {c.customers.map((k) => (
            <div key={k.customer}>
              <div className="text-[13px] text-white">{k.company} <span className="text-xs text-zinc-600">· {k.customer}</span></div>
              <div className="mt-1 space-y-0.5">
                {k.shipments.map((s) => (
                  <Link key={s.thread} href={`/shipments?id=${s.thread}`} className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-[13px] transition hover:bg-white/[0.04]">
                    <span className="num w-28 text-zinc-300">{s.booking_ref ?? s.ref}</span>
                    <span className="num w-28 text-zinc-200">{s.lane}</span>
                    <span className="text-xs text-zinc-500">{s.as === "trucker" ? "pickup truck" : s.news ? `carrier says: ${s.news}` : "no carrier mail yet"}</span>
                    <span className="num ml-auto text-xs text-zinc-500">{day(s.at)}</span>
                    <ShipStatus s={s.status} />
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl glass p-5">
        <h2 className="text-sm font-semibold text-white">Latest updates from this carrier</h2>
        <p className="mt-0.5 text-xs text-zinc-500">Their mails about bookings, newest first. Price offers are counted in the record above.</p>
        <div className="mt-3 space-y-2">
          {mine.length === 0 && <p className="text-[13px] text-zinc-500">{c.role === "trucker" ? "Truckers have only sent price offers so far. Pickup news will show here." : "No mail about a booking from this carrier yet."}</p>}
          {mine.slice(0, 30).map((u) => <UpdateItem key={u.id} u={u} showShipment />)}
          {mine.length > 30 && <p className="text-xs text-zinc-500">{mine.length - 30} older updates not shown.</p>}
        </div>
      </section>
    </div>
  );
}

function Feed({ updates }: { updates: Update[] }) {
  const [all, setAll] = useState(false);
  // Delays and cancellations first (they need a person), then customers not told, then the rest, newest first.
  const rank = (u: Update) => (u.tone === "red" && u.from === "carrier" ? 0 : u.told === "no" ? 1 : 2);
  const list = [...updates].sort((a, b) => rank(a) - rank(b) || b.ts - a.ts);
  const shown = all ? list : list.slice(0, 12);
  return (
    <section className="rounded-2xl glass p-5">
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold text-white">Updates from all carriers</h2>
        <span className="num text-xs text-zinc-500">{updates.length}</span>
      </div>
      <p className="mt-0.5 text-xs text-zinc-500">Delays and cancellations on top, then updates the customer has not heard about.</p>
      <div className="mt-3 space-y-2">
        {updates.length === 0 && <p className="text-[13px] text-zinc-500">No carrier mail about a booking yet.</p>}
        {shown.map((u) => <UpdateItem key={u.id} u={u} showCarrier showShipment />)}
      </div>
      {list.length > 12 && (
        <button onClick={() => setAll((x) => !x)} className="mt-3 rounded-md glass-2 px-2.5 py-1 text-xs text-zinc-300 hover:text-white">
          {all ? "Show fewer" : `Show all ${list.length}`}
        </button>
      )}
    </section>
  );
}

export default function CarriersPage() {
  return <Suspense fallback={null}><CarriersView /></Suspense>;
}

function CarriersView() {
  const router = useRouter();
  const urlId = useSearchParams().get("id");
  const [data, setData] = useState<CarriersData | null>(null);
  const [role, setRole] = useState<"all" | Carrier["role"]>("all");

  const load = useCallback(() => fetch("/api/carriers", { cache: "no-store" }).then((r) => r.json()).then(setData).catch(() => {}), []);
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  if (!data) return <div className="p-8 text-sm text-zinc-500">Loading carriers…</div>;
  if (!data.available || data.carriers.length === 0) {
    return (
      <div className="h-full p-2"><div className="h-full rounded-2xl glass p-8">
        <h1 className="text-xl font-semibold text-white">Carriers</h1>
        <p className="mt-2 max-w-xl text-sm text-zinc-400">No carriers yet. They show here once we ask an airline or trucker for a price or book with them.</p>
      </div></div>
    );
  }
  const t = data.totals;
  const list = data.carriers.filter((c) => role === "all" || c.role === role);
  const active = urlId ? data.carriers.find((c) => c.key === urlId) ?? null : list[0] ?? null;

  return (
    <div className="h-full overflow-y-auto p-2">
      <div className="mx-auto max-w-[1400px] space-y-3 px-2 py-3">
        <div className="px-1">
          <h1 className="text-xl font-semibold tracking-tight text-white">Carriers</h1>
          <p className="mt-0.5 text-sm text-zinc-500">Airlines, truckers and the rate desk. Their mails become shipment updates, and each update should reach the customer.</p>
        </div>

        <div className="grid grid-cols-4 gap-3">
          <Tile label="Carriers in use" value={String(t.in_use)} sub={`with a shipment · ${t.known} known`} />
          <Tile label="Updates today" value={String(t.updates_today)} sub={t.updates_today ? "carrier mails about bookings" : t.last_update ? `none since midnight · last ${at(t.last_update)}` : "no carrier mail about a booking yet"}
            tone={t.updates_today ? "text-sky-300" : "text-white"} />
          <Tile label="Delays / cancellations" value={String(t.trouble_open)} sub={t.trouble_open ? "open, carrier reported" : "none reported by carriers"} tone={t.trouble_open ? "text-red-300" : "text-white"} />
          <Tile label="Customers not told" value={String(t.not_told)} sub={t.not_told ? `carrier updates on ${t.not_told_shipments} shipment${t.not_told_shipments === 1 ? "" : "s"}` : "every update reached the customer"}
            tone={t.not_told ? "text-amber-300" : "text-white"} />
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] items-start gap-3">
          <section className="rounded-2xl glass p-2">
            <div className="flex items-center gap-1 px-2 py-1.5">
              {(["all", "airline", "trucker", "rate desk"] as const).map((r) => (
                <button key={r} onClick={() => setRole(r)}
                  className={`rounded-md px-2 py-0.5 text-[11px] uppercase tracking-wide transition ${role === r ? "glass-2 text-white" : "text-zinc-500 hover:text-zinc-300"}`}>
                  {r === "all" ? "All" : ROLE[r]}
                </button>
              ))}
              <span className="num ml-auto text-[11px] text-zinc-500">{list.length}</span>
            </div>
            <div className="space-y-0.5">
              {list.map((c) => (
                <button key={c.key} onClick={() => router.replace(carrierHref(c.key), { scroll: false })}
                  className={`block w-full rounded-xl px-3 py-2.5 text-left transition ${c.key === active?.key ? "glass-2" : "hover:bg-white/[0.04]"}`}>
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[13px] text-white">{c.name}</span>
                    <FlagDot c={c} />
                    <span className="ml-auto text-[11px] text-zinc-500">{ROLE[c.role]}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-3 text-xs text-zinc-500">
                    <span><span className="num text-zinc-300">{c.shipments}</span> shipment{c.shipments === 1 ? "" : "s"}</span>
                    <span><span className="num text-zinc-300">{pct(c.answered, c.asked)}</span> answered</span>
                    {c.flag && <span className={`truncate ${c.flag.level === "red" ? "text-red-300" : "text-amber-300"}`}>{c.flag.reasons[0]}</span>}
                  </div>
                </button>
              ))}
              {list.length === 0 && <p className="px-3 py-4 text-[13px] text-zinc-500">No carrier of this kind yet.</p>}
            </div>
          </section>

          <div className="space-y-3">
            {active ? <CarrierDetail c={active} updates={data.updates} />
              : <div className="rounded-2xl glass p-8 text-sm text-zinc-500">{urlId ? "No carrier with this name." : "Select a carrier."}</div>}
            <Feed updates={data.updates} />
          </div>
        </div>
      </div>
    </div>
  );
}
