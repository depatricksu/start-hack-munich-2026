// Server-only. Shipments after the customer said yes, and the messages a forwarder still writes by hand.
// The drafting is a port of Patrick's demo/after_yes.py (branch patrick/after-the-yes-demo): same message set,
// same wording, same honesty markers. Every value is marked: "record" = from our data, "open" = still missing.
// Nothing here sends mail. A message is "sent" only when our event log proves it went out.
import fs from "node:fs";
import path from "node:path";
import { getDb } from "./db";
import { parse } from "./data";
import { simMarks } from "./dashboard";
import { getCarrierFlags, getInvoices, type Invoice } from "./invoices";

// ---------- shapes (the page imports these as types) ----------

export type SegKind = "text" | "record" | "open";
export type Seg = { t: string; k: SegKind };
export type Line = Seg[];
export type Recipient = { name: string; address: string | null; offer: string | null };
export type Message = {
  id: string; role: string; title: string; when: string; why: string;
  to: Line; address: string | null; recipients?: Recipient[];
  subject: Line; body: Line[];
  state: "sent" | "draft"; sent_at: number | null;
};
export type Step = { key: string; label: string; done: boolean; at: number | null; sim?: boolean; problem?: boolean };
export type Watch = { carrier: string; level: string; reasons: string[] };
export type ShipInvoice = { number: string; amount: number; currency: string; status: string; overdue_days: number; sent: boolean; issued_at: number; paid_at: number | null };
export type ShipmentRow = {
  thread: number; ref: string; booking_ref: string | null; customer: string; company: string;
  origin: string | null; destination: string | null; airline: string | null; trucker: string | null;
  status: string; at: number; price: string | null; transit_days: number | null;
  steps: Step[]; drafts: number; sent: number; flag: "red" | "amber" | null;
};
export type Fact = { k: string; v: string; open: boolean };
export type ShipmentDetail = ShipmentRow & {
  watch: Watch[]; invoice: ShipInvoice | null; facts: Fact[]; messages: Message[]; note: string | null;
};
export type ShipmentsData = {
  available: boolean;
  totals: { active: number; waiting: number; informed: number; drafts: number; invoiced: number; paid: number; cancelled: number };
  rows: ShipmentRow[];
};

// ---------- small helpers (Patrick's F / O / T) ----------

const F = (v: unknown): Seg => ({ t: String(v ?? ""), k: "record" });
const O = (v: string): Seg => ({ t: v, k: "open" });
const T = (v: unknown): Seg => ({ t: String(v ?? ""), k: "text" });
const L = (...parts: (Seg | string | null | false | undefined)[]): Line =>
  parts.filter((p): p is Seg | string => !!p || p === "").map((p) => (typeof p === "string" ? T(p) : p)).filter((s) => s.t !== "");

