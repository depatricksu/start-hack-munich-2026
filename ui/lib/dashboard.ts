// Server-only: everything the forwarder dashboard shows, derived read-only from the runner DB (or demo data).
// Rule: no invented numbers. The only made-up values are the shipment step + ETA, flagged as simulated in the UI.
import { getDb } from "./db";
import { getSessions, parse, rowToSession } from "./data";
import { fakeDetail } from "./fake";
import { getCarrierFlags } from "./invoices";
import { EXPIRY_S, EventRow, Session } from "./types";
import type {
  CarrierRow, CustomerRow, DashData, FeedDot, FeedItem, Kpi, LaneRow, QueueItem, Shipment, ShipStep, Tone,
} from "./dashboard-types";

const H = 3600;
const DAY = 86400;
const WON = ["confirmed", "booked"];
const COUNTDOWN = ["new", "waiting_bids", "sending"];
const QUOTE_OUT = ["quoted", "booking", "booking_requested", "awaiting_docs"];
const NEEDS = ["needs_human", "failed"];

export function toneOf(status: string): Tone {
  if (WON.includes(status)) return "won";
  if (status === "needs_human") return "human";
  if (status === "failed") return "broken";
  if (COUNTDOWN.includes(status) || QUOTE_OUT.includes(status)) return "progress";
  return "over";
}

const eurFmt = (n: number) => n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const priceOf = (s: Session): string | null =>
  s.chosen && Number(s.chosen.total) > 0 ? `${eurFmt(Number(s.chosen.total))} ${s.chosen.currency || "EUR"}` : null;
const eurOf = (s: Session) => (s.chosen ? Number(s.chosen.total_eur) || 0 : 0);
const quoteSent = (s: Session) => s.quoted_at != null || WON.includes(s.status) || s.status === "lost";

function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const a = [...xs].sort((x, y) => x - y);
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

