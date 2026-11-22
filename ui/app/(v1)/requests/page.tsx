"use client";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown, FileSpreadsheet, FileText, Mic, Paperclip } from "lucide-react";
import { BigClock, Countdown, LANG_FLAG, StatusChip, bestOption, money, sameOption } from "@/components/bits";
import { FileRef, Option, Session, SessionDetail, Status } from "@/lib/types";
import type { ShipmentDetail } from "@/lib/shipments";

type Source = "live" | "demo";

// What happened, in a forwarder's words. Internal steps (style picks, safety gates, alarms, retries) are not
// listed: a code a forwarder cannot read is left out rather than shown raw.
const EVENT_LABEL: Record<string, string> = {
  mail_in: "Mail received", rfq_in_attachment: "Request read from the attachment", attachments: "Attachments read",
  translated: "Translated", llm: "Request read", unit_fix: "Units converted to kg / cbm",
  origin_from_pickup: "Departure airport chosen from the pickup address", same_as_earlier: "Same cargo as an earlier request",
  dg: "Dangerous goods checked", insurance: "Insurance added", lookalike_sender: "Fake sender caught",
  clarify_asked: "Asked the customer for missing details", clarify_answer: "Customer sent the missing details",
  bid_requested: "Asked carriers for prices", bid_mail_out: "Asked carriers for prices", bid_received: "Carrier price received",
  waiting_bids: "Waiting for carrier prices", bid_wait_over: "Carrier prices in", bids_merged: "Carrier prices compared",
  bid_picked: "Trucker chosen", trucker_estimate: "Trucking estimated",
  options: "Prices compared", multi_options: "Prices compared per shipment", portal_hold: "Waiting for airline prices",
  portal_down: "Airline prices unavailable", portal_estimate: "Price estimated", deadline: "Answer deadline set",
  quote_sent: "Quote sent", offer_file: "Offer PDF attached", requote: "New quote sent", follow_up: "Customer replied",
  follow_up_ignored: "Customer replied, no action needed", follow_up_nudge: "Reminder sent",
  price_confirmed_by_mail: "Price confirmed to the customer", meeting_proposed: "Call offered",
  booking_call: "Flight booked with the airline", booked: "Flight booked", booking_confirmed: "Airline confirmed the booking",
  customer_informed: "Customer informed", sending_docs_book_now: "Booked, documents to follow", awaiting_docs: "Waiting for documents",
  tracking_lookup: "Customer asked for status", tracking_answered: "Status sent to the customer",
  booking_cancel_call: "Booking cancelled with the airline", booking_cancelled: "Booking cancelled",
  after_booking_cancellation: "Customer cancelled", status_corrected: "Status corrected",
  needs_human: "Handed to you", human_action: "Answered by a person", rfq_expired: "Request expired",
};

function useJson<T>(url: string | null, every = 2000): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    const load = () => fetch(url, { cache: "no-store" }).then((r) => r.json()).then((d) => alive && setData(d)).catch(() => {});
    load();
    const t = setInterval(load, every);
    return () => { alive = false; clearInterval(t); };
  }, [url, every]);
  return data;
}

function splitNote(note: string | null): { code: string | null; text: string } {
  if (!note) return { code: null, text: "" };
  const m = /^([a-z_]+):\s*([\s\S]*)$/.exec(note);
  return m ? { code: m[1], text: m[2] } : { code: null, text: note };
}