const OUR_NAME = "Lena"; // the signature our quote mails use
const money = (v: unknown) => {
  const n = Number(v);
  return Number.isFinite(n) && v !== null && v !== "" ? n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : String(v ?? "");
};
const num = (n: number) => String(Number(n.toFixed(3)));
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dmy = (d: Date) => `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
const dm = (d: Date) => `${String(d.getUTCDate()).padStart(2, "0")} ${MON[d.getUTCMonth()]}`;

let carrierCache: Map<string, string> | null = null;
function carrierEmails(): Map<string, string> {
  if (carrierCache) return carrierCache;
  const out = new Map<string, string>();
  try {
    const file = path.join(process.cwd(), "..", "kit", "start-kit", "carrier-list.csv");
    const lines = fs.readFileSync(file, "utf8").split(/\r?\n/).slice(1);
    for (const line of lines) {
      const p = line.trim().split(",");
      if (p.length >= 3 && p[0] && p[2]) out.set(p[0], p[2]);
    }
  } catch { /* no list: addresses stay open */ }
  carrierCache = out;
  return out;
}

type Fields = Record<string, unknown> & { customer_lines?: string[]; pieces?: { count?: number }[] };

function readyDate(body: string): Date | null {
  const m = /\b(20\d\d)-(\d\d)-(\d\d)\b/.exec(body || "");
  if (!m) return null;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return Number.isNaN(d.getTime()) || d.getUTCDate() !== Number(m[3]) ? null : d;
}

const NOT_NAMES = ["best", "kind", "cheers", "regards", "thanks", "many", "mit", "viele", "beste"];
function firstName(f: Fields): string | null {
  if (typeof f.customer_first_name === "string" && f.customer_first_name) return f.customer_first_name;
  for (const line of f.customer_lines ?? []) {
    const w = String(line).replaceAll(",", " ").split(/\s+/).filter(Boolean);
    if (w.length >= 2 && /^[A-ZÄÖÜ]/.test(w[0]) && !NOT_NAMES.includes(w[0].toLowerCase())) return w[0];
  }
  return null;
}

export function companyOf(f: Fields, customer: string): string {
  for (const line of f.customer_lines ?? []) if (/\b(GmbH|AG|KG|Ltd|SE|S\.p\.A|SAS|SL|Inc)\b/.test(String(line))) return String(line).trim();
  return customer.split("@")[0].replaceAll("-", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function contactOf(f: Fields): string {
  const n = firstName(f);
  for (const line of f.customer_lines ?? []) if (n && String(line).startsWith(n)) return String(line).trim();
  return n || "the shipper";
}

const GENERIC = new Set(["shipment", "goods", "cargo", "the shipment", "the goods", "freight", "it", "they"]);
const GOODS_PATTERNS = [
  /\bpieces of ([a-z][a-z \-]{2,40}?)(?:[,.:;]| with| ready| for| to| from)/g,
  /\bfor ([a-z][a-z \-]{2,40}?)\?/g,
  /\bimporting (?:some )?([a-z][a-z \-]{2,40}?) from/g,
  /\bcargo is ([a-z][a-z \-]{2,40}?)(?:[,.]| packed)/g,
  /\b[Tt]he ([a-z][a-z \-]{2,40}?) (?:will be|are|is) ready/g,
  /\bshipment of ([a-z][a-z \-]{2,40}?)(?:[,.]| to| from| with)/g,
  /\b[Cc]ommodity: ([a-z][a-z \-]{2,40}?)(?:[,.\n]| packed)/g, // added: the request form most customers use
];
// The goods as the customer wrote them; "general cargo" when the mail never says.
function goodsOf(body: string): string {
  for (const pat of GOODS_PATTERNS) {
    for (const m of (body || "").matchAll(pat)) {
      const g = m[1].trim().replace(/^(our|some|the|these) /, "");
      if (!GENERIC.has(g.toLowerCase()) && !/piece|option|import|export|shipment/.test(g)) return g;
    }
  }
  return "general cargo";
}

// The customer's city: from the read fields, else the word after the pickup postcode in their mail.
function cityOf(f: Fields, postcode: string | null, body: string): string {
  if (typeof f.customer_city === "string" && f.customer_city) return f.customer_city;
  if (!postcode || !/^\w+$/.test(postcode)) return "";
  return new RegExp(`\\b${postcode}\\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\\-]+)`).exec(body || "")?.[1] ?? "";
}

// ---------- data access ----------

type Row = Record<string, unknown>;
type Ev = { id: number; ts: number; kind: string; data: Record<string, unknown> };

function hasTable(name: string): boolean {
  const db = getDb();
  return !!db && !!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(name);
}

function q<T = Row>(sql: string, ...args: unknown[]): T[] {
  const db = getDb();
  if (!db) return [];
  try { return db.prepare(sql).all(...args) as T[]; } catch { return []; }
}

type Ctx = {
  b: Row; fields: Fields; chosen: Record<string, unknown>; events: Ev[];
  invoice: Invoice | null; flags: Map<string, { level: string; reasons: string[] }>; now: number;
};

function loadBookings(): Row[] {
  return q("SELECT * FROM bookings ORDER BY COALESCE(confirmed_at, booked_at, created_at) DESC");
}

function eventsByThread(): Map<number, Ev[]> {
  const out = new Map<number, Ev[]>();
  const kinds = "'bid_picked','customer_informed','booking_confirmed','booking_cancelled','invoice_issued','invoice_paid','mail_out','tracking_answered'";
  for (const r of q<Row>(`SELECT id, ts, thread_id, kind, data FROM events WHERE kind IN (${kinds})
      AND thread_id IN (SELECT thread_id FROM bookings) ORDER BY id`)) {
    const t = Number(r.thread_id);
    const list = out.get(t) ?? [];
    list.push({ id: Number(r.id), ts: Number(r.ts), kind: String(r.kind), data: parse(r.data, {}) });
    out.set(t, list);
  }
  return out;
}

function sessionsOf(): Map<number, { fields: Fields; chosen: Record<string, unknown> }> {
  const out = new Map<number, { fields: Fields; chosen: Record<string, unknown> }>();
  for (const r of q<Row>("SELECT thread_id, fields, chosen FROM sessions WHERE thread_id IN (SELECT thread_id FROM bookings)"))
    out.set(Number(r.thread_id), { fields: parse(r.fields, {}), chosen: parse(r.chosen, {}) });
  return out;
}

function flagMap() {
  return new Map(getCarrierFlags().filter((f) => f.level === "red" || f.level === "amber").map((f) => [f.carrier, { level: f.level, reasons: f.reasons }]));
}

// ---------- lifecycle ----------

function truckerOf(c: Ctx): string | null {
  if (typeof c.chosen.trucker === "string" && c.chosen.trucker) return c.chosen.trucker;
  const p = [...c.events].reverse().find((e) => e.kind === "bid_picked" && e.data.role === "trucker" && e.data.carrier);
  return p ? String(p.data.carrier) : null;
}

function steps(c: Ctx, yesAt: number | null): Step[] {
  const b = c.b;
  const status = String(b.status ?? "");
  const cancelled = status === "cancelled";
  const bookedAt = b.booked_at == null ? null : Number(b.booked_at);
  const confAt = b.confirmed_at == null ? null : Number(b.confirmed_at);
  const informed = c.events.filter((e) => e.kind === "customer_informed");
  // Informed of the latest state: "confirmed" once the airline confirmed, else "booked".
  const want = status === "confirmed" ? "confirmed" : "booked";
  const inf = [...informed].reverse().find((e) => String(e.data.message ?? "") === want) ?? null;
  const inv = c.invoice;
  const out: Step[] = [
    { key: "yes", label: "Customer said yes", done: true, at: yesAt ?? (b.created_at == null ? null : Number(b.created_at)) },
    { key: "booked", label: "Booked with airline", done: !!bookedAt || ["booked", "confirmed"].includes(status), at: bookedAt },
    { key: "confirmed", label: "Airline confirmed", done: status === "confirmed" || (!!confAt && !cancelled), at: confAt },
    { key: "informed", label: "Customer informed", done: !!inf, at: inf?.ts ?? null },
    { key: "invoice", label: "Invoice issued", done: !!inv && inv.status !== "cancelled", at: inv?.issued_at ?? null },
    { key: "paid", label: "Paid", done: inv?.status === "paid", at: inv?.paid_at ?? null,
      problem: !!inv && inv.status !== "paid" && (inv.overdue_days > 0 || inv.status === "overdue_human") },
  ];
  // Flight steps: SIMULATED with the dashboard's rule (booking time + transit days). Only once the airline confirmed.
  const t0 = Number(b.confirmed_at ?? b.booked_at ?? b.created_at ?? 0);
  const marks = simMarks(t0, b.transit_days == null ? null : Number(b.transit_days));
  const fly = status === "confirmed";
  out.push(
    { key: "departed", label: "Departed", done: fly && c.now >= marks[2], at: fly ? marks[2] : null, sim: true },
    { key: "arrived", label: "Arrived", done: fly && c.now >= marks[3], at: fly ? marks[3] : null, sim: true },
    { key: "delivered", label: "Delivered", done: fly && c.now >= marks[4], at: fly ? marks[4] : null, sim: true },
  );
  return out;
}

// ---------- the messages (port of after_yes.py build()) ----------

type Bid = { carrier: string; kind: string; total: string | null; currency: string | null; email: string | null; raw: string | null };

function drafts(c: Ctx, first: Row | null, bids: Bid[]): { messages: Message[]; facts: Fact[] } {
  const b = c.b, f = c.fields, chosen = c.chosen;
  const firstBody = String(first?.body ?? "");
  const ready = readyDate(firstBody);
  const name = firstName(f) ?? "there";
  const company = companyOf(f, String(b.customer ?? ""));
  const goods = goodsOf(firstBody);
  const pieces = (f.pieces ?? []).reduce((a, p) => a + (Number(p?.count) || 0), 0) || null;
  const kg = Number(b.weight_kg ?? f.weight_kg_total ?? f.weight_kg ?? 0) || 0;
  const cbm = Number(b.volume_cbm ?? f.volume_cbm_total ?? f.volume_cbm ?? 0) || null;
  const postcode = typeof f.pickup_postcode === "string" ? f.pickup_postcode : f.pickup_postcode != null ? String(f.pickup_postcode) : null;
  const city = cityOf(f, postcode, firstBody);
  const dg = f.dg || f.dangerous_goods;
  const dgText = dg ? "dangerous goods, DG papers attached" : "not dangerous";
  const trucker = truckerOf(c);
  const transit = b.transit_days ?? chosen.transit_days ?? null;
  const readyS = ready ? dmy(ready) : null;
  const arrive = ready && transit ? new Date(ready.getTime() + Number(transit) * 86400_000) : null;
  const ref = String(b.team_reference ?? `#${b.thread_id}`);
  const bk = b.booking_reference ? String(b.booking_reference) : null;
  const origin = String(b.origin ?? "?"), dest = String(b.destination ?? "?"), airline = String(b.airline ?? "the airline");
  const lane = `${origin} → ${dest}`;
  const tbid = bids.find((x) => x.kind === "trucker" && x.carrier === trucker) ?? null;
  const offerRef = /\b(TRK-\d+)\b/.exec(tbid?.raw ?? "")?.[1] ?? null;
  const losers = bids.filter((x) => x.carrier !== trucker && x.carrier !== b.airline && (x.kind === "trucker" || x.kind === "airline"));
  const contact = contactOf(f);
  const who = F(name);
  const goodsLine = (): Seg[] => [F(goods), T(", "), pieces ? F(`${pieces} pcs`) : O("pieces open"), T(", "), F(`${num(kg)} kg`), T(", "),
    cbm ? F(`${num(cbm)} m³`) : O("volume open")];
  const readyOr = (open: string) => (readyS ? F(readyS) : O(open));
  const BK = bk ? F(bk) : O("booking ref open");
  const emails = carrierEmails();
  const msgs: Message[] = [];
  const base = { state: "draft" as const, sent_at: null };

  if (trucker) {
    const truckers = bids.filter((x) => x.kind === "trucker").length;
    msgs.push({ ...base, id: "truck", role: "Trucker", when: "Right after the booking", title: "Pickup order to the chosen trucker",
      why: `${trucker}, picked from ${truckers} trucker offer${truckers === 1 ? "" : "s"}. Today the trucker only got our price request.`,
      to: L(F(trucker)), address: tbid?.email || emails.get(trucker) || null,
      subject: L("Pickup order ", ref, " · ", postcode || city ? F(postcode || city) : O("pickup open"), " → ", F(origin), " · ", readyOr("date open")),
      body: [
        L("Hello, thank you for your offer ", offerRef && F(offerRef), offerRef && " ", "of ",
          F(`${money(chosen.trucker_total)} ${String(chosen.trucker_currency || "EUR")}`), ". We confirm:"),
        [],
        L("Collect   ", F(company), ", ", postcode && F(postcode), postcode && city && " ", city && F(city)),
        L("Contact   ", F(contact)),
        L("From      ", readyOr("ready date open")),
        L("Goods     ", ...goodsLine(), ", ", F(dgText)),
        L("Deliver   ", F(origin), " airport, ", F(airline), " cargo terminal"),
        L("Booking   ", BK),
        [],
        L("Please reply with the driver's arrival window. Ref ", ref, "."),
      ] });
  }

  msgs.push({ ...base, id: "airline", role: "Airline", when: "Right after the booking", title: "Shipment details for the booking",
    why: `${airline}. The portal booking only carries lane, weight and volume.`,
    to: L(F(airline)), address: emails.get(String(b.airline ?? "")) ?? null,
    subject: L(BK, " · shipment details · ", ref),
    body: [
      L("Shipper     ", F(company), city && ", ", city && F(city)),
      L("Consignee   ", O("follows with the commercial invoice")),
      L("Routing     ", F(origin), " → ", F(dest)),
      L("Pieces      ", pieces ? F(pieces) : O("open"), " · gross ", F(`${num(kg)} kg`), " · ", cbm ? F(`${num(cbm)} m³`) : O("volume open")),
      L("Goods       ", F(goods), ", ", F(dgText)),
      trucker
        ? L("Delivery    by truck (", F(trucker), ") to your ", F(origin), " terminal on ", readyOr("date open"))
        : L("Delivery    by the shipper to your ", F(origin), " terminal"),
      [],
      L("Please issue the air waybill to our reference ", ref, "."),
    ] });

  if (losers.length) {
    const names = [...new Set(losers.map((x) => x.carrier))].sort();
    msgs.push({ ...base, id: "losers", role: "Carriers not chosen", when: "Right after the booking",
      title: `Thank the ${losers.length} bidder${losers.length === 1 ? "" : "s"} we did not pick`,
      why: "Usually nobody answers them. Carriers stop prioritising a forwarder who never closes the loop. No price is shared.",
      to: L(F(names.join(", "))), address: null,
      recipients: losers.map((x) => ({ name: x.carrier, address: x.email || emails.get(x.carrier) || null,
        offer: x.total ? `${money(x.total)} ${x.currency ?? ""}`.trim() : null })),
      subject: L("Your offer for ", F(lane), ", our ref ", ref),
      body: [L("Hello,"), [], L("thank you for your quick offer. This time the customer went"), L("with another option, so we will not need it."),
        L("We will ask you again for the next one on this lane."), [], L(`Best regards, ${OUR_NAME}`)] });
  }

  msgs.push({ ...base, id: "customer", role: "Customer", when: "Right after the booking", title: "What happens next, and which papers we need",
    why: "Today the forwarder chases the Shipper's Letter of Instruction, invoice and packing list by phone and mail.",
    to: L(F(contact)), address: String(b.customer ?? "") || null,
    subject: L("Re: ", String(first?.subject ?? b.subject ?? "")),
    body: [
      L("Hi ", who, ","), [],
      trucker
        ? L("all set: ", F(trucker), " collects the ", F(goods), " on ", readyS ? F(readyS) : O("the ready date"))
        : L("all set: please deliver the ", F(goods), " to ", F(airline), " at ", F(origin)),
      L("and they fly with ", F(airline), ", about ", transit != null ? F(transit) : O("?"), " days to ", F(dest), "."),
      [], L("Could you reply with these, so customs and the airline have them?"),
      L("  1. Commercial invoice (value and HS codes)"), L("  2. Packing list"), L("  3. Shipper's Letter of Instruction"),
      L("  4. Consignee name and address at ", F(dest)),
      [], L("I will write again when the goods are on their way."), L(`Best regards, ${OUR_NAME}`),
    ] });

  msgs.push({ ...base, id: "prealert", role: "Destination partner", when: "When the papers arrive", title: "Pre-alert to the partner at destination",
    why: `Our partner forwarder at ${dest}, who clears import and delivers. Today sent by hand after departure, often without the HS code.`,
    to: L("partner forwarder, ", F(dest)), address: null,
    subject: L("Pre-alert ", F(lane), " · ", F(b.airline_code || airline), " · ", BK),
    body: [
      L("Departs ", readyOr("date open"), ", arrives about ", arrive ? F(dm(arrive)) : O("open"), "."),
      L("Shipper    ", F(company)),
      L("Consignee  ", O("from the invoice")),
      L("Goods      ", ...goodsLine(), ", ", F(dgText)),
      L("HS code    ", O("from the invoice")),
      L("Docs       invoice and packing list attached"),
    ] });

  if (trucker) {
    msgs.push({ ...base, id: "remind", role: "Trucker, then customer", when: "Day before pickup", title: "Day-before check with the trucker",
      why: "The trucker confirms the window; the customer gets it the same minute. Today: phone calls both ways.",
      to: L(F(trucker), " → ", F(contact)), address: tbid?.email || emails.get(trucker) || null,
      subject: L("Reminder: pickup ", readyOr("date open"), ", ref ", ref),
      body: [
        L("→ To: ", F(trucker)),
        L("  Reminder: pickup ", readyOr("date open"), ", ", postcode && F(postcode), postcode && city && " ", city && F(city), ", ref ", ref, "."),
        L("  What time will the driver be there?"), [],
        L("← ", trucker, ": ", O("driver window, e.g. 9 to 11")), [],
        L("→ To: ", F(contact)),
        L("  Hi ", who, ", the driver from ", F(trucker), " comes between ", O("window"), "."),
        L("  Please have the ", pieces ? F(`${pieces} pieces`) : "goods", " ready."),
      ] });
  }

  msgs.push({ ...base, id: "status", role: "Customer", when: "Pickup to arrival", title: "Status mails before the customer has to ask",
    why: `${name}, at each step: at the airport, departed, arrived. A delay of a day or more waits for a person first.`,
    to: L(F(contact)), address: String(b.customer ?? "") || null,
    subject: L("Re: ", String(first?.subject ?? b.subject ?? "")),
    body: [
      L(readyS ? F(readyS) : O("pickup day"), "  Your ", F(goods), " are at ", F(origin), " airport with ", F(airline), " (booking ", BK, ")."),
      L("            Next update when the flight leaves."),
      L("departure   The flight to ", F(dest), " has left. Arrival about ", arrive ? F(dm(arrive)) : O("open"), "."),
      L("delay ≥ 24h ", O("draft only: a person approves the new arrival date")),
      L("arrival     Landed at ", F(dest), ". Our partner handles import and delivery."),
    ] });

  const flight = chosen.flight_total ?? chosen.total ?? b.price;
  const facts: Fact[] = [
    { k: "Shipper", v: `${company} · ${contact}`, open: false },
    { k: "Pickup", v: trucker ? (`${postcode ?? ""} ${city}`.trim() || "open") : "shipper delivers", open: !!trucker && !postcode && !city },
    { k: "Ready", v: readyS ?? "open", open: !readyS },
    { k: "Pieces", v: pieces ? String(pieces) : "open", open: !pieces },
    { k: "Weight", v: cbm ? `${num(kg)} kg · ${num(cbm)} m³` : `${num(kg)} kg`, open: !kg },
    { k: "Goods", v: `${goods} · ${dgText}`, open: goods === "general cargo" },
    { k: "Transit", v: transit != null ? `${transit} days` : "open", open: transit == null },
    { k: "Cost", v: trucker ? `${money(flight)} flight + ${money(chosen.trucker_total)} truck` : `${money(flight)} flight`, open: false },
  ];
  return { messages: msgs, facts };
}

