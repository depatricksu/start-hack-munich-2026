"use client";
// Centre pane of v2 Requests: what the customer asked, what we quoted, and the mail thread.
import { useState } from "react";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { Badge, Card, CardHead, Skeleton, day, money, route, useJson } from "@/components/v2/ui";
import { FileChips, bestOption, customerName, needsYou, noteText, quoteBadge, sameOption, sourceName } from "@/components/v2/requests-data";
import type { FileRef, Option, SessionDetail } from "@/lib/types";
import type { ShipmentDetail } from "@/lib/shipments";

const LANG: Record<string, string> = { en: "English", de: "German", fr: "French", it: "Italian", es: "Spanish" };
const clockS = (t: number) => new Date(t * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

function Fact({ k, v, dim }: { k: string; v: string; dim?: boolean }) {
  return (
    <div className="min-w-0 px-4 py-3 first:pl-0">
      <div className="eyebrow">{k}</div>
      <div className={`tnum mt-1 truncate text-[14px] ${dim ? "text-[var(--fg-3)]" : "text-[var(--fg)]"}`}>{v}</div>
    </div>
  );
}

function Facts({ d }: { d: SessionDetail }) {
  const f = d.fields;
  const lang = (f.language ?? "").toLowerCase();
  return (
    <div className="flex flex-wrap divide-x divide-[var(--hair)] border-y border-[var(--hair)]">
      <Fact k="Weight" v={f.weight_kg != null ? `${f.weight_kg} kg` : "not given"} dim={f.weight_kg == null} />
      <Fact k="Volume" v={f.volume_cbm != null ? `${f.volume_cbm} cbm` : "not given"} dim={f.volume_cbm == null} />
      <Fact k="Wants" v={f.prefer === "fastest" ? "Fastest" : "Cheapest"} />
      <Fact k="Language" v={LANG[lang] ?? (lang ? lang.toUpperCase() : "unknown")} dim={!lang} />
      {f.pickup_postcode && <Fact k="Pickup" v={f.pickup_postcode} />}
    </div>
  );
}

function QuoteCard({ chosen, options, prefer }: { chosen: Option; options: Option[]; prefer?: string | null }) {
  const b = quoteBadge(chosen, options, prefer);
  return (
    <Card className="p-6">
      <div className="flex items-center gap-3">
        <span className="eyebrow">Our quote</span>
        <span className="flex-1" />
        <Badge tone={b.good ? "ok" : "warn"}>{b.text}</Badge>
      </div>
      <div className="tnum mt-3 text-[44px] font-semibold leading-none tracking-[-0.04em] text-[var(--fg)]">{money(chosen.total, chosen.currency)}</div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[14px] text-[var(--fg-2)]">
        <span className="text-[var(--fg)]">{chosen.airline}</span>
        <span><span className="tnum">{chosen.transit_days}</span> days transit</span>
        <span>{sourceName(chosen.source)}</span>
      </div>
    </Card>
  );
}

function InvoiceLine({ inv }: { inv: NonNullable<SessionDetail["invoice"]> }) {
  const [text, tone] = inv.status === "paid" ? ["Paid", "text-[var(--ok)]"]
    : inv.status === "cancelled" ? ["Cancelled", "text-[var(--fg-2)]"]
    : inv.status === "paid_reported" ? ["Customer says paid, check the bank", "text-[var(--warn)]"]
    : inv.overdue_days > 0 || inv.status === "overdue_human" ? [`${inv.overdue_days} days overdue`, "text-[var(--bad)]"]
    : [`Open, due ${day(inv.due_at)}`, "text-[var(--fg-2)]"];
  return (
    <Link href="/v2/invoices" className="card flex items-center gap-4 px-5 py-3.5 transition-colors duration-150 hover:bg-[var(--bg-2)]">
      <span className="eyebrow">Invoice</span>
      <span className="tnum whitespace-nowrap text-[14px] text-[var(--fg)]">{inv.number}</span>
      <span className="tnum whitespace-nowrap text-[14px] text-[var(--fg-2)]">{money(inv.amount, inv.currency)}</span>
      <span className="flex-1" />
      {!inv.sent && inv.status !== "paid" && <span className="text-[13px] text-[var(--fg-3)]">Draft</span>}
      <span className={`whitespace-nowrap text-[13px] ${tone}`}>{text}</span>
    </Link>
  );
}

// Confirmed bookings: one line per party with what went out and what is still a draft.
function AfterYes({ id }: { id: number }) {
  const data = useJson<{ shipment: ShipmentDetail | null }>(`/api/shipments/${id}`, 10000);
  const msgs = data?.shipment?.messages ?? [];
  if (!msgs.length) return null;
  const parties = new Map<string, { sent: number; draft: number }>();
  for (const m of msgs) {
    const p = parties.get(m.role) ?? { sent: 0, draft: 0 };
    p[m.state === "sent" ? "sent" : "draft"]++;
    parties.set(m.role, p);
  }
  return (
    <Card>
      <CardHead title="After the yes" right={<Link href={`/v2/shipments?id=${id}`} className="text-[13px] text-[var(--fg-2)] transition-colors hover:text-[var(--fg)]">See all messages</Link>} />
      <ul className="divide-y divide-[var(--hair)]">
        {[...parties.entries()].map(([role, p]) => (
          <li key={role} className="flex items-center gap-2 py-2 text-[13px]">
            <span className="text-[var(--fg)]">{role}</span>
            <span className="flex-1" />
            {p.sent > 0 && <Badge tone="ok">{p.sent} sent</Badge>}
            {p.draft > 0 && <Badge>{p.draft} draft{p.draft === 1 ? "" : "s"}</Badge>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function OptionsTable({ options, chosen }: { options: Option[]; chosen: Option | null }) {
  if (!options.length) return <p className="text-[13px] text-[var(--fg-2)]">No prices found yet.</p>;
  const best = bestOption(options);
  const sorted = [...options].sort((a, b) => Number(a.total_eur) - Number(b.total_eur));
  // Mark exactly one row as quoted: same airline, price and source first, else the first same airline and price.
  const exact = sorted.findIndex((o) => sameOption(o, chosen) && o.source === chosen?.source);
  const chosenIdx = exact >= 0 ? exact : sorted.findIndex((o) => sameOption(o, chosen));
  return (
    <table className="w-full text-[13px]">
      <thead>
        <tr className="text-left">
          <th className="eyebrow pb-2 font-normal">Airline</th>
          <th className="eyebrow pb-2 font-normal">From</th>
          <th className="eyebrow pb-2 text-right font-normal">Days</th>
          <th className="eyebrow pb-2 text-right font-normal">Total</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((o, i) => {
          const isChosen = i === chosenIdx;
          const isBest = o === best;
          return (
            <tr key={i} className={`border-t border-[var(--hair)] ${isChosen ? "bg-[var(--accent-soft)]" : ""}`}>
              <td className="py-2 pl-2 pr-3">
                <span className="flex items-center gap-2">
                  <span className={isChosen ? "font-medium text-[var(--fg)]" : "text-[var(--fg)]"}>{o.airline}</span>
                  {isChosen && <Badge tone="info">Quoted</Badge>}
                  {isBest && <Badge>Cheapest</Badge>}
                </span>
              </td>
              <td className="pr-3 text-[var(--fg-2)]">{sourceName(o.source)}</td>
              <td className="tnum pr-3 text-right text-[var(--fg-2)]">{o.transit_days}</td>
              <td className="tnum pr-2 text-right text-[var(--fg)]">{money(o.total, o.currency)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ---------- the thread ----------

const WHO: Record<string, { label: string; side: "customer" | "other" }> = {
  rfq: { label: "Customer", side: "customer" }, follow_up: { label: "Customer", side: "customer" },
  carrier_bid: { label: "Carrier", side: "other" }, ratedesk: { label: "Rate desk", side: "other" },
  tariff: { label: "Tariff", side: "other" }, booking_confirmation: { label: "Booking", side: "other" },
  tracking: { label: "Tracking", side: "other" }, spam: { label: "Spam", side: "other" },
};

function Body({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 420 || text.split("\n").length > 7;
  return (
    <>
      <div className={`whitespace-pre-wrap break-words leading-relaxed ${long && !open ? "line-clamp-6" : ""}`}>{text.trim()}</div>
      {long && (
        <button onClick={() => setOpen(!open)} className="mt-2 text-[13px] font-medium text-[var(--accent)] transition-opacity duration-150 hover:opacity-80">
          {open ? "Show less" : "Show the whole mail"}
        </button>
      )}
    </>
  );
}

function Thread({ d }: { d: SessionDetail }) {
  type It = { key: string; ts: number; side: "customer" | "other" | "us"; label: string; sender: string; body: string; files?: FileRef[] };
  const items: It[] = d.mails.map((m) => {
    const w = WHO[m.route ?? ""] ?? (m.sender === d.customer ? WHO.rfq : { label: "Mail", side: "other" as const });
    return { key: `m${m.id}`, ts: m.received_at, side: w.side, label: w.label, sender: m.sender, body: m.body, files: m.files };
  });
  if (d.reply) {
    const last = items.length ? items[items.length - 1].ts : d.received_at;
    items.push({ key: "reply", ts: d.quoted_at ?? last + 0.001, side: "us", label: "Our reply", sender: "sent by Relay", body: d.reply, files: d.reply_files });
  }
  items.sort((x, y) => x.ts - y.ts);
  return (
    <Card>
      <CardHead title="Mail thread" hint={`${items.length} ${items.length === 1 ? "mail" : "mails"}`} />
      {items.length === 0 ? <p className="text-[13px] text-[var(--fg-2)]">No mail in this thread yet.</p> : (
        <ol className="space-y-3">
          {items.map((it) => {
            const us = it.side === "us", other = it.side === "other";
            return (
              <li key={it.key} className={`flex ${us ? "justify-end" : "justify-start"}`}>
                <div className={`min-w-0 ${us ? "max-w-[85%] rounded-xl border border-[var(--hair-2)] bg-[var(--bg-3)] p-4 text-[14px] text-[var(--fg)]"
                  : other ? "w-full border-l-2 border-[var(--hair-2)] py-1 pl-3 text-[13px] text-[var(--fg-2)]"
                  : "max-w-[85%] rounded-xl border border-[var(--hair)] bg-[var(--bg-2)] p-4 text-[14px] text-[var(--fg)]"}`}>
                  <div className="mb-1.5 flex items-baseline gap-2 text-[12px]">
                    <span className="font-medium text-[var(--fg)]">{it.label}</span>
                    <span className="min-w-0 truncate text-[var(--fg-3)]">{it.sender}</span>
                    <span className="tnum ml-auto shrink-0 pl-2 text-[var(--fg-3)]" title={new Date(it.ts * 1000).toLocaleString("en-GB")}>
                      {day(it.ts)} {clockS(it.ts)}
                    </span>
                  </div>
                  <Body text={it.body} />
                  <FileChips files={it.files} className="mt-2.5" />
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

export function RequestDetail({ d }: { d: SessionDetail }) {
  const files = d.mails.filter((m) => m.route === "rfq" || m.sender === d.customer).flatMap((m) => m.files ?? []);
  const human = needsYou(d.status);
  return (
    <div className="mx-auto max-w-[760px] space-y-6 px-8 py-7">
      {human && (
        <div className="flex gap-3 rounded-xl border border-[color-mix(in_srgb,var(--warn)_30%,transparent)] bg-[var(--warn-soft)] p-4">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-[var(--warn)]" />
          <div>
            <div className="text-[14px] font-medium text-[var(--warn)]">{d.status === "failed" ? "This request failed" : "This request needs you"}</div>
            <p className="mt-1 text-[14px] text-[var(--fg)]">{noteText(d.note) || "Relay could not price this safely. Write the answer on the right."}</p>
          </div>
        </div>
      )}

      <header>
        <div className="tnum text-[32px] font-semibold leading-tight tracking-[-0.04em] text-[var(--fg)]">{route(d.fields.origin, d.fields.destination)}</div>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-2 text-[14px]">
          <span className="text-[var(--fg)]">{customerName(d.customer)}</span>
          <span className="tnum text-[13px] text-[var(--fg-3)]">#{d.thread_id}</span>
        </div>
        <p className="mt-1 text-[14px] text-[var(--fg-2)]">{d.subject}</p>
        {files.length > 0 && (
          <div className="mt-4">
            <div className="eyebrow mb-1.5">Came in as</div>
            <FileChips files={files} />
          </div>
        )}
      </header>

      <Facts d={d} />

      {d.chosen && <QuoteCard chosen={d.chosen} options={d.options} prefer={d.fields.prefer} />}

      {(d.invoice || (d.watch && d.watch.length > 0)) && (
        <div className="space-y-2">
          {d.invoice && <InvoiceLine inv={d.invoice} />}
          {d.watch?.map((w) => {
            const red = w.level === "red";
            return (
              <div key={w.carrier} className="card flex items-center gap-3 px-5 py-3">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${red ? "bg-[var(--bad)]" : "bg-[var(--warn)]"}`} />
                <span className="text-[14px] text-[var(--fg)]">Watch {w.carrier}</span>
                <span className={`min-w-0 truncate text-[13px] ${red ? "text-[var(--bad)]" : "text-[var(--warn)]"}`}>{w.reasons.join(", ")}</span>
              </div>
            );
          })}
        </div>
      )}

      {d.status === "confirmed" && <AfterYes id={d.thread_id} />}

      <Card>
        <CardHead title="Price options" hint={`${d.options.length} found, cheapest first`} />
        <OptionsTable options={d.options} chosen={d.chosen} />
      </Card>

      <Thread d={d} />
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="mx-auto max-w-[760px] space-y-6 px-8 py-7">
      <div className="space-y-3"><Skeleton className="h-9 w-56" /><Skeleton className="h-4 w-40" /><Skeleton className="h-4 w-72" /></div>
      <div className="flex gap-8 border-y border-[var(--hair)] py-3">{[0, 1, 2, 3].map((i) => <div key={i} className="space-y-2"><Skeleton className="h-3 w-14" /><Skeleton className="h-4 w-20" /></div>)}</div>
      <div className="card space-y-4 p-6"><Skeleton className="h-3 w-20" /><Skeleton className="h-11 w-64" /><Skeleton className="h-4 w-48" /></div>
      <div className="card space-y-3 p-5"><Skeleton className="h-4 w-32" />{[0, 1, 2].map((i) => <Skeleton key={i} className="h-7 w-full" />)}</div>
    </div>
  );
}
