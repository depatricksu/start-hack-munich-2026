// "Ask Relay": find cases in the runner's data from plain words. No AI call: it reads the query with fixed rules
// (request number, booking ref, airports, status, language, time, customer, words in the mails), so it is
// instant, free, and never touches the 5U gateway that the live quotes are scored on.
import { getDb } from "./db";
import { AIRPORTS } from "./airports";
import { getSessions, rowToSession } from "./data";
import { Session } from "./types";

export type Hit = { s: Session; why: string[]; booking: string | null };
export type SearchResult = { query: string; understood: string[]; hits: Hit[]; total: number; summary: string };

const STATUS_WORDS: Record<string, string[]> = {
  lost: ["lost"], won: ["confirmed", "booked"], confirmed: ["confirmed"], booked: ["booked", "confirmed"],
  expired: ["expired"], cancelled: ["cancelled"], canceled: ["cancelled"], ignored: ["ignored"], spam: ["ignored"],
  open: ["new", "waiting_bids", "sending", "quoted", "awaiting_docs"], waiting: ["waiting_bids", "awaiting_docs"],
  stuck: ["awaiting_docs", "needs_human", "failed"], human: ["needs_human", "failed"], failed: ["failed"],
};
const LANGS: Record<string, string> = {
  english: "en", german: "de", deutsch: "de", french: "fr", italian: "it", spanish: "es", turkish: "tr",
  korean: "ko", chinese: "zh", japanese: "ja", portuguese: "pt", dutch: "nl", polish: "pl",
};
// Words that carry no meaning for the search ("show me all lost requests from today").
const STOP = new Set(["show", "me", "all", "the", "a", "an", "of", "for", "from", "to", "in", "on", "with", "and",
  "requests", "request", "cases", "case", "quotes", "quote", "shipments", "shipment", "find", "search", "what",
  "which", "where", "is", "are", "was", "were", "my", "our", "us", "please", "status", "list", "any", "that",
  "needs", "need", "you", "by", "mails", "mail", "customer", "customers", "lane", "route", "->", "→"]);

const H = 3600;

function bookingRefs(): Map<number, string> {
  const db = getDb();
  const out = new Map<number, string>();
  if (!db) return out;
  try {
    for (const r of db.prepare("SELECT thread_id, booking_reference FROM bookings WHERE booking_reference IS NOT NULL").all() as { thread_id: number; booking_reference: string }[])
      out.set(r.thread_id, r.booking_reference);
  } catch { /* no bookings table in older DBs */ }
  try {
    for (const r of db.prepare("SELECT thread_id, json_extract(data,'$.booking_reference') AS ref FROM events WHERE kind='booking_confirmed' AND thread_id IS NOT NULL").all() as { thread_id: number; ref: string | null }[])
      if (r.ref && !out.has(r.thread_id)) out.set(r.thread_id, r.ref);
  } catch { /* ignore */ }
  return out;
}

// Threads whose mails contain every one of the words (subject or body).
function mailMatches(words: string[]): Set<number> | null {
  const db = getDb();
  if (!db || !words.length) return null;
  const where = words.map(() => "(lower(subject) LIKE ? OR lower(body) LIKE ?)").join(" AND ");
  const args = words.flatMap((w) => [`%${w}%`, `%${w}%`]);
  const rows = db.prepare(`SELECT DISTINCT thread_id FROM mails WHERE thread_id IS NOT NULL AND ${where}`).all(...args) as { thread_id: number }[];
  return new Set(rows.map((r) => r.thread_id));
}