// Messages our log proves went out: the booked / confirmed mails to the customer (mail_out right before customer_informed).
function sentToCustomer(c: Ctx): Message[] {
  const out: Message[] = [];
  const evs = c.events;
  for (let i = 0; i < evs.length; i++) {
    const e = evs[i];
    if (e.kind !== "customer_informed") continue;
    const kind = String(e.data.message ?? "");
    if (kind !== "booked" && kind !== "confirmed") continue;
    let mail: Ev | null = null;
    for (let j = i - 1; j >= 0; j--) if (evs[j].kind === "mail_out") { mail = evs[j]; break; }
    const body = String(mail?.data.body ?? "");
    out.push({
      id: `sent-${kind}`, role: "Customer", when: kind === "confirmed" ? "When the airline confirmed" : "Right after the booking",
      title: kind === "confirmed" ? "Booking confirmed, told the customer" : "Booked, told the customer",
      why: "Sent by Relay. This is the mail as it went out.",
      to: L(F(contactOf(c.fields))), address: String(mail?.data.to ?? c.b.customer ?? "") || null,
      subject: L(String(mail?.data.subject ?? "")),
      body: body ? body.split("\n").map((l) => L(l)) : [L("The mail text is not in the log.")],
      state: "sent", sent_at: (mail ?? e).ts,
    });
  }
  return out;
}

