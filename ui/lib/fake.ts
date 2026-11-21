// Demo data so every screen looks right before (and without) real traffic. Same shape as the real DB rows.
import { Session, SessionDetail, EventRow, MailRow } from "./types";

const now = () => Date.now() / 1000;

export function fakeSessions(): Session[] {
  const t = now();
  const opt = (airline: string, total: string, days: number, source: string, rate_id?: string) => ({
    airline, total, currency: "EUR", total_eur: total, transit_days: days, source, rate_id: rate_id ?? null, valid_until: null,
  });
  const a = [opt("Riverbend Airlines Cargo", "358.20", 4, "portal", "R-0S9lAq3Oqy"), opt("Cobalt Skylift", "470.70", 3, "sheet"),
    opt("Solace Air Cargo", "483.30", 3, "portal", "R-wzrFBxgjPZ"), opt("Yellowtail Air Freight", "514.80", 2, "sheet")];
  const b = [opt("Wayzata Air Cargo", "471.94", 4, "sheet"), opt("Helix Air Freight", "578.66", 1, "sheet")];
  const c = [opt("Fjordline Air Cargo", "827.65", 3, "portal", "R-fj29x"), opt("Kestrel Airways", "901.10", 6, "sheet")];
  return [
    { thread_id: 1001, customer: "anna.schmidt@customer-example.mail", subject: "Quote HAM to BOG", status: "quoted",
      fields: { origin: "HAM", destination: "BOG", weight_kg: 90, volume_cbm: 0.4, prefer: "cheapest", language: "en" },
      options: a, chosen: a[0], reply: "Hi Anna,\n\nThe all-in price from HAM to BOG with Riverbend Airlines Cargo is 358.20 EUR, transit about 4 days.\n\nBest regards,\nYour forwarding team",
      note: null, received_at: t - 200, deadline: t - 110, quoted_at: t - 168, llm_cost_usd: 0.00015 },
    { thread_id: 1002, customer: "k.weber@kunde-beispiel.mail", subject: "Anfrage MUC nach LAX", status: "waiting_bids",
      fields: { origin: "MUC", destination: "LAX", weight_kg: 150, volume_cbm: 1.2, prefer: "fastest", language: "de" },
      options: c, chosen: null, reply: null, note: null, received_at: t - 48, deadline: t + 42, quoted_at: null, llm_cost_usd: 0.00016 },
    { thread_id: 1003, customer: "ops@nordlicht-trade.mail", subject: "Pickup 80331 Munich to SIN", status: "needs_human",
      fields: { origin: "MUC", destination: "SIN", pickup_postcode: "80331", weight_kg: 420, prefer: "cheapest", language: "en", missing: ["volume_cbm"] },
      options: [], chosen: null, reply: null, note: "door_pickup: door pickup needs a trucker bid, none received yet",
      received_at: t - 130, deadline: t - 40, quoted_at: null, llm_cost_usd: 0.00014 },
    { thread_id: 1004, customer: "buyer@acme.hackloop.mail", subject: "RFQ FRA to LAX 120 kg", status: "booked",
      fields: { origin: "FRA", destination: "LAX", weight_kg: 120, volume_cbm: 0.9, prefer: "cheapest", language: "en" },
      options: b, chosen: b[0], reply: "Hello,\n\nWayzata Air Cargo, 471.94 EUR, transit 4 days.\n\nBest regards,\nYour forwarding team",
      note: null, received_at: t - 900, deadline: t - 810, quoted_at: t - 862, llm_cost_usd: 0.00013 },
    { thread_id: 1005, customer: "j.martin@lyon-fret.mail", subject: "Demande MUC vers JFK", status: "expired",
      fields: { origin: "MUC", destination: "JFK", weight_kg: 60, prefer: "cheapest", language: "fr" },
      options: [], chosen: null, reply: null, note: "rfq_expired: mail was 410 s old when we saw it",
      received_at: t - 1300, deadline: t - 1210, quoted_at: null, llm_cost_usd: null },
  ];
}

export function fakeDetail(id: number): SessionDetail | null {
  const s = fakeSessions().find((x) => x.thread_id === id);
  if (!s) return null;
  const mails: MailRow[] = [{ id, sender: s.customer, subject: s.subject, received_at: s.received_at, route: "rfq",
    body: `Hi, please quote ${s.fields.weight_kg} kg from ${s.fields.origin} to ${s.fields.destination}. ${s.fields.prefer === "fastest" ? "Fastest" : "Cheapest"} option please.` }];
  const ev = (i: number, dt: number, kind: string, data: Record<string, unknown>): EventRow => ({ id: i, ts: s.received_at + dt, kind, data });
  const events: EventRow[] = [ev(1, 0, "mail_in", { route: "rfq" }), ev(2, 4, "llm", { language: s.fields.language, cost_usd: s.llm_cost_usd })];
  if (s.options.length) events.push(ev(3, 9, "options", { count: s.options.length }));
  if (s.status === "waiting_bids") events.push(ev(4, 10, "waiting_bids", { wait_s: 90 }));
  if (s.quoted_at) events.push(ev(5, s.quoted_at - s.received_at, "quote_sent", { airline: s.chosen?.airline, total: s.chosen?.total }));
  if (s.status === "needs_human") events.push(ev(6, 12, "needs_human", { why: s.note }));
  const reply_files = s.quoted_at ? [{ filename: `offer-GOOGLE-${id}.pdf`, bytes: 2253, type: "application/pdf" }] : [];
  return { ...s, events, mails, actions: [], reply_files };
}
