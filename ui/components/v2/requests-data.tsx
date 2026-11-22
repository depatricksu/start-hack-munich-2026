"use client";
// Plain-word maps and small helpers for the v2 Requests screen. Kept here so the panes stay readable.
import { FileSpreadsheet, FileText, Mic, Paperclip } from "lucide-react";
import type { EventRow, FileRef, Option, Session } from "@/lib/types";

// What happened, in a forwarder's words. Internal steps (style picks, safety gates, retries) are left out
// rather than shown as a raw code.
export const EVENT_LABEL: Record<string, string> = {
  mail_in: "Mail received", rfq_in_attachment: "Request read from the attachment", attachments: "Attachments read",
  translated: "Translated", llm: "Request read", unit_fix: "Units converted to kg and cbm",
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
  invoice_issued: "Invoice drafted",
};

// One step per run of the same label, timed at the first event of that run.
export function timeline(events: EventRow[]): { label: string; ts: number }[] {
  const out: { label: string; ts: number }[] = [];
  for (const e of [...events].sort((a, b) => a.ts - b.ts || a.id - b.id)) {
    const label = EVENT_LABEL[e.kind];
    if (!label) continue;
    if (out[out.length - 1]?.label !== label) out.push({ label, ts: e.ts });
  }
  return out;
}

// Request groups for the filter. "Done" catches every other status so nothing goes missing.
export type Filter = "all" | "need" | "live" | "done";
const NEED = ["needs_human", "failed"];
const LIVE = ["new", "waiting_bids", "sending"];
export function groupOf(s: Session): Exclude<Filter, "all"> {
  return NEED.includes(s.status) ? "need" : LIVE.includes(s.status) ? "live" : "done";
}
export const needsYou = (status: string) => NEED.includes(status);

// The runner writes notes as "code: text". Only the text is for people.
export function noteText(note: string | null): string {
  if (!note) return "";
  const m = /^([a-z_]+):\s*([\s\S]*)$/.exec(note);
  return (m ? m[2] : note).replace(/\s[–—]\s/g, ", ").replace(/[–—]/g, "-");
}

export function sourceName(src: string): string {
  return ({ sheet: "Rate sheet", portal: "Airline portal", bid: "Carrier offer", ratedesk: "Rate desk", estimate: "Estimate" } as Record<string, string>)[src] ?? src;
}

export function bestOption(options: Option[]): Option | null {
  const priced = options.filter((o) => Number(o.total_eur) > 0);
  if (!priced.length) return null;
  return priced.reduce((a, b) => (Number(b.total_eur) < Number(a.total_eur) ? b : a));
}
export const sameOption = (a: Option | null, b: Option | null) => !!a && !!b && a.airline === b.airline && a.total === b.total;

// Did we give the customer what they asked for? Fastest flight when they wanted fast, lowest price otherwise.
export function quoteBadge(chosen: Option, options: Option[], prefer?: string | null): { text: string; good: boolean } {
  if (prefer === "fastest") {
    const quickest = options.length ? Math.min(...options.map((o) => o.transit_days)) : chosen.transit_days;
    return chosen.transit_days <= quickest
      ? { text: "fastest option", good: true }
      : { text: `${chosen.transit_days - quickest} days slower than fastest`, good: false };
  }
  const best = bestOption(options);
  const over = best && !sameOption(chosen, best) && Number(best.total_eur) > 0
    ? ((Number(chosen.total_eur) - Number(best.total_eur)) / Number(best.total_eur)) * 100 : 0;
  return over > 0.1 ? { text: `+${over.toFixed(1)}% over cheapest`, good: false } : { text: "cheapest option", good: true };
}

const SYM: Record<string, string> = { EUR: "€", USD: "$", GBP: "£" };
// Short price for the list: "€1,589".
export function priceShort(o: Option | null): string {
  if (!o) return "";
  const n = Math.round(Number(o.total)).toLocaleString("en-GB");
  return SYM[o.currency] ? `${SYM[o.currency]}${n}` : `${n} ${o.currency}`;
}

// A duration in plain units: "48s", "3m 12s", "2h 5m".
export function span(s: number): string {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
}

export const customerName = (c: string) => c.split("@")[0];

function fileSize(bytes: number | null): string {
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

export function FileChips({ files, className = "" }: { files?: FileRef[]; className?: string }) {
  if (!files || files.length === 0) return null;
  return (
    <div className={`flex flex-wrap gap-1.5 ${className}`}>
      {files.map((f, i) => {
        const { Icon, tag } = fileKind(f);
        const size = fileSize(f.bytes);
        return (
          <span key={i} className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-md border border-[var(--hair-2)] bg-[var(--bg-2)] px-2 text-[13px] text-[var(--fg)]">
            <Icon size={14} className="shrink-0 text-[var(--fg-2)]" />
            <span className="truncate">{f.filename}</span>
            <span className="tnum shrink-0 text-[11px] text-[var(--fg-3)]">{tag}{size ? ` ${size}` : ""}</span>
          </span>
        );
      })}
    </div>
  );
}