function invoiceMessage(c: Ctx): Message | null {
  const inv = c.invoice;
  if (!inv) return null;
  return {
    id: "invoice", role: "Customer", when: "When the airline confirmed", title: `Invoice ${inv.number}`,
    why: inv.sent ? "Sent to the customer." : "Written by Relay. Invoice mails to customers are switched off, so it is a draft.",
    to: L(F(inv.customer)), address: inv.customer || null, subject: L(inv.subject ? `${inv.subject}` : `Invoice ${inv.number}`),
    body: (inv.body || "No invoice text stored.").split("\n").map((l) => L(l)),
    state: inv.sent ? "sent" : "draft", sent_at: inv.sent ? inv.issued_at : null,
  };
}

// A draft to a carrier counts as sent only if a real mail_out to that address exists after the booking.
function proveSent(c: Ctx, msgs: Message[]) {
  const since = Number(c.b.booked_at ?? c.b.created_at ?? 0);
  const outs = c.events.filter((e) => e.kind === "mail_out" && e.ts >= since);
  for (const m of msgs) {
    if (m.state === "sent" || m.role === "Customer" || !m.address) continue;
    const hit = outs.find((e) => String(e.data.to ?? "").toLowerCase() === m.address!.toLowerCase());
    if (hit) { m.state = "sent"; m.sent_at = hit.ts; }
  }
}