function fileKB(bytes: number | null): string {
  if (bytes == null) return "";
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function fileKind(f: FileRef): { Icon: typeof FileText; tag: string } {
  const t = (f.type ?? "").toLowerCase();
  const name = f.filename.toLowerCase();
  if (t.startsWith("audio") || /\.(mp3|m4a|wav|ogg)$/.test(name)) return { Icon: Mic, tag: "voice" };
  if (t.includes("spreadsheet") || /\.(xlsx|xls|csv)$/.test(name)) return { Icon: FileSpreadsheet, tag: "sheet" };
  if (t.includes("pdf") || name.endsWith(".pdf")) return { Icon: FileText, tag: "PDF" };
  if (t.includes("word") || /\.docx?$/.test(name)) return { Icon: FileText, tag: "doc" };
  return { Icon: Paperclip, tag: "file" };
}

function FileChips({ files }: { files?: FileRef[] }) {
  if (!files || files.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {files.map((f, i) => {
        const { Icon, tag } = fileKind(f);
        const size = fileKB(f.bytes);
        return (
          <span key={i} className="inline-flex max-w-full items-center gap-1.5 rounded-lg glass-2 px-2 py-1 text-[12px] text-zinc-200">
            <Icon size={13} className="shrink-0 text-zinc-400" />
            <span className="truncate">{f.filename}</span>
            <span className="num shrink-0 text-[10px] uppercase tracking-wide text-zinc-500">{tag}{size ? ` · ${size}` : ""}</span>
          </span>
        );
      })}
    </div>
  );
}

function Route({ s, className }: { s: Session; className?: string }) {
  const f = s.fields;
  return (
    <span className={`num font-semibold ${className ?? ""}`}>
      {f.origin ?? "???"} <span className="text-zinc-600">→</span> {f.destination ?? "???"}
    </span>
  );
}

// ---------- Left panel: the queue ----------

function SessionRow({ s, active, onClick }: { s: Session; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} className="relative w-full rounded-xl px-3 py-2.5 text-left transition hover:bg-white/5">
      {active && (
        <motion.span layoutId="req-active" transition={{ type: "spring", stiffness: 420, damping: 36 }}
          className="absolute inset-0 rounded-xl glass ring-1 ring-inset ring-white/15" />
      )}
      <div className="relative z-10">
        <div className="flex items-center justify-between gap-2">
          <Route s={s} className="text-[15px] text-white" />
          <StatusChip status={s.status} />
        </div>
        <div className="mt-0.5 truncate text-[13px] text-zinc-500">{s.customer}</div>
        <div className="mt-1.5 flex items-center justify-between">
          <Countdown receivedAt={s.received_at} quotedAt={s.quoted_at} status={s.status} />
          <span className="num text-[13px] font-medium text-zinc-200">{s.chosen ? money(s.chosen.total, s.chosen.currency) : "—"}</span>
        </div>
      </div>
    </button>
  );
}

const GROUPS: { key: string; label: string; match: Status[] }[] = [
  { key: "need", label: "Needs you", match: ["needs_human", "failed"] },
  { key: "live", label: "In flight", match: ["new", "waiting_bids", "sending"] },
  { key: "done", label: "Done", match: ["quoted", "booking", "booking_requested", "booked", "confirmed", "lost", "expired"] },
];

function Rail({ sessions, activeId, onSelect, newCount, onClearNew }: { sessions: Session[]; activeId: number | null; onSelect: (id: number) => void; newCount: number; onClearNew: () => void }) {
  const needCount = sessions.filter((s) => s.status === "needs_human" || s.status === "failed").length;
  return (
    <aside className="rail flex w-80 shrink-0 flex-col overflow-y-auto rounded-2xl glass p-3">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
          Requests <span className="num text-zinc-500">{sessions.length}</span>
          {newCount > 0 && (
            <button onClick={onClearNew} title="New since you looked — click to clear"
              className="num rounded-full bg-red-500 px-1.5 py-0.5 text-[11px] font-semibold text-white shadow-[0_0_12px_rgba(239,68,68,0.5)]">
              +{newCount}
            </button>
          )}
        </h2>
        <span className="num text-xs text-zinc-500">live</span>
      </div>
      {needCount > 0 && (
        <div className="mb-3 rounded-xl glass-2 px-3 py-2 text-sm text-zinc-200">
          <span className="font-semibold text-white">{needCount}</span> {needCount === 1 ? "request needs" : "requests need"} you now
        </div>
      )}
      <div className="space-y-3">
        {GROUPS.map((g) => {
          const NEED: string[] = ["needs_human", "failed"];
          const LIVE: string[] = ["new", "waiting_bids", "sending"];
          // "Done" is a catch-all so every real status shows (confirmed, lost, cancelled, awaiting_docs, …).
          const rows = g.key === "done"
            ? sessions.filter((s) => !NEED.includes(s.status) && !LIVE.includes(s.status))
            : sessions.filter((s) => g.match.includes(s.status));
          if (!rows.length) return null;
          return (
            <div key={g.key}>
              <div className="mb-1.5 flex items-center gap-2 px-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                {g.label} <span className="num font-normal text-zinc-600">{rows.length}</span>
              </div>
              <div className="space-y-1">
                {rows.map((s) => <SessionRow key={s.thread_id} s={s} active={s.thread_id === activeId} onClick={() => onSelect(s.thread_id)} />)}
              </div>
            </div>
          );
        })}
        {sessions.length === 0 && <p className="px-1 text-sm text-zinc-500">No requests yet.</p>}
      </div>
    </aside>
  );
}

