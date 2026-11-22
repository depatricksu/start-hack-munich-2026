// Pure rules for carrier mails: no DB, no imports, so they can be tested with plain node (carrier-rules.test.mjs).
// First hit wins in RULES, so the most serious news is checked first. EN + DE keywords.

export type UpdateType =
  | "confirmed" | "booked" | "delayed" | "cancelled" | "rebooked" | "departed" | "arrived" | "delivered" | "price" | "info"
  | "customer_cancel" | "we_cancelled";
export type Tone = "green" | "blue" | "amber" | "red" | "grey";

export const TYPE: Record<UpdateType, { label: string; tone: Tone }> = {
  confirmed: { label: "Confirmed", tone: "green" },
  booked: { label: "Booking accepted", tone: "blue" },
  delayed: { label: "Delayed", tone: "red" },
  cancelled: { label: "Cancelled / refused", tone: "red" },
  rebooked: { label: "Rebooked", tone: "amber" },
  departed: { label: "Departed", tone: "blue" },
  arrived: { label: "Arrived", tone: "blue" },
  delivered: { label: "Delivered", tone: "green" },
  price: { label: "Price change", tone: "amber" },
  info: { label: "Info", tone: "blue" },
  customer_cancel: { label: "Customer asked to cancel", tone: "red" },
  we_cancelled: { label: "We cancelled with the airline", tone: "grey" },
};

// First hit wins, so the most serious news is checked first. EN + DE, lower-case text.
export const RULES: [UpdateType, RegExp][] = [
  ["cancelled", /\bcancel|\bstorn|\brefus|unable to accept|cannot accept|can't accept|offload|abgelehnt|nicht annehmen/],
  ["delayed", /\bdelay|verspät|verspaet|verzöger|verzoeger|postpone|new eta|revised eta|neue ankunft|reschedul|verschoben/],
  ["rebooked", /\brebook|re-book|new flight|umgebucht|umbuchung|anderen flug/],
  ["price", /surcharge|price change|rate increase|new price|rate update|tariff|preisänderung|preisaenderung|zuschlag/],
  ["delivered", /\bdelivered\b|proof of delivery|\bpod\b|zugestellt|ausgeliefert/],
  ["arrived", /\barrived\b|\blanded\b|angekommen|gelandet/],
  ["departed", /\bdeparted\b|has left|took off|abgeflogen|on its way|unterwegs/],
  ["confirmed", /\bconfirmed\b|bestätigt|bestaetigt/],
  ["booked", /thank you for your booking|status:\s*booked\b|\bgebucht\b|booking received|buchung erhalten/],
];

// Our own words, quoted below a reply, must not change the type.
export function ownText(body: string): string {
  const out: string[] = [];
  for (const line of (body || "").split(/\r?\n/)) {
    if (/^\s*>/.test(line)) continue;
    if (/^\s*(on .+wrote:|am .+schrieb.*:|-----\s*original message)/i.test(line)) break;
    out.push(line);
  }
  return out.join("\n");
}

export function classify(subject: string, body: string): UpdateType {
  const t = `${subject}\n${ownText(body)}`.toLowerCase();
  for (const [type, re] of RULES) if (re.test(t)) return type;
  return "info";
}

const MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const MON_DE: Record<string, number> = { jan: 0, januar: 0, feb: 1, februar: 1, mär: 2, maerz: 2, märz: 2, mrz: 2, apr: 3, mai: 4, jun: 5, juni: 5, jul: 6, juli: 6, aug: 7, sep: 8, sept: 8, okt: 9, oct: 9, nov: 10, dez: 11, dec: 11 };
const fmtDate = (y: number, m: number, d: number) => `${String(d).padStart(2, "0")} ${MON[m][0].toUpperCase()}${MON[m].slice(1)} ${y}`;

// New dates in the mail: ISO, 27.11.2026, "27 Nov (2026)". Validity dates of offers are not news, so "valid until ..." is skipped.
export function datesIn(text: string, year = new Date().getUTCFullYear()): string[] {
  const t = ownText(text).replace(/valid (?:until|till|to)[^.\n]*/gi, "").replace(/gültig bis[^.\n]*/gi, "");
  const out = new Set<string>();
  const ok = (y: number, m: number, d: number) => m >= 0 && m < 12 && d >= 1 && d <= 31 && y > 2000 && y < 2100;
  for (const m of t.matchAll(/\b(20\d\d)-(\d\d)-(\d\d)\b/g)) { const y = +m[1], mo = +m[2] - 1, d = +m[3]; if (ok(y, mo, d)) out.add(fmtDate(y, mo, d)); }
  for (const m of t.matchAll(/\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b/g)) { const y = +m[3], mo = +m[2] - 1, d = +m[1]; if (ok(y, mo, d)) out.add(fmtDate(y, mo, d)); }
  for (const m of t.matchAll(/\b(\d{1,2})\.?\s+([A-Za-zäÄ]{3,9})\.?(?:\s+(20\d\d))?\b/g)) {
    const mo = MON_DE[m[2].toLowerCase()] ?? MON_DE[m[2].toLowerCase().slice(0, 3)];
    if (mo === undefined) continue;
    const y = m[3] ? +m[3] : year, d = +m[1];
    if (ok(y, mo, d)) out.add(fmtDate(y, mo, d));
  }
  return [...out].slice(0, 3);
}

export function flightIn(text: string, airlineCode: string | null): string | null {
  const t = ownText(text);
  const ctx = /\b(?:flight|flug)(?:\s*(?:no\.?|number|nr\.?))?\s*:?\s*([A-Z0-9]{2}\s?\d{2,4})\b/i.exec(t);
  if (ctx) return ctx[1].toUpperCase().replace(/\s/, " ");
  if (airlineCode && /^[A-Z0-9]{2}$/.test(airlineCode)) {
    const m = new RegExp(`\\b${airlineCode}\\s?(\\d{3,4})\\b`).exec(t);
    if (m) return `${airlineCode} ${m[1]}`;
  }
  return null;
}

export const awbIn = (text: string) => /\b(\d{3}-\d{8})\b/.exec(ownText(text))?.[1] ?? null;

export function answerWords(s: number | null): string | null {
  if (s == null || !Number.isFinite(s)) return null;
  if (s < 60) return "under a minute";
  if (s < 3600) return `about ${Math.round(s / 60)} min`;
  if (s < 86400) return `about ${Math.round(s / 3600)} h`;
  return `about ${Math.round(s / 86400)} days`;
}

export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

// Opening sentence of a mail, without the greeting.
export function firstSentence(body: string): string {
  const lines = ownText(body).split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
    .filter((l) => !/^(hello|hi|dear|good (morning|day|afternoon)|guten|sehr geehrte|hallo|liebe)\b/i.test(l) || l.length > 40);
  const s = (lines.join(" ").replace(/^(hello|hi|dear [^,]+|hallo)[,!]?\s*/i, "").split(/(?<=[.!?])\s/)[0] || "").trim();
  return s.length > 150 ? `${s.slice(0, 147)}…` : s;
}

// The sentence that carries the news (e.g. the one that says "cancel"), else the opening sentence.
export function keySentence(body: string, re: RegExp): string {
  const s = ownText(body).replace(/\s+/g, " ").split(/(?<=[.!?])\s/).find((x) => re.test(x))?.trim();
  if (!s) return firstSentence(body);
  const t = s.replace(/^(hello|hi|dear|hallo|guten tag)( there| team| [A-Z][a-z]+)?[,!]?\s*/i, "");
  return t.length > 150 ? `${t.slice(0, 147)}…` : t;
}