// ---------- public ----------

function build(b: Row, ctxBase: Omit<Ctx, "b" | "fields" | "chosen" | "events" | "invoice">,
  sess: { fields: Fields; chosen: Record<string, unknown> } | undefined, events: Ev[], invoice: Invoice | null) {
  const c: Ctx = { ...ctxBase, b, fields: sess?.fields ?? {}, chosen: sess?.chosen ?? {}, events, invoice };
  const tid = Number(b.thread_id);
  const yesMail = b.last_customer_mail_id != null ? q<Row>("SELECT received_at FROM mails WHERE id=?", b.last_customer_mail_id)[0] : undefined;
  const status = String(b.status ?? "");
  const trucker = truckerOf(c);
  const watch: Watch[] = [b.airline ? String(b.airline) : "", trucker ?? ""].filter((x) => x && c.flags.has(x))
    .map((x) => ({ carrier: x, ...c.flags.get(x)! }));
  // Patrick drafts only for bookings the airline confirmed: before that the details may still change.
  let messages: Message[] = [];
  let facts: Fact[] = [];
  if (status !== "cancelled") {
    messages = [...sentToCustomer(c)];
    if (status === "confirmed" && sess) {
      const first = q<Row>("SELECT id, subject, body FROM mails WHERE thread_id=? ORDER BY id LIMIT 1", tid)[0] ?? null;
      const bids = q<Bid>("SELECT carrier, kind, total, currency, email, raw FROM bids WHERE thread_id=? AND status='ok'", tid);
      const d = drafts(c, first, bids);
      facts = d.facts;
      messages.push(...d.messages);
    }
    const inv = invoiceMessage(c);
    if (inv) messages.push(inv);
    proveSent(c, messages);
  }
  const row: ShipmentRow = {
    thread: tid, ref: String(b.team_reference ?? `#${tid}`), booking_ref: b.booking_reference ? String(b.booking_reference) : null,
    customer: String(b.customer ?? ""), company: companyOf(c.fields, String(b.customer ?? "")),
    origin: b.origin ? String(b.origin) : null, destination: b.destination ? String(b.destination) : null,
    airline: b.airline ? String(b.airline) : null, trucker, status,
    at: Number(b.confirmed_at ?? b.booked_at ?? b.created_at ?? 0),
    price: Number(b.price) > 0 ? `${money(b.price)} ${b.currency || "EUR"}` : null,
    transit_days: b.transit_days == null ? null : Number(b.transit_days),
    steps: steps(c, yesMail ? Number(yesMail.received_at) : null),
    drafts: messages.filter((m) => m.state === "draft").length, sent: messages.filter((m) => m.state === "sent").length,
    flag: watch.some((w) => w.level === "red") ? "red" : watch.length ? "amber" : null,
  };
  return { row, watch, messages, facts };
}