// Note codes the clerk writes ("door_pickup: ...") in plain words. Unknown codes keep the raw text.
const REASON: Record<string, string> = {
  door_pickup: "Door pickup needs a trucker price",
  rfq_expired: "Request expired before we saw it",
  llm_regex_mismatch: "Read values do not match the mail text",
  missing: "Request is missing details",
  no_lane: "No price for this lane",
  dg: "Dangerous goods: check the documents",
};
function plainReason(note: string | null, why: string | null): string {
  const raw = (why || note || "").trim();
  if (!raw) return "Waiting for a person";
  const m = /^([a-z_]+):\s*(.*)$/.exec(raw);
  if (m && REASON[m[1]]) return m[2] ? `${REASON[m[1]]} (${m[2]})` : REASON[m[1]];
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function queueItem(s: Session, why: string | null): QueueItem {
  return {
    id: s.thread_id, customer: s.customer, origin: s.fields.origin ?? null, destination: s.fields.destination ?? null,
    status: s.status, received_at: s.received_at, quoted_at: s.quoted_at,
    reason: NEEDS.includes(s.status) ? plainReason(s.note, why) : null, price: priceOf(s), tone: toneOf(s.status),
  };
}

// 24 hourly buckets ending at `end`. `pick` returns the value a session adds to its bucket (or null to skip).
function buckets(end: number, sessions: Session[], at: (s: Session) => number | null): Session[][] {
  const out: Session[][] = Array.from({ length: 24 }, () => []);
  for (const s of sessions) {
    const t = at(s);
    if (t == null || t > end || t <= end - DAY) continue;
    const i = 23 - Math.floor((end - t) / H);
    if (i >= 0 && i < 24) out[i].push(s);
  }
  return out;
}

function pct(n: number, of: number): number | null {
  return of ? Math.round((n / of) * 100) : null;
}

function kpis(sessions: Session[], end: number) {
  const inWin = (s: Session) => s.received_at <= end && s.received_at > end - DAY;
  const win = sessions.filter(inWin);
  const b = buckets(end, sessions, (s) => s.received_at);

  const sent = (xs: Session[]) => xs.filter(quoteSent);
  const won = (xs: Session[]) => xs.filter((s) => WON.includes(s.status));
  const value = (xs: Session[]) => won(xs).reduce((a, s) => a + eurOf(s), 0);

  const requests: Kpi = {
    value: win.length, sub: "requests in", allTime: `${sessions.length} all time`, spark: b.map((x) => x.length),
  };
  // Average value of a won shipment: a forwarder's view of the business (not how fast the system was).
  const avg = (xs: Session[]) => (won(xs).length ? Math.round(value(xs) / won(xs).length) : 0);
  const avgK: Kpi = {
    value: avg(win), sub: "per won shipment",
    allTime: won(sessions).length ? `${avg(sessions).toLocaleString("en-GB")} EUR all time` : "no wins yet",
    spark: b.map((x) => avg(x)),
  };
  const accepted: Kpi = {
    value: pct(won(win).length, sent(win).length),
    sub: `${won(win).length} of ${sent(win).length} quotes`,
    allTime: sent(sessions).length ? `${pct(won(sessions).length, sent(sessions).length)}% all time` : "no quotes yet",
    spark: b.map((x) => pct(won(x).length, sent(x).length)),
  };
  const booked: Kpi = {
    value: Math.round(value(win)), sub: `${won(win).length} won`,
    allTime: `${Math.round(value(sessions)).toLocaleString("en-GB")} EUR all time`, spark: b.map((x) => Math.round(value(x))),
  };
  return { requests, avg: avgK, accepted, booked };
}

// ---------- live feed ----------

function feedFrom(events: (EventRow & { thread_id: number | null })[], byId: Map<number, Session>, trackRef: Map<number, string>): FeedItem[] {
  const out: FeedItem[] = [];
  const bidGroup = new Map<number, FeedItem>(); // thread -> its bid line
  const askGroup = new Map<number, FeedItem>();
  const asks = new Map<number, number>(); // thread -> how many bid requests went out
  for (const e of events) { // newest first
    const d = e.data;
    const th = e.thread_id;
    const s = th != null ? byId.get(th) : undefined;
    const lane = s?.fields.origin && s?.fields.destination ? `${s.fields.origin} → ${s.fields.destination}` : null;
    const push = (label: string, detail: string | null, tone: Tone) => {
      // A repeat of a line already shown for this thread (e.g. several customer replies) adds nothing: keep the newest.
      if (out.some((o) => o.thread === th && th != null && o.label === label)) return;
      out.push({ key: `e${e.id}`, ts: e.ts, thread: th, label, detail, tone });
    };
    switch (e.kind) {
      case "mail_in": {
        const r = String(d.route ?? "");
        if (r === "rfq") push("New request", [lane, String(d.sender ?? "")].filter(Boolean).join(" · "), "progress");
        else if (r === "follow_up") push("Customer replied", String(d.sender ?? "") || null, "neutral");
        else if (r === "tracking") push("Tracking question in", String(d.sender ?? "") || null, "neutral");
        break;
      }
      case "quote_sent": {
        const c = (d.chosen ?? {}) as Record<string, unknown>;
        const total = Number(c.total);
        const secs = s ? Math.round(e.ts - s.received_at) : null;
        const label = ["Quote sent", total > 0 ? `${eurFmt(total)} ${c.currency ?? "EUR"}` : null]
          .filter(Boolean).join(" · ");
        push(label, [lane, c.airline ? String(c.airline) : null].filter(Boolean).join(" · ") || null,
          secs != null && secs > EXPIRY_S ? "broken" : "progress");
        break;
      }
      case "bid_received": {
        if (th == null) break;
        const dot: FeedDot = { carrier: String(d.carrier ?? "?"), status: String(d.status ?? "?"), late: d.late === true };
        const g = bidGroup.get(th);
        if (g) { g.dots!.push(dot); break; }
        const item: FeedItem = { key: `b${th}-${e.id}`, ts: e.ts, thread: th, label: "Bids in", detail: lane, tone: "progress", dots: [dot] };
        bidGroup.set(th, item);
        out.push(item);
        break;
      }
      case "bid_requested": {
        if (th == null) break;
        const g = askGroup.get(th);
        if (g) { asks.set(th, (asks.get(th) ?? 1) + 1); break; }
        const item: FeedItem = { key: `a${th}-${e.id}`, ts: e.ts, thread: th, label: "Asked for bids", detail: lane, tone: "neutral" };
        askGroup.set(th, item);
        out.push(item);
        break;
      }
      case "bid_picked":
        push(`Picked ${d.role ?? "bid"} · ${d.carrier ?? "?"}`, d.total_eur ? `${eurFmt(Number(d.total_eur))} EUR` : null, "progress");
        break;
      case "waiting_bids":
        push("Waiting for bids", lane, "progress");
        break;
      case "booking_confirmed":
        push(`Booked ${d.booking_reference ?? ""}`.trim(), lane, "won");
        break;
      case "customer_informed":
        push("Customer informed", d.message ? String(d.message) : null, "won");
        break;
      case "tracking_answered":
        push(d.matched === false ? "Tracking question: no match" : "Tracking question answered",
          (th != null ? trackRef.get(th) : null) ?? lane, d.matched === false ? "human" : "won");
        break;
      case "needs_human":
        push("Needs you", d.why ? plainReason(null, String(d.why)) : null, "human");
        break;
      case "alarm_posted":
        push("Alarm", d.headline ? String(d.headline).replaceAll("`", "") : null, "broken");
        break;
      case "portal_down":
      case "portal_hold":
        push("Rate portal down · quote held", d.why ? String(d.why) : lane, "broken");
        break;
      case "loop_error": {
        const prev = out[out.length - 1];
        if (prev && prev.label.startsWith("Loop error")) { // collapse a run of the same error
          const n = Number(/×(\d+)/.exec(prev.label)?.[1] ?? 1) + 1;
          prev.label = `Loop error ×${n}`;
          break;
        }
        push("Loop error", d.error ? String(d.error).slice(0, 90) : null, "broken");
        break;
      }
    }
    if (out.length >= 40) break;
  }
  for (const [th, item] of askGroup) {
    const n = asks.get(th) ?? 1;
    item.label = `Asked ${n} carrier${n === 1 ? "" : "s"} for a price`;
  }
  // Order by the newest event in each line (grouped lines keep the time of their latest event).
  return out.sort((a, b) => b.ts - a.ts).slice(0, 30);
}

// ---------- shipments (SIMULATED step + ETA) ----------

const STEPS: ShipStep[] = ["Booked", "Picked up", "Departed", "Arrived", "Delivered"];
function simulate(bookedAt: number, transitDays: number | null, now: number) {
  const t = Math.max(1, transitDays ?? 3) * DAY;
  const marks = [bookedAt, bookedAt + 4 * H, bookedAt + 12 * H, bookedAt + 12 * H + t, bookedAt + 24 * H + t];
  let i = 0;
  for (let k = 0; k < marks.length; k++) if (now >= marks[k]) i = k;
  return { step: STEPS[i], stepIndex: i, eta: marks[4] };
}

// ---------- tables ----------

function pricing(sessions: Session[]): { lanes: LaneRow[]; total: LaneRow } {
  const rows = new Map<string, { quotes: number; asks: number; cheapest: number; over: number[] }>();
  const total = { quotes: 0, asks: 0, cheapest: 0, over: [] as number[] };
  for (const s of sessions) {
    if (!s.chosen || !quoteSent(s) || !s.options.length) continue;
    const min = Math.min(...s.options.map((o) => Number(o.total_eur)).filter((n) => n > 0));
    const ours = Number(s.chosen.total_eur);
    if (!Number.isFinite(min) || !(ours > 0)) continue;
    const lane = `${s.fields.origin ?? "?"} → ${s.fields.destination ?? "?"}`;
    const r = rows.get(lane) ?? { quotes: 0, asks: 0, cheapest: 0, over: [] };
    for (const x of [r, total]) {
      x.quotes++;
      if (s.fields.prefer === "cheapest") {
        x.asks++;
        if (ours <= min + 0.005) x.cheapest++;
        x.over.push(((ours - min) / min) * 100);
      }
    }
    rows.set(lane, r);
  }
  const toRow = (lane: string, r: typeof total): LaneRow =>
    ({ lane, quotes: r.quotes, asks: r.asks, cheapest: r.cheapest, medianOverPct: median(r.over) });
  const lanes = [...rows.entries()].sort((a, b) => b[1].quotes - a[1].quotes).slice(0, 6).map(([l, r]) => toRow(l, r));
  return { lanes, total: toRow("All lanes", total) };
}

function customers(sessions: Session[]): CustomerRow[] {
  const m = new Map<string, CustomerRow>();
  for (const s of sessions) {
    if (!s.customer) continue;
    const r = m.get(s.customer) ?? { customer: s.customer, requests: 0, quotes: 0, won: 0, languages: [] };
    r.requests++;
    if (quoteSent(s)) r.quotes++;
    if (WON.includes(s.status)) r.won++;
    const lang = (s.fields.language || "").toLowerCase();
    if (lang && !r.languages.includes(lang)) r.languages.push(lang);
    m.set(s.customer, r);
  }
  return [...m.values()].sort((a, b) => b.requests - a.requests || b.won - a.won).slice(0, 8);
}

// ---------- main ----------

export function getDashboard(): DashData {
  const now = Date.now() / 1000;
  const { source, sessions: list } = getSessions();
  const db = source === "live" ? getDb() : null;
  const sessions: Session[] = db
    ? (db.prepare("SELECT * FROM sessions ORDER BY received_at DESC").all() as Record<string, unknown>[]).map(rowToSession)
    : list;
  const byId = new Map(sessions.map((s) => [s.thread_id, s]));

  // Raw rows (empty in demo mode).
  type Ev = EventRow & { thread_id: number | null };
  const q = <T,>(sql: string, ...args: unknown[]): T[] => {
    if (!db) return [];
    try { return db.prepare(sql).all(...args) as T[]; } catch { return []; }
  };
  const events: Ev[] = db
    ? q<Record<string, unknown>>("SELECT id, ts, thread_id, kind, data FROM events ORDER BY id DESC LIMIT 800")
      .map((e) => ({ id: e.id as number, ts: e.ts as number, thread_id: (e.thread_id as number) ?? null, kind: e.kind as string, data: parse(e.data, {}) }))
    : sessions.flatMap((s) => (fakeDetail(s.thread_id)?.events ?? []).map((e) => ({ ...e, id: s.thread_id * 100 + e.id, thread_id: s.thread_id })))
      .sort((a, b) => b.ts - a.ts);

  // Window: the last 24 h, or the 24 h up to the last activity when the data is older (a snapshot).
  const lastActivity = Math.max(0, ...sessions.map((s) => s.received_at), events[0]?.ts ?? 0);
  const windowIsNow = lastActivity > now - DAY;
  const windowEnd = windowIsNow ? now : lastActivity;

  // Latest "why" per thread from needs_human events (plainer than the session note).
  const why = new Map<number, string>();
  for (const r of q<{ thread_id: number; data: string }>("SELECT thread_id, data FROM events WHERE kind='needs_human' ORDER BY id")) {
    const w = parse<{ why?: string }>(r.data, {}).why;
    if (w) why.set(r.thread_id, w);
  }

  const needs = sessions.filter((s) => NEEDS.includes(s.status)).map((s) => queueItem(s, why.get(s.thread_id) ?? null));
  const flight = sessions.filter((s) => COUNTDOWN.includes(s.status) || QUOTE_OUT.includes(s.status)).map((s) => queueItem(s, null));
  const doneAll = sessions.filter((s) => !NEEDS.includes(s.status) && !COUNTDOWN.includes(s.status) && !QUOTE_OUT.includes(s.status));

  // Rate portal: down if a portal_down/hold came in the last 30 min and no portal price went out after it.
  const down = q<{ ts: number }>("SELECT ts FROM events WHERE kind IN ('portal_down','portal_hold','portal_booking_down_mail') ORDER BY id DESC LIMIT 1")[0];
  const okRow = q<{ ts: number }>("SELECT ts FROM events WHERE kind='quote_sent' AND json_extract(data,'$.chosen.source')='portal' ORDER BY id DESC LIMIT 1")[0];
  let portal: DashData["portal"] = { state: "unknown", at: null, text: "" };
  if (down && down.ts > now - 1800 && (!okRow || okRow.ts < down.ts)) portal = { state: "down", at: down.ts, text: "Airline prices unavailable since" };
  else if (okRow) portal = { state: "ok", at: okRow.ts, text: "Airline prices available · last price" };

  const lastMail = q<{ t: number | null }>("SELECT MAX(received_at) AS t FROM mails")[0]?.t
    ?? (sessions.length ? Math.max(...sessions.map((s) => s.received_at)) : null);

  // Shipments: the bookings table when it exists, else won sessions with a booking_confirmed reference.
  const informed = new Set(q<{ t: number }>("SELECT DISTINCT thread_id AS t FROM events WHERE kind='customer_informed'").map((r) => r.t));
  // Tracking questions arrive in their own thread; tracking_lookup links that thread to the booking it matched.
  const trackRef = new Map<number, string>(); // tracking thread -> booking reference
  const tracked = new Set<number>(); // booking threads whose tracking question we answered
  for (const r of q<{ t: number; b: number | null; ref: string | null }>(`SELECT l.thread_id AS t, json_extract(l.data,'$.booking.thread_id') AS b,
      json_extract(l.data,'$.booking.booking_reference') AS ref FROM events l WHERE l.kind='tracking_lookup'
      AND EXISTS (SELECT 1 FROM events a WHERE a.kind='tracking_answered' AND a.thread_id=l.thread_id AND a.id > l.id)`)) {
    if (r.b != null) tracked.add(r.b);
    if (r.ref) trackRef.set(r.t, r.ref);
  }
  type B = { thread_id: number; booking_reference: string; customer: string; origin: string | null; destination: string | null;
    airline: string | null; transit_days: number | null; price: string | null; currency: string | null; at: number };
  let books = q<B>(`SELECT thread_id, booking_reference, customer, origin, destination, airline, transit_days, price, currency,
    COALESCE(confirmed_at, booked_at, created_at) AS at FROM bookings
    WHERE booking_reference IS NOT NULL AND COALESCE(status,'') <> 'cancelled' ORDER BY at DESC`);
  if (!books.length) {
    books = q<{ thread_id: number; ref: string; ts: number }>(
      "SELECT thread_id, json_extract(data,'$.booking_reference') AS ref, MAX(ts) AS ts FROM events WHERE kind='booking_confirmed' GROUP BY thread_id ORDER BY ts DESC")
      .flatMap((r) => {
        const s = byId.get(r.thread_id);
        if (!s || !WON.includes(s.status) || !r.ref) return [];
        return [{ thread_id: s.thread_id, booking_reference: r.ref, customer: s.customer, origin: s.fields.origin ?? null,
          destination: s.fields.destination ?? null, airline: s.chosen?.airline ?? null, transit_days: s.chosen?.transit_days ?? null,
          price: s.chosen?.total ?? null, currency: s.chosen?.currency ?? null, at: r.ts }];
      });
  }
  const shipments: Shipment[] = books.slice(0, 12).map((b) => ({
    thread: b.thread_id, ref: b.booking_reference, customer: b.customer, origin: b.origin, destination: b.destination,
    airline: b.airline, price: b.price && Number(b.price) > 0 ? `${eurFmt(Number(b.price))} ${b.currency || "EUR"}` : null,
    booked_at: b.at, transit_days: b.transit_days, ...simulate(b.at, b.transit_days, now),
    tracking_answered: tracked.has(b.thread_id), customer_informed: informed.has(b.thread_id),
  }));

  // Carriers: every bid we asked for, ranked by how often they answered.
  const carriers: CarrierRow[] = (() => {
    const rows = q<{ carrier: string; role: string; requested_at: number; replied_at: number | null; status: string; total_eur: string | null }>(
      "SELECT carrier, COALESCE(role, kind, '') AS role, requested_at, replied_at, status, total_eur FROM bids WHERE carrier IS NOT NULL");
    const m = new Map<string, { role: string; asked: number; replied: number; offers: number; secs: number[]; eur: number[] }>();
    for (const r of rows) {
      const k = `${r.carrier}|`;  // one row per carrier, whatever kind of bid we asked for
      const x = m.get(k) ?? { role: r.role, asked: 0, replied: 0, offers: 0, secs: [], eur: [] };
      if (r.role === "ratedesk" || r.role === "trucker") x.role = r.role;
      x.asked++;
      if (r.replied_at && r.status !== "send_failed") { x.replied++; if (r.requested_at) x.secs.push(r.replied_at - r.requested_at); }
      if (r.status === "ok" && Number(r.total_eur) > 0) { x.offers++; x.eur.push(Number(r.total_eur)); }
      m.set(k, x);
    }
    // Patrick's reliability flags (monitor/carriers.py): red / amber carriers go first, with the reason.
    const flags = new Map(getCarrierFlags().map((f) => [f.carrier, f]));
    const rank = (f: string | null) => (f === "red" ? 0 : f === "amber" ? 1 : 2);
    return [...m.entries()].map(([k, x]) => {
      const f = flags.get(k.split("|")[0]);
      const flag = f && (f.level === "red" || f.level === "amber") ? f.level : null;
      return { carrier: k.split("|")[0], role: x.role, asked: x.asked, replied: x.replied,
        offers: x.offers, medianReplyS: median(x.secs), medianEur: median(x.eur), flag, reasons: flag ? f!.reasons : [] };
    })
      .sort((a, b) => rank(a.flag) - rank(b.flag) || b.replied - a.replied || b.offers - a.offers).slice(0, 8);
  })();

  return {
    source, now, windowEnd, windowIsNow,
    needsYou: needs.length, portal, lastMail,
    kpis: kpis(sessions, windowEnd),
    queue: { needs, flight, done: doneAll.slice(0, 10).map((s) => queueItem(s, null)), doneTotal: doneAll.length },
    feed: feedFrom(events, byId, trackRef),
    shipments, shipmentsTotal: books.length,
    pricing: pricing(sessions),
    carriers,
    customers: customers(sessions),
  };
}
