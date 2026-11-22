// Server-only, read-only. Carriers (airlines, truckers, the rate desk) and what their mails mean for our shipments.
// Every carrier mail is matched to its shipment and sorted into a plain update type with simple keyword rules.
// Each carrier update is then checked against the customer side: did a mail go to the customer afterwards?
// Nothing here sends mail or writes to the DB.
import fs from "node:fs";
import path from "node:path";
import { getDb } from "./db";
import { parse } from "./data";
import { getCarrierFlags } from "./invoices";
import { getShipments, type ShipmentRow } from "./shipments";
import { answerWords, awbIn, classify, datesIn, firstSentence, flightIn, keySentence, median, RULES, TYPE, type Tone, type UpdateType } from "./carrier-rules";

export type { Tone, UpdateType } from "./carrier-rules";

// ---------- shapes (pages import these as types) ----------

export type Told = "yes" | "no" | "n/a";
export type Update = {
  id: string; ts: number; type: UpdateType; label: string; tone: Tone;
  from: "carrier" | "customer" | "us"; carrier: string | null;
  thread: number | null; ref: string | null; booking_ref: string | null; company: string | null; lane: string | null;
  match: string | null; // how we found the shipment, in plain words; null = not matched
  summary: string; dates: string[]; flight: string | null; awb: string | null;
  told: Told; told_at: number | null;
  mail: { sender: string; subject: string; body: string } | null;
};
export type CarrierShipment = {
  thread: number; ref: string; booking_ref: string | null; lane: string; status: string; at: number; as: "airline" | "trucker";
  news: string | null; // latest carrier-reported state
};
export type Carrier = {
  key: string; name: string; role: "airline" | "trucker" | "rate desk"; email: string | null;
  shipments: number; cancelled: number; asked: number; answered: number; declined: number; answer_time: string | null;
  flag: { level: "red" | "amber"; reasons: string[]; requests: number[] } | null;
  customers: { company: string; customer: string; shipments: CarrierShipment[] }[];
  updates: number; last_update: number | null;
};
export type CarriersData = {
  available: boolean;
  totals: { in_use: number; known: number; updates_today: number; last_update: number | null; trouble_open: number; not_told: number; not_told_shipments: number; unmatched: number };
  carriers: Carrier[];
  updates: Update[]; // newest first, every carrier mail about a booking + the event-based updates
};
export type ShipmentUpdates = { thread: number; status: string | null; updates: Update[]; not_told: number };

// ---------- data access ----------

type Row = Record<string, unknown>;

function hasTable(name: string): boolean {
  const db = getDb();
  return !!db && !!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(name);
}

function q<T = Row>(sql: string, ...args: unknown[]): T[] {
  const db = getDb();
  if (!db) return [];
  try { return db.prepare(sql).all(...args) as T[]; } catch { return []; }
}

type ListEntry = { name: string; role: "airline" | "trucker"; email: string };
let listCache: ListEntry[] | null = null;
function carrierList(): ListEntry[] {
  if (listCache) return listCache;
  const out: ListEntry[] = [];
  try {
    const file = path.join(process.cwd(), "..", "kit", "start-kit", "carrier-list.csv");
    for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/).slice(1)) {
      const p = line.trim().split(",");
      if (p.length >= 3 && p[0] && p[2]) out.push({ name: p[0], role: p[1] === "trucker" ? "trucker" : "airline", email: p[2].toLowerCase() });
    }
  } catch { /* no list: we still know every carrier from bids and bookings */ }
  listCache = out;
  return out;
}