function prepare() {
  const now = Date.now() / 1000;
  const invoices = new Map(getInvoices(now).rows.map((r) => [r.thread_id, r]));
  return { now, flags: flagMap(), invoices, sessions: sessionsOf(), events: eventsByThread() };
}

const EMPTY: ShipmentsData = { available: false, totals: { active: 0, waiting: 0, informed: 0, drafts: 0, invoiced: 0, paid: 0, cancelled: 0 }, rows: [] };

export function getShipments(): ShipmentsData {
  if (!hasTable("bookings")) return EMPTY;
  const p = prepare();
  const rows = loadBookings().map((b) => {
    const t = Number(b.thread_id);
    return build(b, { now: p.now, flags: p.flags }, p.sessions.get(t), p.events.get(t) ?? [], p.invoices.get(t) ?? null).row;
  });
  const live = rows.filter((r) => r.status !== "cancelled");
  const inv = live.map((r) => r.steps.find((s) => s.key === "invoice")?.done);
  return {
    available: true,
    totals: {
      active: live.length,
      waiting: live.filter((r) => r.status === "booked").length,
      informed: live.filter((r) => r.steps.find((s) => s.key === "informed")?.done).length,
      drafts: rows.reduce((a, r) => a + r.drafts, 0),
      invoiced: inv.filter(Boolean).length,
      paid: live.filter((r) => r.steps.find((s) => s.key === "paid")?.done).length,
      cancelled: rows.length - live.length,
    },
    rows,
  };
}

export function getShipment(threadId: number): ShipmentDetail | null {
  if (!hasTable("bookings")) return null;
  const b = q<Row>("SELECT * FROM bookings WHERE thread_id=?", threadId)[0];
  if (!b) return null;
  const p = prepare();
  const { row, watch, messages, facts } = build(b, { now: p.now, flags: p.flags }, p.sessions.get(threadId),
    p.events.get(threadId) ?? [], p.invoices.get(threadId) ?? null);
  const i = p.invoices.get(threadId) ?? null;
  const status = row.status;
  return {
    ...row, watch, messages, facts,
    invoice: i ? { number: i.number, amount: i.amount, currency: i.currency, status: i.status, overdue_days: i.overdue_days, sent: i.sent, issued_at: i.issued_at, paid_at: i.paid_at } : null,
    note: status === "cancelled" ? "This booking was cancelled. Nothing more goes out."
      : status !== "confirmed" ? "The messages to trucker, airline and partner are drafted once the airline confirms."
      : !p.sessions.has(threadId) ? "The request record is missing, so only the sent mails are shown." : null,
  };
}
