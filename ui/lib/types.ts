// Shapes the UI uses. They mirror docs/ui-data.md (tables sessions, events, bids in data/forwarder.db).
export type Status = "new" | "waiting_bids" | "sending" | "quoted" | "booking" | "booking_requested" | "booked" | "confirmed" | "lost" | "needs_human" | "expired" | "failed";

// Statuses where our quote has already gone out.
export const QUOTE_SENT: Status[] = ["quoted", "booking", "booking_requested", "booked", "confirmed", "lost"];

export type Option = {
  airline: string;
  total: string;
  currency: string;
  total_eur: string;
  transit_days: number;
  source: "sheet" | "portal" | "bid" | string;
  rate_id?: string | null;
  valid_until?: string | null;
};

export type Fields = {
  origin?: string | null;
  destination?: string | null;
  pickup_postcode?: string | null;
  weight_kg?: number | null;
  volume_cbm?: number | null;
  prefer?: "cheapest" | "fastest";
  language?: string | null;
  missing?: string[];
  // several shipments in one request: each has its own lane, weight and volume; the request itself has none
  shipments?: { origin?: string | null; destination?: string | null; weight_kg?: number | null; volume_cbm?: number | null }[] | null;
};

export type Session = {
  thread_id: number;
  customer: string;
  subject: string;
  status: Status;
  fields: Fields;
  options: Option[];
  chosen: Option | null;
  reply: string | null;
  note: string | null;
  received_at: number; // unix seconds
  deadline: number | null; // end of bid wait, NOT the expiry
  quoted_at: number | null;
  llm_cost_usd: number | null;
};

export type EventRow = { id: number; ts: number; kind: string; data: Record<string, unknown> };
// A file on a mail: the customer's (request as PDF / Word / voice message, packing list) or ours (the offer PDF).
export type FileRef = { filename: string; bytes: number | null; type: string | null };
export type MailRow = { id: number; sender: string; subject: string; body: string; received_at: number; route: string | null; files?: FileRef[] };

export type ActionRow = { id: number; kind: string; body: string; created_at: number; done_at: number | null; result: string | null };

export type SessionDetail = Session & { events: EventRow[]; mails: MailRow[]; actions: ActionRow[]; reply_files: FileRef[] };

export type Stats = {
  total: number;
  quoted: number;
  needs_human: number;
  open: number;
  median_response_s: number | null;
  cost_per_quote_usd: number | null;
  response_times: number[];
};

export const EXPIRY_S = 360; // an RFQ expires 6 minutes after arrival