const RATE_DESK = "Rate desk";
const nameFromAddress = (a: string) => a.split("@")[0].replace(/[-_.]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// ---------- the core: carrier mails → updates ----------

type Booking = {
  thread: number; ref: string; booking_ref: string | null; airline: string | null; airline_code: string | null;
  origin: string | null; destination: string | null; customer: string; status: string; booked_at: number; price: string | null;
};

type Model = {
  bookings: Map<number, Booking>; rows: Map<number, ShipmentRow>;
  updates: Update[]; priceAnswers: Map<string, number>; // carrier → price-answer mails (for the record)
  emailToName: Map<string, string>; nameToEmail: Map<string, string>; roleOf: Map<string, "airline" | "trucker" | "rate desk">;
};

function build(): Model | null {
  if (!hasTable("mails")) return null;
  const shipments = hasTable("bookings") ? getShipments().rows : [];
  const rows = new Map(shipments.map((r) => [r.thread, r]));
  const bookings = new Map<number, Booking>();
  for (const b of q<Row>("SELECT * FROM bookings")) {
    const t = Number(b.thread_id);
    bookings.set(t, {
      thread: t, ref: String(b.team_reference ?? `#${t}`), booking_ref: b.booking_reference ? String(b.booking_reference) : null,
      airline: b.airline ? String(b.airline) : null, airline_code: b.airline_code ? String(b.airline_code) : null,
      origin: b.origin ? String(b.origin) : null, destination: b.destination ? String(b.destination) : null,
      customer: String(b.customer ?? ""), status: String(b.status ?? ""),
      booked_at: Number(b.booked_at ?? b.created_at ?? 0), price: b.price ? String(b.price) : null,
    });
  }
  const byBk = new Map<string, Booking>(), byRef = new Map<string, Booking>();
  for (const b of bookings.values()) { if (b.booking_ref) byBk.set(b.booking_ref.toUpperCase(), b); byRef.set(b.ref.toUpperCase(), b); }

  // Who is a carrier: the start-kit list, every address we asked for a price, the rate desk.
  const emailToName = new Map<string, string>(), nameToEmail = new Map<string, string>();
  const roleOf = new Map<string, "airline" | "trucker" | "rate desk">();
  for (const c of carrierList()) { emailToName.set(c.email, c.name); nameToEmail.set(c.name, c.email); roleOf.set(c.name, c.role); }
  for (const r of q<Row>("SELECT carrier, role, kind, email FROM bids WHERE email IS NOT NULL GROUP BY carrier, role, email")) {
    const role = String(r.role ?? r.kind ?? "");
    const email = String(r.email).toLowerCase();
    if (role === "ratedesk") { emailToName.set(email, RATE_DESK); nameToEmail.set(RATE_DESK, email); roleOf.set(RATE_DESK, "rate desk"); continue; }
    const name = String(r.carrier);
    if (!emailToName.has(email)) emailToName.set(email, name);
    if (!nameToEmail.has(name)) nameToEmail.set(name, email);
    if (!roleOf.has(name)) roleOf.set(name, role === "trucker" ? "trucker" : "airline");
  }
  for (const b of bookings.values()) if (b.airline && !roleOf.has(b.airline)) roleOf.set(b.airline, "airline");

  // Mails our log already tied to a request: price answers (bid_received) and confirmations (booking_confirmed).
  const linked = new Map<number, number>();
  const bidMails = new Set<number>();
  for (const e of q<Row>("SELECT kind, thread_id, mail_id FROM events WHERE mail_id IS NOT NULL AND kind IN ('bid_received','booking_confirmed','bid_extra_reply_ignored')")) {
    const m = Number(e.mail_id);
    if (e.kind !== "booking_confirmed") bidMails.add(m);
    if (e.thread_id != null) linked.set(m, Number(e.thread_id));
  }

  const carrierRoutes = new Set(["booking_confirmation", "carrier_bid", "ratedesk"]);
  const mails = q<Row>("SELECT id, thread_id, sender, subject, body, route, received_at FROM mails ORDER BY received_at");
  const updates: Update[] = [];
  const priceAnswers = new Map<string, number>();

  for (const m of mails) {
    const sender = String(m.sender ?? "").toLowerCase();
    const route = String(m.route ?? "");
    // A carrier mail: routed as one, or from a carrier address whatever the router said (a delay could be routed as a follow-up).
    if (!carrierRoutes.has(route) && !emailToName.has(sender)) continue;
    const id = Number(m.id), subject = String(m.subject ?? ""), body = String(m.body ?? "");
    const ts = Number(m.received_at ?? 0);
    const name = emailToName.get(sender) ?? (route === "ratedesk" ? RATE_DESK : nameFromAddress(sender));
    if (!roleOf.has(name)) roleOf.set(name, route === "ratedesk" ? "rate desk" : "airline");
    if (!nameToEmail.has(name)) nameToEmail.set(name, sender);
    const text = `${subject}\n${body}`;
    const tokens = [...text.toUpperCase().matchAll(/\b[A-Z][A-Z0-9]*-[A-Z0-9]{3,}\b/g)].map((x) => x[0]);
    const bkHit = tokens.map((t) => byBk.get(t)).find(Boolean) ?? null;
    const refHit = tokens.map((t) => byRef.get(t)).find(Boolean) ?? null;

    // Price answers (offers, declines of a lane, rate-desk questions) are the record, not shipment news.
    const looksLikeBid = bidMails.has(id) || route === "ratedesk"
      || /^(re:\s*)*(rate request|rate question|pickup quote|pickup |better price|price request|quote request|dangerous goods)/i.test(subject.trim());
    if (looksLikeBid && !bkHit && !refHit) { priceAnswers.set(name, (priceAnswers.get(name) ?? 0) + 1); continue; }

    // Match to a shipment: our log / same thread, then booking ref, then our ref, then sender = booked airline + lane.
    let b: Booking | null = null, how: string | null = null;
    const viaLog = linked.get(id) ?? (bookings.has(Number(m.thread_id)) ? Number(m.thread_id) : null);
    if (viaLog != null && bookings.has(viaLog)) { b = bookings.get(viaLog)!; how = "same thread"; }
    else if (bkHit) { b = bkHit; how = "booking reference"; }
    else if (refHit) { b = refHit; how = "our reference"; }
    else {
      const lane = /\b([A-Z]{3})\s*(?:-|–|→|to|nach)\s*([A-Z]{3})\b/.exec(text);
      if (lane) {
        const cands = [...bookings.values()].filter((x) => x.airline === name && x.origin === lane[1] && x.destination === lane[2] && x.booked_at <= ts)
          .sort((a, c) => c.booked_at - a.booked_at);
        if (cands[0]) { b = cands[0]; how = "airline + lane"; }
      }
    }

    const type = classify(subject, body);
    const row = b ? rows.get(b.thread) : undefined;
    const lanes = /lane:\s*([A-Z]{3})-([A-Z]{3})/i.exec(body);
    const priceM = /price:\s*([\d.,]+)\s*([A-Z]{3})/i.exec(body);
    const bk = /\b(BK-[A-Z0-9]+)\b/.exec(text)?.[1] ?? b?.booking_ref ?? null;
    const KEY: Partial<Record<UpdateType, RegExp>> = { cancelled: RULES[0][1], delayed: RULES[1][1], rebooked: RULES[2][1], price: RULES[3][1],
      delivered: RULES[4][1], arrived: RULES[5][1], departed: RULES[6][1] };
    let summary = (KEY[type] ? keySentence(body, new RegExp(KEY[type]!.source, "i")) : firstSentence(body)) || subject;
    if (type === "confirmed" || type === "booked") {
      const parts = [type === "confirmed" ? "Booking confirmed" : "Booking accepted, confirmation to follow",
        lanes ? `${lanes[1]} → ${lanes[2]}` : null, priceM ? `${Number(priceM[1].replace(",", "")).toLocaleString("en-GB", { minimumFractionDigits: 2 })} ${priceM[2]}` : null];
      summary = parts.filter(Boolean).join(" · ");
    } else if (!b && type === "price") summary = subject || summary;
    updates.push({
      id: `m${id}`, ts, type, ...TYPE[type], from: "carrier", carrier: name,
      thread: b?.thread ?? null, ref: b?.ref ?? null, booking_ref: bk, company: row?.company ?? null,
      lane: b ? `${b.origin ?? "?"} → ${b.destination ?? "?"}` : lanes ? `${lanes[1]} → ${lanes[2]}` : null,
      match: how, summary, dates: datesIn(body), flight: flightIn(text, b?.airline_code ?? null), awb: awbIn(text),
      told: "n/a", told_at: null, mail: { sender, subject, body },
    });
  }

  // Events complete the timeline: the customer's cancellation, our cancel call, a confirmation that came without a mail.
  const mailUpd = new Set(updates.filter((u) => u.thread != null && u.type === "confirmed").map((u) => u.thread));
  const evs = q<Row>(`SELECT id, ts, thread_id, mail_id, kind, data FROM events
    WHERE kind IN ('after_booking_cancellation','booking_cancel_call','booking_cancelled','booking_confirmed') AND thread_id IS NOT NULL ORDER BY id`);
  const cancelCall = new Set(evs.filter((e) => e.kind === "booking_cancel_call").map((e) => Number(e.thread_id)));
  for (const e of evs) {
    const t = Number(e.thread_id);
    const b = bookings.get(t);
    if (!b) continue;
    const d = parse<Record<string, unknown>>(e.data, {});
    const row = rows.get(t);
    const base = { id: `e${e.id}`, ts: Number(e.ts), thread: t, ref: b.ref, booking_ref: String(d.booking_reference ?? b.booking_ref ?? "") || null,
      company: row?.company ?? null, lane: `${b.origin ?? "?"} → ${b.destination ?? "?"}`, match: "our log", dates: [], flight: null, awb: null,
      told: "n/a" as Told, told_at: null, mail: null };
    if (e.kind === "after_booking_cancellation") {
      const mail = e.mail_id != null ? q<Row>("SELECT sender, subject, body FROM mails WHERE id=?", e.mail_id)[0] : undefined;
      updates.push({ ...base, type: "customer_cancel", ...TYPE.customer_cancel, from: "customer", carrier: b.airline,
        summary: mail ? keySentence(String(mail.body ?? ""), /cancel|storn|withdraw|zurück|not go ahead|no longer/i) || "The customer wrote to cancel." : "The customer wrote to cancel.",
        mail: mail ? { sender: String(mail.sender ?? ""), subject: String(mail.subject ?? ""), body: String(mail.body ?? "") } : null });
    } else if (e.kind === "booking_cancel_call" || (e.kind === "booking_cancelled" && !cancelCall.has(t))) {
      updates.push({ ...base, type: "we_cancelled", ...TYPE.we_cancelled, from: "us", carrier: b.airline,
        summary: `Booking ${base.booking_ref ?? ""} cancelled with ${b.airline ?? "the airline"}${d.by === "hand" ? ", by a person" : ""}.`.replace("  ", " ") });
    } else if (e.kind === "booking_confirmed" && !mailUpd.has(t)) {
      updates.push({ ...base, type: "confirmed", ...TYPE.confirmed, from: "carrier", carrier: b.airline,
        summary: `Booking confirmed by ${b.airline ?? "the airline"} (no mail found, from our log).` });
    }
  }

  // Customer told? A carrier update counts as told once a mail to that customer went out after it.
  const outs = new Map<number, number[]>();
  for (const e of q<Row>(`SELECT thread_id, ts, kind, data FROM events WHERE kind IN ('mail_out','customer_informed') AND thread_id IN (SELECT thread_id FROM bookings)`)) {
    const t = Number(e.thread_id);
    const b = bookings.get(t);
    if (!b) continue;
    if (e.kind === "mail_out") {
      const to = String(parse<Record<string, unknown>>(e.data, {}).to ?? "").toLowerCase();
      if (!to || to !== b.customer.toLowerCase()) continue;
    }
    const l = outs.get(t) ?? [];
    l.push(Number(e.ts));
    outs.set(t, l);
  }
  for (const u of updates) {
    if (u.from !== "carrier" || u.thread == null) continue;
    const after = (outs.get(u.thread) ?? []).filter((x) => x >= u.ts).sort((a, c) => a - c)[0];
    u.told = after != null ? "yes" : "no";
    u.told_at = after ?? null;
  }

  updates.sort((a, c) => c.ts - a.ts);
  return { bookings, rows, updates, priceAnswers, emailToName, nameToEmail, roleOf };
}

const TROUBLE: UpdateType[] = ["delayed", "cancelled"];
const NEWS: UpdateType[] = ["confirmed", "booked", "delayed", "cancelled", "rebooked", "departed", "arrived", "delivered", "price"];

// What the shipment's state is from the carrier side, in one word. A cancelled booking is over, whatever was said before.
function newsLabel(m: Model, thread: number): string | null {
  if (m.bookings.get(thread)?.status === "cancelled") return "Cancelled";
  return latestNews(m.updates, thread)?.label ?? null;
}

function latestNews(updates: Update[], thread: number): Update | null {
  return updates.find((u) => u.thread === thread && u.from === "carrier" && NEWS.includes(u.type)) ?? null;
}

// A delay or cancellation stays open until the shipment is over or a later carrier mail says something better.
function troubleOpen(m: Model): Update[] {
  return m.updates.filter((u) => {
    if (!TROUBLE.includes(u.type) || u.from !== "carrier") return false;
    if (u.thread == null) return true;
    if (m.bookings.get(u.thread)?.status === "cancelled") return false;
    return latestNews(m.updates, u.thread)?.id === u.id;
  });
}

const EMPTY: CarriersData = { available: false, totals: { in_use: 0, known: 0, updates_today: 0, last_update: null, trouble_open: 0, not_told: 0, not_told_shipments: 0, unmatched: 0 }, carriers: [], updates: [] };

export function getCarriers(now = Date.now() / 1000): CarriersData {
  const m = build();
  if (!m) return EMPTY;
  const flags = new Map(getCarrierFlags().filter((f) => f.level === "red" || f.level === "amber").map((f) => [f.carrier, f]));

  // Price requests per carrier (the rate desk is one contact, whatever airline we asked it about).
  const asks = new Map<string, { asked: number; answered: number; declined: number; secs: number[] }>();
  for (const r of q<Row>("SELECT carrier, role, kind, status, requested_at, replied_at FROM bids")) {
    const key = String(r.role ?? r.kind) === "ratedesk" ? RATE_DESK : String(r.carrier);
    const a = asks.get(key) ?? { asked: 0, answered: 0, declined: 0, secs: [] };
    const st = String(r.status ?? "");
    if (st === "send_failed") continue;
    a.asked += 1;
    if (r.replied_at != null || ["ok", "declined", "unclear"].includes(st)) a.answered += 1;
    if (st === "declined") a.declined += 1;
    if (r.replied_at != null && r.requested_at != null) a.secs.push(Number(r.replied_at) - Number(r.requested_at));
    asks.set(key, a);
  }

  const names = new Set<string>([...m.roleOf.keys(), ...asks.keys(), ...flags.keys()]);
  const carriers: Carrier[] = [];
  for (const name of names) {
    const ships = [...m.rows.values()].filter((r) => r.airline === name || r.trucker === name);
    const byCustomer = new Map<string, { company: string; customer: string; shipments: CarrierShipment[] }>();
    for (const r of ships) {
      const c = byCustomer.get(r.customer) ?? { company: r.company, customer: r.customer, shipments: [] };
      c.shipments.push({ thread: r.thread, ref: r.ref, booking_ref: r.booking_ref, lane: `${r.origin ?? "?"} → ${r.destination ?? "?"}`,
        status: r.status, at: r.at, as: r.airline === name ? "airline" : "trucker", news: r.airline === name ? newsLabel(m, r.thread) : null });
      byCustomer.set(r.customer, c);
    }
    const a = asks.get(name);
    const f = flags.get(name);
    const mine = m.updates.filter((u) => u.carrier === name && u.from === "carrier");
    const role = m.roleOf.get(name) ?? (f?.role === "trucker" ? "trucker" : f?.role === "ratedesk" ? "rate desk" : "airline");
    carriers.push({
      key: name, name, role, email: m.nameToEmail.get(name) ?? null,
      shipments: ships.length, cancelled: ships.filter((r) => r.status === "cancelled").length,
      asked: a?.asked ?? 0, answered: a?.answered ?? 0, declined: a?.declined ?? 0, answer_time: answerWords(median(a?.secs ?? [])),
      flag: f ? { level: f.level as "red" | "amber", reasons: f.reasons, requests: [...new Set(Object.values(f.examples).flat())].slice(0, 8) } : null,
      customers: [...byCustomer.values()].sort((x, y) => y.shipments.length - x.shipments.length),
      updates: mine.length, last_update: mine[0]?.ts ?? null,
    });
  }
  const lvl = (c: Carrier) => (c.flag?.level === "red" ? 0 : c.flag ? 1 : 2);
  carriers.sort((x, y) => lvl(x) - lvl(y) || y.shipments - x.shipments || y.asked - x.asked || x.name.localeCompare(y.name));

  const midnight = new Date(now * 1000); midnight.setHours(0, 0, 0, 0);
  const carrierUpd = m.updates.filter((u) => u.from === "carrier");
  const notTold = carrierUpd.filter((u) => u.told === "no");
  return {
    available: true,
    totals: {
      in_use: carriers.filter((c) => c.shipments > 0).length, known: carriers.length,
      updates_today: carrierUpd.filter((u) => u.thread != null && u.ts >= midnight.getTime() / 1000).length,
      last_update: carrierUpd.find((u) => u.thread != null)?.ts ?? null,
      trouble_open: troubleOpen(m).length,
      not_told: notTold.length, not_told_shipments: new Set(notTold.map((u) => u.thread)).size,
      unmatched: carrierUpd.filter((u) => u.thread == null).length,
    },
    carriers, updates: m.updates,
  };
}

export function getShipmentUpdates(thread: number): ShipmentUpdates {
  const m = build();
  if (!m) return { thread, status: null, updates: [], not_told: 0 };
  const updates = m.updates.filter((u) => u.thread === thread);
  return { thread, status: newsLabel(m, thread), updates, not_told: updates.filter((u) => u.told === "no").length };
}
