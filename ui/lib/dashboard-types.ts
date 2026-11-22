// Shapes for the forwarder dashboard (/dashboard). Built on the server by lib/dashboard.ts, read by components/dash.tsx.
import type { Status } from "./types";

export type Tone = "won" | "progress" | "human" | "broken" | "over" | "neutral";

export type Kpi = {
  value: number | null; // null = nothing to measure in the window
  sub: string; // plain words, e.g. "41 of 52 quotes"
  allTime: string; // same figure over all data
  spark: (number | null)[]; // 24 hourly buckets, oldest first
};

export type QueueItem = {
  id: number;
  customer: string;
  origin: string | null;
  destination: string | null;
  status: Status | string;
  received_at: number;
  quoted_at: number | null;
  reason: string | null; // plain words, needs-you rows only
  price: string | null; // "1,182.28 EUR"
  tone: Tone;
};

export type FeedDot = { carrier: string; status: string; late: boolean };
export type FeedItem = {
  key: string;
  ts: number;
  thread: number | null;
  label: string;
  detail: string | null;
  tone: Tone;
  dots?: FeedDot[];
};

export type ShipStep = "Booked" | "Picked up" | "Departed" | "Arrived" | "Delivered";
export type Shipment = {
  thread: number;
  ref: string;
  customer: string;
  origin: string | null;
  destination: string | null;
  airline: string | null;
  price: string | null;
  booked_at: number;
  transit_days: number | null;
  step: ShipStep; // SIMULATED from booked_at + transit_days
  stepIndex: number;
  eta: number | null; // SIMULATED
  tracking_answered: boolean;
  customer_informed: boolean;
};

export type LaneRow = { lane: string; quotes: number; asks: number; cheapest: number; medianOverPct: number | null };
export type CarrierRow = { carrier: string; role: string; asked: number; replied: number; offers: number; medianReplyS: number | null; medianEur: number | null; flag: string | null; reasons: string[] };
export type CustomerRow = { customer: string; requests: number; quotes: number; won: number; languages: string[] };

export type DashData = {
  source: "live" | "demo";
  now: number;
  windowEnd: number; // end of the 24 h window (now, or the last activity when the data is older)
  windowIsNow: boolean;
  needsYou: number;
  portal: { state: "down" | "ok" | "unknown"; at: number | null; text: string };
  lastMail: number | null;
  kpis: { requests: Kpi; avg: Kpi; accepted: Kpi; booked: Kpi };
  queue: { needs: QueueItem[]; flight: QueueItem[]; done: QueueItem[]; doneTotal: number };
  feed: FeedItem[];
  shipments: Shipment[];
  shipmentsTotal: number;
  pricing: { lanes: LaneRow[]; total: LaneRow };
  carriers: CarrierRow[];
  customers: CustomerRow[];
};