export function search(raw: string, limit = 30): SearchResult {
  const query = raw.trim();
  const { sessions } = getSessions();
  const refs = bookingRefs();
  const understood: string[] = [];
  if (!query) return { query, understood, hits: [], total: 0, summary: "" };

  let text = query.replace(/[,;!?]/g, " ");
  // Booking reference, e.g. BK-G8VAQW4N, or our own team reference GOOGLE-268.
  const bk = /\bBK-[A-Z0-9]{4,}\b/i.exec(text)?.[0]?.toUpperCase() ?? null;
  if (bk) { understood.push(`booking ${bk}`); text = text.replace(new RegExp(bk, "i"), " "); }
  const team = /\bGOOGLE-(\d+)/i.exec(text);
  const ids = new Set<number>();
  if (team) { ids.add(Number(team[1])); text = text.replace(team[0], " "); }
  for (const m of text.matchAll(/(?:#|\b)(\d{3,6})\b/g)) {
    const n = Number(m[1]);
    if (sessions.some((s) => s.thread_id === n)) { ids.add(n); text = text.replace(m[0], " "); }
  }
  if (ids.size) understood.push(`request ${[...ids].join(", ")}`);

  // Time: "today", "last hour", "last 3 hours", "24h". Relative to the newest request (the data can be a snapshot).
  const newest = sessions.reduce((a, s) => Math.max(a, s.received_at), 0);
  let since: number | null = null;
  const hrs = /\b(?:last|past)\s+(\d+)\s*(?:h|hours?)\b|\b(\d+)\s*h\b/i.exec(text);
  if (hrs) { const n = Number(hrs[1] ?? hrs[2]); since = newest - n * H; understood.push(`last ${n} h`); text = text.replace(hrs[0], " "); }
  else if (/\b(?:last|past)\s+hour\b/i.test(text)) { since = newest - H; understood.push("last hour"); text = text.replace(/\b(?:last|past)\s+hour\b/i, " "); }
  else if (/\btoday\b/i.test(text)) {
    const d = new Date(newest * 1000); d.setHours(0, 0, 0, 0); since = d.getTime() / 1000;
    understood.push("today"); text = text.replace(/\btoday\b/i, " ");
  }

  // Airports: any known IATA code. Two codes = a lane in that order; one = either end.
  const words = text.split(/\s+/).filter(Boolean);
  const codes = words.filter((w) => /^[A-Za-z]{3}$/.test(w) && AIRPORTS[w.toUpperCase()] && !STOP.has(w.toLowerCase()))
    .map((w) => w.toUpperCase());
  const [from, to] = codes;
  if (codes.length >= 2) understood.push(`${from} → ${to}`); else if (from) understood.push(`airport ${from}`);

  const statuses = new Set<string>();
  const langs = new Set<string>();
  const free: string[] = [];
  for (const w0 of words) {
    const w = w0.toLowerCase();
    if (codes.includes(w0.toUpperCase()) && /^[a-z]{3}$/i.test(w0)) continue;
    if (STATUS_WORDS[w]) { STATUS_WORDS[w].forEach((x) => statuses.add(x)); understood.push(w); continue; }
    if (LANGS[w]) { langs.add(LANGS[w]); understood.push(`in ${w0}`); continue; }
    if (STOP.has(w) || w.length < 2) continue;
    free.push(w);
  }
  // Free words: customer address first; if no customer matches, search the mail text.
  const custWords = free.filter((w) => sessions.some((s) => s.customer.toLowerCase().includes(w)));
  const mailWords = free.filter((w) => !custWords.includes(w));
  if (custWords.length) understood.push(`customer "${custWords.join(" ")}"`);
  const inMail = mailMatches(mailWords);
  if (mailWords.length) understood.push(`mail says "${mailWords.join(" ")}"`);

  const hits: Hit[] = [];
  for (const s of sessions) {
    const why: string[] = [];
    const ref = refs.get(s.thread_id) ?? null;
    const o = s.fields.origin ?? "", d = s.fields.destination ?? "";
    if (bk) { if (ref?.toUpperCase() !== bk) continue; why.push(bk); }
    if (ids.size) { if (!ids.has(s.thread_id)) continue; why.push(`#${s.thread_id}`); }
    if (codes.length >= 2) { if (o !== from || d !== to) continue; why.push(`${from} → ${to}`); }
    else if (from) { if (o !== from && d !== from) continue; why.push(from); }
    if (statuses.size) { if (!statuses.has(s.status)) continue; why.push(s.status.replaceAll("_", " ")); }
    if (langs.size) { if (!langs.has((s.fields.language ?? "").toLowerCase())) continue; why.push((s.fields.language ?? "").toUpperCase()); }
    if (since != null) { if (s.received_at < since) continue; }
    if (custWords.length) { if (!custWords.every((w) => s.customer.toLowerCase().includes(w))) continue; why.push(s.customer.split("@")[0]); }
    if (inMail) { if (!inMail.has(s.thread_id)) continue; why.push(`"${mailWords.join(" ")}" in mail`); }
    hits.push({ s, why, booking: ref });
  }
  hits.sort((a, b) => b.s.received_at - a.s.received_at);

  const won = hits.filter((h) => h.s.status === "confirmed" || h.s.status === "booked").length;
  const lost = hits.filter((h) => h.s.status === "lost").length;
  const value = hits.reduce((a, h) => a + (h.s.status === "confirmed" || h.s.status === "booked" ? Number(h.s.chosen?.total_eur ?? 0) : 0), 0);
  const summary = hits.length === 0 ? "Nothing matches."
    : `${hits.length} ${hits.length === 1 ? "request" : "requests"} · ${won} won · ${lost} lost` +
      (value ? ` · ${Math.round(value).toLocaleString("en-GB")} EUR booked` : "");
  return { query, understood, hits: hits.slice(0, limit), total: hits.length, summary };
}

export { rowToSession };