// ---------- The thread: who said what, when ----------

// Who a mail is from, read off the runner's route. The customer is on the left, we are on the right,
// everyone else (carriers, rate desk, booking and tracking notices) sits in between as a slim note.
const WHO: Record<string, { label: string; side: "customer" | "other" }> = {
  rfq: { label: "Customer", side: "customer" }, follow_up: { label: "Customer", side: "customer" },
  carrier_bid: { label: "Carrier", side: "other" }, ratedesk: { label: "Rate desk", side: "other" },
  tariff: { label: "Tariff", side: "other" }, booking_confirmation: { label: "Booking", side: "other" },
  tracking: { label: "Tracking", side: "other" }, spam: { label: "Spam", side: "other" },
};

// Where a price came from, as a forwarder says it.
function sourceName(src: string): string {
  return ({ sheet: "Rate sheet", portal: "Airline portal", bid: "Carrier offer", ratedesk: "Rate desk", estimate: "Estimate" } as Record<string, string>)[src] ?? src;
}

function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function Body({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 420 || text.split("\n").length > 7;
  return (
    <>
      <div className={`whitespace-pre-wrap break-words ${long && !open ? "line-clamp-6" : ""}`}>{text.trim()}</div>
      {long && (
        <button onClick={() => setOpen(!open)} className="mt-1.5 text-xs font-medium text-zinc-400 hover:text-white">
          {open ? "Show less" : "Show the whole mail"}
        </button>
      )}
    </>
  );
}

function Thread({ d }: { d: SessionDetail }) {
  type Item = { key: string; ts: number; side: "customer" | "other" | "us"; label: string; sender: string; body: string; files?: FileRef[] };
  const items: Item[] = d.mails.map((m) => {
    const w = WHO[m.route ?? ""] ?? (m.sender === d.customer ? WHO.rfq : { label: "Mail", side: "other" as const });
    return { key: `m${m.id}`, ts: m.received_at, side: w.side, label: w.label, sender: m.sender, body: m.body, files: m.files };
  });
  if (d.reply) {
    const last = items.length ? items[items.length - 1].ts : d.received_at;
    items.push({ key: "reply", ts: d.quoted_at ?? last + 0.001, side: "us", label: "Our reply", sender: "sent by Relay", body: d.reply, files: d.reply_files });
  }
  items.sort((x, y) => x.ts - y.ts);
  return (
    <details open className="group rounded-2xl glass-2 p-5">
      <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-white [&::-webkit-details-marker]:hidden">
        <span>Thread <span className="num font-normal text-zinc-500">{items.length}</span></span>
        <ChevronDown size={16} className="text-zinc-500 transition group-open:rotate-180" />
      </summary>
      <ol className="mt-4 space-y-3">
        {items.map((it) => {
          const us = it.side === "us", other = it.side === "other";
          return (
            <li key={it.key} className={`flex ${us ? "justify-end" : "justify-start"}`}>
              <div className={`min-w-0 text-sm ${us ? "max-w-[88%] rounded-2xl rounded-br-md bg-white/[0.09] p-3.5 text-zinc-100 ring-1 ring-inset ring-white/15"
                : other ? "w-full rounded-xl border-l-2 border-white/15 bg-white/[0.02] py-2 pl-3.5 pr-3 text-[13px] text-zinc-400"
                : "max-w-[88%] rounded-2xl rounded-bl-md bg-white/[0.04] p-3.5 text-zinc-200 ring-1 ring-inset ring-white/8"}`}>
                <div className="mb-1.5 flex items-baseline gap-2 text-xs">
                  <span className={`font-semibold ${us ? "text-white" : other ? "text-zinc-300" : "text-zinc-200"}`}>{it.label}</span>
                  <span className="min-w-0 truncate text-zinc-500">{it.sender}</span>
                  <span className="num ml-auto shrink-0 pl-2 text-zinc-500" title={new Date(it.ts * 1000).toLocaleString("en-GB")}>
                    {clock(it.ts)}
                  </span>
                </div>
                <Body text={it.body} />
                <FileChips files={it.files} />
              </div>
            </li>
          );
        })}
        {items.length === 0 && <li className="text-sm text-zinc-500">No mail in this thread yet.</li>}
      </ol>
    </details>
  );
}

// ---------- Centre: the facts ----------

function Fact({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="rounded-xl glass-2 p-3">
      <div className="text-[11px] uppercase tracking-wide text-zinc-500">{k}</div>
      <div className={`num mt-0.5 font-semibold ${warn ? "text-zinc-400" : "text-white"}`}>{v}</div>
    </div>
  );
}

function OptionsTable({ options, chosen }: { options: Option[]; chosen: Option | null }) {
  if (!options.length) return <p className="text-sm text-zinc-500">No prices found yet.</p>;
  const best = bestOption(options);
  const sorted = [...options].sort((a, b) => Number(a.total_eur) - Number(b.total_eur));
  return (
    <table className="w-full text-sm">
      <thead><tr className="text-left text-[11px] uppercase tracking-wide text-zinc-500">
        <th className="py-1 font-medium">Airline</th><th className="font-medium">From</th><th className="font-medium">Days</th><th className="text-right font-medium">Total</th>
      </tr></thead>
      <tbody>
        {sorted.map((o, i) => {
          const isChosen = sameOption(o, chosen);
          const isBest = sameOption(o, best);
          return (
            <tr key={i} className={`border-t border-line ${isChosen ? "bg-white/5" : ""}`}>
              <td className="py-1.5 text-zinc-200">
                <span className={isChosen ? "font-medium text-white" : ""}>{o.airline}</span>
                {isChosen && <span className="ml-2 rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold text-black">QUOTED</span>}
                {isBest && !isChosen && <span className="ml-2 rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-300">CHEAPEST</span>}
              </td>
              <td className="text-zinc-500">{sourceName(o.source)}</td>
              <td className="num text-zinc-300">{o.transit_days}</td>
              <td className="num text-right text-zinc-200">{money(o.total, o.currency)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// The badge answers "did we give the customer what they asked for?": the fastest flight when they wanted
// fast, the lowest price otherwise. "% over cheapest" is only shown when a cheapest-ask was not the cheapest.
function QuoteCard({ chosen, options, prefer }: { chosen: Option; options: Option[]; prefer?: string | null }) {
  const best = bestOption(options);
  const overBest = best && !sameOption(chosen, best) && Number(best.total_eur) > 0
    ? ((Number(chosen.total_eur) - Number(best.total_eur)) / Number(best.total_eur)) * 100 : 0;
  const quickest = options.length ? Math.min(...options.map((o) => o.transit_days)) : chosen.transit_days;
  const badge = prefer === "fastest"
    ? (chosen.transit_days <= quickest ? "fastest option" : `${chosen.transit_days - quickest} days slower than fastest`)
    : overBest > 0.1 ? `+${overBest.toFixed(1)}% over cheapest` : "cheapest option";
  return (
    <div className="rounded-2xl glass glass-hi p-6">
      <div className="flex items-start justify-between">
        <div className="num text-[11px] uppercase tracking-wide text-zinc-400">Our quote</div>
        <span className="rounded-full bg-white/8 px-2.5 py-1 text-xs font-medium text-zinc-300 ring-1 ring-inset ring-white/10">
          {badge}
        </span>
      </div>
      <div className="num mt-2 text-6xl font-semibold tracking-tight text-white">{money(chosen.total, chosen.currency)}</div>
      <div className="mt-2 text-sm text-zinc-400">{chosen.airline} · {chosen.transit_days} days transit · {sourceName(chosen.source)}</div>
    </div>
  );
}

const PROGRESS: Partial<Record<Status, number>> = {
  new: 18, waiting_bids: 46, sending: 78, quoted: 100, booking: 100, booking_requested: 100,
  booked: 100, confirmed: 100, lost: 100, needs_human: 60, expired: 50, failed: 50,
};

function Facts({ d }: { d: SessionDetail }) {
  const f = d.fields;
  const note = splitNote(d.note);
  const lang = (f.language ?? "").toLowerCase();
  return (
    <div className="mx-auto max-w-2xl space-y-5 p-6">
      <div>
        <div className="text-3xl text-white"><Route s={d} /></div>
        <div className="mt-1.5 text-sm text-zinc-400">{d.customer}</div>
        <div className="text-sm text-zinc-500">{d.subject}</div>
        {(() => {
          const reqFiles = d.mails.flatMap((m) => m.files ?? []);
          if (!reqFiles.length) return null;
          return (
            <div className="mt-2.5">
              <div className="mb-1 text-[11px] uppercase tracking-wide text-zinc-500">Came in as</div>
              <FileChips files={reqFiles} />
            </div>
          );
        })()}
      </div>

      {(d.status === "needs_human" || d.status === "failed") && (
        <div className="rounded-2xl glass-2 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            Needs you {note.code && <span className="num rounded bg-white/10 px-1.5 py-0.5 text-xs font-medium text-zinc-200">{note.code}</span>}
          </div>
          <p className="mt-1 text-sm text-zinc-400">{note.text || "Relay could not price this safely. Write the answer on the right."}</p>
        </div>
      )}

      <div className="grid grid-cols-4 gap-3">
        <Fact k="Weight" v={f.weight_kg != null ? `${f.weight_kg} kg` : "?"} warn={f.weight_kg == null} />
        <Fact k="Volume" v={f.volume_cbm != null ? `${f.volume_cbm} cbm` : "?"} warn={f.volume_cbm == null} />
        <Fact k="Wants" v={f.prefer ?? "cheapest"} />
        <Fact k="Language" v={LANG_FLAG[lang] ?? (lang ? lang.toUpperCase() : "?")} />
      </div>

      {d.chosen && <QuoteCard chosen={d.chosen} options={d.options} prefer={f.prefer} />}

      {(d.invoice || (d.watch && d.watch.length > 0)) && (
        <div className="grid gap-3">
          {d.invoice && (
            <a href="/invoices" className="flex items-center gap-3 rounded-2xl glass-2 px-5 py-3.5 transition hover:bg-white/5">
              <span className="text-[11px] uppercase tracking-wide text-zinc-500">Invoice</span>
              <span className="num whitespace-nowrap text-sm text-white">{d.invoice.number}</span>
              <span className="num whitespace-nowrap text-sm text-zinc-300">{money(String(d.invoice.amount), d.invoice.currency)}</span>
              <span className={`ml-auto whitespace-nowrap text-right text-xs ${d.invoice.status === "paid" ? "text-emerald-300"
                : d.invoice.overdue_days > 0 || d.invoice.status === "overdue_human" ? "text-red-300"
                : d.invoice.status === "paid_reported" ? "text-amber-300" : "text-sky-300"}`}>
                {d.invoice.status === "paid" ? "Paid"
                  : d.invoice.status === "cancelled" ? "Cancelled"
                  : d.invoice.status === "paid_reported" ? "Customer says paid, check the bank"
                  : d.invoice.overdue_days > 0 ? `${d.invoice.overdue_days} days overdue`
                  : `Open · due ${new Date(d.invoice.due_at * 1000).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}`}
                {!d.invoice.sent && d.invoice.status !== "paid" && <span className="ml-2 text-zinc-500">draft</span>}
              </span>
            </a>
          )}
          {d.watch?.map((w) => (
            <div key={w.carrier} className={`flex items-center gap-3 rounded-2xl px-5 py-3 ring-1 ring-inset ${w.level === "red" ? "bg-red-400/[0.06] ring-red-400/25" : "bg-amber-400/[0.06] ring-amber-400/25"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${w.level === "red" ? "bg-red-400" : "bg-amber-400"}`} />
              <span className="text-sm text-white">Watch {w.carrier}</span>
              <span className={`text-xs ${w.level === "red" ? "text-red-300" : "text-amber-300"}`}>{w.reasons.join(" · ")}</span>
            </div>
          ))}
        </div>
      )}

      {d.status === "confirmed" && <AfterYes id={d.thread_id} />}

      <section className="rounded-2xl glass-2 p-5">
        <h3 className="mb-2 text-sm font-semibold text-white">Price options <span className="num font-normal text-zinc-500">{d.options.length}</span></h3>
        <OptionsTable options={d.options} chosen={d.chosen} />
      </section>

      <Thread d={d} />
    </div>
  );
}

// Confirmed bookings: one line per party with what went out and what is still a draft (details on /shipments).
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
    <section className="rounded-2xl glass-2 p-5">
      <div className="mb-2 flex items-baseline">
        <h3 className="text-sm font-semibold text-white">After the yes</h3>
        <a href={`/shipments?id=${id}`} className="ml-auto text-xs text-zinc-400 hover:text-white">See all messages</a>
      </div>
      <ul className="space-y-1 text-[13px]">
        {[...parties.entries()].map(([role, p]) => (
          <li key={role} className="flex items-center gap-2">
            <span className="text-zinc-300">{role}</span>
            <span className="ml-auto flex gap-1.5">
              {p.sent > 0 && <span className="rounded-full bg-emerald-400/12 px-2 py-0.5 text-[11px] text-emerald-300 ring-1 ring-inset ring-emerald-400/25">{p.sent} sent</span>}
              {p.draft > 0 && <span className="rounded-full bg-white/6 px-2 py-0.5 text-[11px] text-zinc-300 ring-1 ring-inset ring-white/12">{p.draft} draft{p.draft === 1 ? "" : "s"}</span>}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---------- Right panel: the operator ----------

function StatusProgress({ d }: { d: SessionDetail }) {
  // The number of steps is not fixed: it grows with the email thread. So the bar is driven by
  // the request's state, and the step list is built live from the events that actually happened.
  const pct = PROGRESS[d.status] ?? 12;
  const steps: string[] = [];
  for (const e of d.events) {
    const label = EVENT_LABEL[e.kind];
    if (!label) continue;
    if (steps[steps.length - 1] !== label) steps.push(label);
  }
  const done = d.status === "quoted" || d.status === "booked" || d.status === "confirmed";
  const last = steps[steps.length - 1] ?? "Waiting…";
  const earlier = steps.slice(0, -1).reverse(); // previous steps, newest first
  const [open, setOpen] = useState(false);
  useEffect(() => { setOpen(false); }, [d.thread_id]); // collapse when switching request

  return (
    <div className="mt-4 rounded-2xl glass-2 p-4">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-zinc-400">What happened</h4>
      </div>
      <div className="mt-2 h-2.5 w-full overflow-hidden rounded-full bg-white/10 ring-1 ring-inset ring-white/5">
        <motion.div className={`h-full rounded-full ${done ? "bg-white" : "bar-soft"}`}
          animate={{ width: `${pct}%` }} transition={{ type: "spring", stiffness: 120, damping: 22 }} />
      </div>

      {/* Only the latest step. It cross-fades (blur + slide) each time the state advances. */}
      <div className="mt-4 flex items-start gap-3">
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
          {done
            ? <span className="flex h-4 w-4 items-center justify-center rounded-full bg-white text-black"><Check size={11} strokeWidth={3} /></span>
            : <span className="load-dots"><i /><i /><i /><i /></span>}
        </span>
        <div className="min-w-0 flex-1">
          <AnimatePresence mode="wait">
            <motion.div key={last}
              initial={{ opacity: 0, y: 8, filter: "blur(5px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -8, filter: "blur(5px)" }}
              transition={{ duration: 0.32, ease: "easeOut" }}
              className="truncate text-sm font-medium text-white">
              {last}
            </motion.div>
          </AnimatePresence>
          {earlier.length > 0 && (
            <button onClick={() => setOpen((o) => !o)}
              className="mt-1 flex items-center gap-1 text-xs text-zinc-500 transition hover:text-zinc-300">
              +{earlier.length} more
              <ChevronDown size={12} className={`transition ${open ? "rotate-180" : ""}`} />
            </button>
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="mt-2.5 space-y-2 overflow-hidden border-t border-line pt-2.5">
            {earlier.map((label, i) => (
              <li key={i} className="flex items-center gap-2.5 text-[13px] text-zinc-400">
                <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-white/15 text-white">
                  <Check size={9} strokeWidth={3} />
                </span>
                {label}
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

function Operator({ d }: { d: SessionDetail }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setDraft(d.reply ?? ""); setErr(null); }, [d.thread_id, d.reply]);
  const alreadyQuoted = d.quoted_at != null;
  const pending = d.actions.some((a) => a.done_at == null);
  // Relay answers on its own. Writing to the customer by hand is an override: open only when the request
  // was handed to a person, otherwise behind one small link.
  const needsYou = d.status === "needs_human" || d.status === "failed";
  const [override, setOverride] = useState(needsYou);

  async function send() {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`/api/sessions/${d.thread_id}/send`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: draft }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) setErr(j.error ?? "Could not queue the reply.");
    } catch { setErr("Could not reach the server."); }
    setBusy(false);
  }

  return (
    <aside className="rail flex w-[23rem] shrink-0 flex-col overflow-y-auto rounded-2xl glass p-5">
      <div className="flex items-center justify-between">
        <StatusChip status={d.status} lg />
      </div>

      <div className="mt-4 rounded-2xl glass-2 p-4">
        <BigClock receivedAt={d.received_at} quotedAt={d.quoted_at} status={d.status} />
      </div>

      <StatusProgress d={d} />

      {!override ? (
        <button onClick={() => setOverride(true)} className="mt-5 self-start text-xs text-zinc-500 transition hover:text-zinc-300">
          Override: write to the customer yourself
        </button>
      ) : (
      <div className="mt-5">
        <div className="flex items-baseline">
          <h3 className="text-sm font-semibold text-white">{needsYou ? "Your answer" : "Override"}</h3>
          {!needsYou && <button onClick={() => setOverride(false)} className="ml-auto text-xs text-zinc-500 hover:text-zinc-300">Close</button>}
        </div>
        <p className="mt-1 text-xs leading-relaxed text-zinc-500">
          {alreadyQuoted
            ? "We already quoted. Your message goes out as a normal follow-up in the same thread."
            : "Nothing has gone out yet. Your message becomes our one and only quote in this thread — state one all-in price with its currency."}
        </p>
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={8}
          placeholder="Write your reply to the customer…"
          className="mt-2 w-full rounded-xl glass-2 p-3 text-sm text-white outline-none placeholder:text-zinc-600 focus:ring-1 focus:ring-white/30" />
        <button onClick={send} disabled={busy || !draft.trim()}
          className={`mt-2 w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition disabled:opacity-40 ${
            alreadyQuoted ? "bg-white text-black hover:bg-zinc-200" : "bg-red-500/15 text-red-100 ring-1 ring-inset ring-red-500/30 hover:bg-red-500/25"}`}>
          {busy ? "Queuing…" : alreadyQuoted ? "Send follow-up" : "Send this quote"}
        </button>
        {err && <p className="mt-2 text-xs text-zinc-400">{err}</p>}
        <p className="mt-2 text-[11px] text-zinc-600">The runner sends it within a second. The UI never sends mail itself.</p>
      </div>
      )}

      {d.actions.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">Your actions</h4>
          <ul className="space-y-2 text-xs">
            {d.actions.map((a) => (
              <li key={a.id} className="rounded-xl glass-2 p-2.5">
                <div className="font-medium text-zinc-200">
                  {a.done_at == null ? "Queued — waiting for the runner" : a.result === "sent" ? "Sent" : a.result ?? "done"}
                </div>
                <div className="mt-0.5 line-clamp-2 text-zinc-500">{a.body}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {pending && <p className="mt-3 text-[11px] text-zinc-500">An action is queued. The clerk picks it up on its next poll.</p>}
    </aside>
  );
}

// ---------- Page ----------

// /requests?id=123 opens that request (links from the dashboard and from Ask Relay). useSearchParams needs Suspense.
export default function RequestsPage() {
  return <Suspense fallback={null}><RequestsView /></Suspense>;
}

function RequestsView() {
  const urlId = Number(useSearchParams().get("id")) || null;
  const list = useJson<{ source: Source; sessions: Session[] }>("/api/sessions");
  const [sel, setSel] = useState<number | null>(null);
  const sessions = useMemo(() => list?.sessions ?? [], [list]);

  // Red "+N" when new quotes come in: watch the request count grow between polls.
  const [newCount, setNewCount] = useState(0);
  const prevLen = useRef<number | null>(null);
  useEffect(() => {
    const n = sessions.length;
    if (prevLen.current != null && n > prevLen.current) setNewCount((c) => c + (n - (prevLen.current as number)));
    if (n > 0 || prevLen.current != null) prevLen.current = n;
  }, [sessions.length]);
  const activeId = sel ?? (urlId && sessions.some((s) => s.thread_id === urlId) ? urlId : null) ?? sessions.find((s) => s.status === "needs_human")?.thread_id ?? sessions[0]?.thread_id ?? null;
  const detail = useJson<{ source: Source; session: SessionDetail | null }>(activeId ? `/api/sessions/${activeId}` : null);

  return (
    <div className="flex h-full gap-2 p-2">
      <Rail sessions={sessions} activeId={activeId} onSelect={(id) => { setSel(id); setNewCount(0); }} newCount={newCount} onClearNew={() => setNewCount(0)} />
      <section className="flex-1 overflow-y-auto rounded-2xl glass">
        {detail?.session ? <Facts d={detail.session} /> : <div className="p-10 text-sm text-zinc-500">Select a request.</div>}
      </section>
      {detail?.session && <Operator key={detail.session.thread_id} d={detail.session} />}
    </div>
  );
}
