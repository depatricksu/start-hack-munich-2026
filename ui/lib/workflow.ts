// Server-only. The whole forwarder job for one shipment, start to end, read from the OFFLINE simulation DBs
// (research harness, one SQLite file per scenario). Phase 1 = the RFQ clerk (steps 1-5) from mails/events/sessions/
// bookings; phase 2 = carrierops (shipment_state, shipment_updates, outbox, ops_invoices, carrier_log).
// Every file is opened read-only. Nothing here writes, sends or calls an API.
import fs from "node:fs";
import path from "node:path";

export const SIM_DB_DIR = process.env.SIM_DB_DIR || "/Users/kaiqin/Projects/starthack/research/harness/db/ops";
export const HARNESS_CMD = "sh /Users/kaiqin/Projects/starthack/research/harness/run_ops.sh <clerk-worktree> ops";
export const HARNESS_CMD_ONE = 'SCENS="c1 c3" sh /Users/kaiqin/Projects/starthack/research/harness/run_ops.sh <clerk-worktree> ops';

// Names and one-liners from research/carrierops-report.md.
export const SCENARIOS: { id: string; name: string; desc: string }[] = [
  { id: "c1", name: "Normal shipment with a delay", desc: "Everyone informed, truck pickup, departed, delay, arrived, delivered, invoice, 'we have paid', marked paid." },
  { id: "c2", name: "German delay by our reference", desc: "German customer; German delay mail with only our reference; the same news again in the confirmation thread." },
  { id: "c3", name: "Airline cancels, rebook offer", desc: "Airline cancels the booking and offers another flight; customer says yes; airline confirms the new flight." },
  { id: "c4", name: "Offload and rebook", desc: "Offloaded, protected on the next flight; then that flight is cancelled and the shipment rebooked (still flies)." },
  { id: "c5", name: "Airline price above quote", desc: "Airline confirms 15% above the flight price we quoted; later a fuel surcharge mail." },
  { id: "c6", name: "Delay without reference", desc: "Delay mail with no reference, matched by airline + route. Other airline ignored. Two shipments on the route: not guessed." },
  { id: "c7", name: "Tracking question after delay", desc: "'Where is my shipment?' before any airline report, then after departure + delay: new ETA, AWB, flight, link." },
  { id: "c8", name: "Invoice overdue, reminder, paid", desc: "Invoice only after delivery; overdue, reminder; 'we have paid' stops reminders; marked paid." },
];

export type Tone = "green" | "blue" | "amber" | "red" | "grey";
export type Party = "customer" | "trucker" | "airline" | "partner" | "bidder" | "forwarder";
export type Draft = {
  id: number; party: Party; to: string; subject: string; body: string; why: string; at: number | null; status: string; shared: boolean;
};
export type Mail = { from: string; subject: string; body: string };
export type Fact = { k: string; v: string; tone?: Tone; plain?: boolean };
export type Item = {
  key: string; phase: "clerk" | "carrier"; at: number | null;
  side: "customer" | "us" | "carrier" | "clerk";
  title: string; chip: string; tone: Tone;
  text?: string; facts: Fact[]; mail?: Mail; out?: Mail & { note: string }; drafts: Draft[]; clerk?: string;
};
export type Check = { label: string; ok: boolean | null; detail: string };
export type LogRow = { carrier: string; kind: string; detail: string; at: number | null; tone: Tone };
export type Header = {
  thread: number; ref: string; route: string; company: string; customer: string; airline: string; trucker: string;
  booking: string; awb: string; flight: string; status: string; statusTone: Tone;
  etaPlanned: string; etaCurrent: string; late: boolean; invoice: string; invoiceTone: Tone; quote: string;
};
export type ScenarioTab = { id: string; name: string; desc: string; exists: boolean };
export type Workflow = {
  dir: string; dirExists: boolean; scenarios: ScenarioTab[]; id: string; scenario: ScenarioTab | null;
  problem: string | null; threads: { thread: number; label: string }[]; thread: number | null;
  header: Header | null; items: Item[]; parties: { party: Party; label: string; drafts: Draft[] }[];
  log: LogRow[]; checks: Check[];
};

// ---------- read-only connections, one per file, cached by mtime ----------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Db = any;
const conns = new Map<string, { db: Db; mtime: number }>();

function open(file: string): Db | null {
  if (!fs.existsSync(file)) return null;
  const mtime = fs.statSync(file).mtimeMs;
  const hit = conns.get(file);
  if (hit && hit.mtime === mtime) return hit.db;
  if (hit) { try { hit.db.close(); } catch { /* already closed */ } }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { DatabaseSync } = (process as any).getBuiltinModule("node:sqlite");
  const db = new DatabaseSync(file, { readOnly: true });
  conns.set(file, { db, mtime });
  return db;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;
const all = (db: Db, sql: string, ...p: unknown[]): Row[] => db.prepare(sql).all(...p) as Row[];
const tables = (db: Db) => new Set(all(db, "SELECT name FROM sqlite_master WHERE type='table'").map((r) => String(r.name)));
const json = (s: unknown): Row => { try { return s ? JSON.parse(String(s)) : {}; } catch { return {}; } };

// ---------- plain words ----------

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function eta(s: string | null | undefined): string {
  if (!s) return "";
  const m = /^(\d{4})-(\d\d)-(\d\d)(?:[ T](\d\d:\d\d))?/.exec(s);
  if (!m) return s;
  return `${m[3]} ${MON[Number(m[2]) - 1]} ${m[1]}${m[4] ? `, ${m[4]}` : ""}`;
}
const money = (v: unknown, c = "EUR") => {
  const n = Number(v);
  return v != null && v !== "" && Number.isFinite(n) ? `${n.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${c || "EUR"}` : "";
};
const short = (m: string) => (m || "").split("@")[0];

export const STATUS: Record<string, [string, Tone]> = {
  confirmed: ["Confirmed", "green"], picked_up: ["Picked up", "blue"], handed_over: ["At the airline", "blue"],
  departed: ["In the air", "blue"], delayed: ["Delayed", "red"], offloaded: ["Offloaded", "red"], rebooked: ["Rebooked", "red"],
  arrived: ["Arrived", "green"], delivered: ["Delivered", "green"], cancelled_by_airline: ["Cancelled by the airline", "red"],
  rebook_requested: ["Rebook asked, waiting for airline", "amber"], cancelled: ["Cancelled", "grey"],
};
const INVOICE: Record<string, [string, Tone]> = {
  issued: ["Invoice open", "blue"], overdue: ["Invoice overdue", "red"], overdue_human: ["Overdue, needs a person", "amber"],
  paid_reported: ["Customer says paid, check the bank", "amber"], paid: ["Paid", "green"],
};
const CARRIER_TYPE: Record<string, [string, Tone]> = {
  confirmed: ["Airline confirmed", "green"], booked: ["Airline booked", "green"], picked_up: ["Picked up by the truck", "blue"],
  handed_over: ["Truck handed the goods to the airline", "blue"], departed: ["Departed", "blue"], delayed: ["Delayed", "red"],
  offloaded: ["Taken off the flight", "red"], rebooked: ["Rebooked on another flight", "red"], arrived: ["Arrived", "green"],
  delivered: ["Delivered, proof of delivery", "green"], cancelled: ["Airline cancelled the booking", "red"],
  cancel_confirmed: ["Cancellation confirmed", "grey"], price: ["Price change", "amber"], info: ["Mail to read", "amber"],
  trucker_delayed: ["Truck delayed", "red"], trucker_cancelled: ["Truck cancelled", "red"],
};
const CUSTOMER_TYPE: Record<string, [string, Tone]> = {
  status_question: ["Customer asks where the shipment is", "blue"], rebook_yes: ["Customer says yes to the new flight", "blue"],
  rebook_no: ["Customer says no to the new flight", "amber"], paid: ["Customer says they paid", "amber"],
};
const MATCH: Record<string, string> = {
  bk: "booking ref", our_ref: "our ref", thread: "mail thread", awb: "AWB", flight: "flight number", lane: "airline + route",
  no_match: "no shipment fits (other airline)",
};
const matchWords = (m: string | null) => (!m ? "" : m.startsWith("ambiguous") ? "two shipments fit, not guessed" : MATCH[m] ?? m.replaceAll("_", " "));

export const PARTY: Record<Party, string> = {
  customer: "Customer", trucker: "Trucker", airline: "Airline", partner: "Destination partner",
  bidder: "Carriers not chosen", forwarder: "Forwarder desk (us)",
};
const KIND_WORDS: Record<string, string> = {
  handed_over: "goods at the airline", picked_up: "picked up", departed: "departed", delayed: "delay", offloaded: "offload",
  rebooked: "rebooked", arrived: "arrived", delivered: "delivered", cancelled: "cancellation and rebook offer",
  rebook_confirmed: "new flight confirmed", cancelled_by_customer: "customer cancelled",
};
function why(reason: string): string {
  const r = (reason || "").replace(/\s*\(partner address unknown, fill in\)/, "");
  if (r.startsWith("step 6: ")) return r.slice(8).replace(/^./, (c) => c.toUpperCase());
  const cu = /^carrier update: (\w+)/.exec(r);
  if (cu) return `News: ${KIND_WORDS[cu[1]] ?? cu[1].replaceAll("_", " ")}`;
  return r.replace(/^./, (c) => c.toUpperCase());
}
const LOG_KIND: Record<string, [string, Tone]> = {
  no_answer: ["No answer to price request", "grey"], late_answer: ["Late answer", "amber"], delay: ["Delay", "red"],
  cancelled: ["Cancelled", "red"], offload: ["Offload", "red"], rebook: ["Rebook", "red"], price_increase: ["Price above quote", "amber"],
  no_status_after_eta: ["No news after ETA", "amber"],
};
const CLERK_DID: Record<string, string> = {
  confirmation_duplicate: "read it as a repeat confirmation and did nothing", carrier_mail_unmatched: "could not tie it to a shipment",
  confirmation_unmatched: "could not tie the confirmation to a booking", booking_cancelled_by_airline: "marked the booking cancelled",
  invoice_cancelled: "cancelled its invoice", invoice_paid_reported: "marked its own invoice as 'customer says paid'",
  after_booking_status_answered: "answered with its own status text", follow_up_ignored: "ignored the mail",
  tracking_answered: "answered the tracking desk itself", carrier_bid: "read it as a price offer",
};

// ---------- the build ----------

const DELAYISH = new Set(["delayed", "offloaded", "rebooked"]);
const MILESTONE = new Set(["picked_up", "handed_over", "departed", "arrived", "delivered"]);

function dateForms(s: string): string[] {
  const m = /^(\d{4})-(\d\d)-(\d\d)/.exec(s);
  if (!m) return [s];
  return [`${Number(m[3])} ${MON[Number(m[2]) - 1]} ${m[1]}`, `${m[3]} ${MON[Number(m[2]) - 1]} ${m[1]}`, `${m[3]}.${m[2]}.${m[1]}`];
}

export function getWorkflow(id: string | null, threadParam: number | null): Workflow {
  const dirExists = fs.existsSync(SIM_DB_DIR);
  const scenarios: ScenarioTab[] = SCENARIOS.map((s) => ({ ...s, exists: dirExists && fs.existsSync(path.join(SIM_DB_DIR, `${s.id}.db`)) }));
  const sid = scenarios.some((s) => s.id === id) ? id! : "c1";
  const scenario = scenarios.find((s) => s.id === sid) ?? null;
  const base: Workflow = {
    dir: SIM_DB_DIR, dirExists, scenarios, id: sid, scenario, problem: null, threads: [], thread: null,
    header: null, items: [], parties: [], log: [], checks: [],
  };
  if (!dirExists) return { ...base, problem: `The simulation folder ${SIM_DB_DIR} does not exist.` };
  const file = path.join(SIM_DB_DIR, `${sid}.db`);
  if (!scenario?.exists) return { ...base, problem: `The file ${file} is missing.` };
  try {
    const db = open(file);
    if (!db) return { ...base, problem: `The file ${file} is missing.` };
    const t = tables(db);
    for (const need of ["mails", "events", "shipment_state", "shipment_updates", "outbox"]) {
      if (!t.has(need)) return { ...base, problem: `${file} has no "${need}" table. It was made before carrierops ran.` };
    }
    return build(db, t, base, threadParam);
  } catch (e) {
    return { ...base, problem: `Could not read ${file}: ${e instanceof Error ? e.message : String(e)}` };
  }
}

function build(db: Db, t: Set<string>, base: Workflow, threadParam: number | null): Workflow {
  const ships = all(db, "SELECT * FROM shipment_state ORDER BY thread_id");
  const threads = ships.map((s) => ({ thread: Number(s.thread_id), label: `${s.booking_ref ?? s.our_ref} · ${s.company || short(s.customer)}` }));
  const tid = threads.some((x) => x.thread === threadParam) ? threadParam! : threads[0]?.thread ?? null;
  if (tid == null) return { ...base, threads, problem: "No confirmed shipment in this run, so carrierops has nothing to show." };
  const s = ships.find((x) => Number(x.thread_id) === tid)!;
  const cur = s.currency || "EUR";

  const mails = new Map<number, Row>(all(db, "SELECT * FROM mails").map((m) => [Number(m.id), m]));
  const mailOf = (id: unknown): Mail | undefined => {
    const m = id != null ? mails.get(Number(id)) : undefined;
    return m ? { from: String(m.sender ?? ""), subject: String(m.subject ?? ""), body: String(m.body ?? "") } : undefined;
  };
  const session = t.has("sessions") ? all(db, "SELECT * FROM sessions WHERE thread_id=?", tid)[0] : undefined;
  const bids = t.has("bids") ? all(db, "SELECT * FROM bids WHERE thread_id=? ORDER BY id", tid) : [];

  // ---- outbox (this shipment + notes tied to no shipment) ----
  const outRows = all(db, "SELECT * FROM outbox WHERE thread_id=? OR thread_id IS NULL ORDER BY created_at, id", tid);
  const drafts: (Draft & { update_id: number | null })[] = outRows.map((o) => ({
    id: Number(o.id), party: o.party as Party, to: String(o.to_addr ?? ""), subject: String(o.subject ?? ""), body: String(o.body ?? ""),
    why: why(String(o.reason ?? "")), at: o.created_at ?? null, status: String(o.status ?? "draft"), shared: o.thread_id == null,
    update_id: o.update_id != null ? Number(o.update_id) : null,
  }));
  const reasonOf = new Map(outRows.map((o) => [Number(o.id), String(o.reason ?? "")]));
  const byUpdate = new Map<number, Draft[]>();
  const loose: (Draft & { update_id: number | null })[] = [];
  for (const d of drafts) {
    if (d.update_id != null) byUpdate.set(d.update_id, [...(byUpdate.get(d.update_id) ?? []), d]);
    else loose.push(d);
  }

  // ---- phase 1: the clerk, from events in id order; sim time = the mail's time, else the last one seen ----
  const items: Item[] = [];
  const evs = all(db, "SELECT * FROM events WHERE thread_id=? ORDER BY id", tid);
  let simT: number | null = null;
  let confirmedSeen = false;
  let lastOut: Row | null = null;
  const clerkLater = new Map<number, string[]>();
  let bidAsk: Item | null = null, bidIn: Item | null = null;
  for (const e of evs) {
    const d = json(e.data);
    const m = e.mail_id != null ? mails.get(Number(e.mail_id)) : undefined;
    if (m?.received_at) simT = Number(m.received_at);
    const kind = String(e.kind);
    if (confirmedSeen && !["customer_informed", "invoice_issued", "reply_variant", "mail_out_dry_run"].includes(kind)) {
      // after the booking: what the clerk did on its own with later mails (shown on the carrier side)
      if (e.mail_id != null && CLERK_DID[kind]) clerkLater.set(Number(e.mail_id), [...(clerkLater.get(Number(e.mail_id)) ?? []), CLERK_DID[kind]]);
      continue;
    }
    const it = (x: Partial<Item> & Pick<Item, "title" | "tone" | "side">): Item =>
      ({ key: `e${e.id}`, phase: "clerk", at: simT, chip: "", facts: [], drafts: [], ...x });
    if (kind === "mail_in" && d.route === "rfq") {
      items.push(it({ side: "customer", title: "Customer request", chip: "Request in", tone: "blue", mail: mailOf(e.mail_id) }));
    } else if (kind === "llm") {
      const f = { ...json(session?.fields), ...(d.fields ?? {}) };
      const fs2 = session ? json(session.fields) : {};
      const facts: Fact[] = [
        { k: "Route", v: `${fs2.origin ?? f.origin ?? "?"} → ${fs2.destination ?? f.destination ?? "?"}` },
        { k: "Weight", v: f.weight_kg != null ? `${f.weight_kg} kg` : "missing", tone: f.weight_kg != null ? undefined : "amber" },
        { k: "Volume", v: f.volume_cbm != null ? `${f.volume_cbm} cbm` : "missing", tone: f.volume_cbm != null ? undefined : "amber" },
      ];
      if (f.pickup_postcode) facts.push({ k: "Pickup", v: String(f.pickup_postcode) });
      if (f.dangerous_goods) facts.push({ k: "Dangerous goods", v: "yes", tone: "amber" });
      if (Array.isArray(f.missing) && f.missing.length) facts.push({ k: "Missing", v: f.missing.join(", "), tone: "amber" });
      items.push(it({ side: "us", title: "Read the request", chip: "Fields read", tone: "green", facts }));
    } else if (kind === "gate" && d.ok === false) {
      items.push(it({ side: "us", title: "Needs a person", chip: "Stopped", tone: "amber", text: String(d.note ?? "") }));
    } else if (kind === "options") {
      const opts: Row[] = Array.isArray(d.options) ? d.options : [];
      items.push(it({ side: "us", title: "Prices found", chip: `${opts.length} options`, tone: "green",
        facts: opts.map((o) => ({ k: String(o.airline ?? "?"), v: `${money(o.total, o.currency)} · ${o.transit_days ?? "?"} days` })) }));
    } else if (kind === "bid_requested") {
      if (!bidAsk) { bidAsk = it({ side: "us", title: "Asked carriers for prices", chip: "Price requests", tone: "blue" }); items.push(bidAsk); }
      bidAsk.facts.push({ k: String(d.carrier ?? "?"), v: d.role === "trucker" ? "trucker" : "airline" });
    } else if (kind === "bid_received") {
      if (!bidIn) { bidIn = it({ side: "carrier", title: "Price answers in", chip: "Offers", tone: "green" }); items.push(bidIn); }
      bidIn.facts.push({ k: String(d.carrier ?? "?"), v: d.status === "ok" ? money(d.total, d.currency) : String(d.status ?? "") });
    } else if (kind === "bid_wait_over" && bidIn) {
      for (const b of bids.filter((b) => !b.replied_at)) bidIn.facts.push({ k: String(b.carrier), v: "no answer", tone: "grey" });
    } else if (kind === "bid_picked") {
      items.push(it({ side: "us", title: `${d.role === "trucker" ? "Trucker" : "Carrier"} chosen`, chip: "Chosen", tone: "green",
        facts: [{ k: String(d.carrier ?? "?"), v: money(d.total_eur) }] }));
    } else if (kind === "mail_out_dry_run" || kind === "mail_out") {
      lastOut = d;
      if (/booking request/i.test(String(d.subject ?? ""))) {
        items.push(it({ side: "us", title: "Booking request to the airline", chip: "Booking", tone: "blue",
          out: { from: "us", subject: String(d.subject ?? ""), body: String(d.body ?? ""), note: `to ${d.to ?? ""}` } }));
      }
    } else if (kind === "quote_sent") {
      const c = d.chosen ?? {};
      items.push(it({ side: "us", title: "Quote sent", chip: money(c.total, c.currency) || "Quote", tone: "green",
        facts: [{ k: "Airline", v: String(c.airline ?? "?") }, { k: "Price", v: money(c.total, c.currency) }, { k: "Transit", v: `${c.transit_days ?? "?"} days` }],
        out: lastOut ? { from: "us", subject: String(lastOut.subject ?? ""), body: String(lastOut.body ?? ""), note: `to ${lastOut.to ?? ""}` } : undefined }));
    } else if (kind === "follow_up") {
      const yes = d.verdict === "accept";
      items.push(it({ side: "customer", title: yes ? "Customer says yes" : `Customer replied (${String(d.verdict ?? "").replaceAll("_", " ")})`,
        chip: yes ? "Accepted" : "Reply", tone: yes ? "green" : "blue", mail: mailOf(e.mail_id) }));
    } else if (kind === "booking_confirmed") {
      confirmedSeen = true;
      items.push(it({ side: "carrier", title: "Airline confirmed the booking", chip: String(d.booking_reference ?? "Confirmed"), tone: "green", mail: mailOf(e.mail_id) }));
    } else if (kind === "customer_informed") {
      const msg = String(d.message ?? "");
      items.push(it({ side: "us", title: msg === "confirmed" ? "Customer told: booking confirmed" : msg === "requested" ? "Customer told: booking asked for" : `Customer told (${msg})`,
        chip: "Customer told", tone: "green",
        out: lastOut ? { from: "us", subject: String(lastOut.subject ?? ""), body: String(lastOut.body ?? ""), note: `to ${lastOut.to ?? ""}` } : undefined }));
    } else if (kind === "invoice_issued") {
      items.push(it({ side: "clerk", title: `The clerk also wrote its own invoice ${d.number ?? ""} at confirmation`, chip: "Not mailed", tone: "grey",
        text: "This is the clerk's old habit (invoice at booking). It was not mailed. The real invoice comes from carrierops after delivery." }));
    }
  }
  // the clerk's events show "sent" in the live game; here they are all dry runs
  for (const it of items) if (it.out) it.out.note += " · dry run, not sent";

  // ---- phase 2: carrierops ----
  const names = new Map<string, string>();
  for (const b of bids) if (b.email) names.set(String(b.email).toLowerCase(), String(b.carrier));
  for (const x of ships) {
    if (x.airline_email) names.set(String(x.airline_email).toLowerCase(), String(x.airline));
    if (x.trucker_email) names.set(String(x.trucker_email).toLowerCase(), String(x.trucker));
  }
  const ups = all(db, "SELECT * FROM shipment_updates WHERE thread_id=? OR thread_id IS NULL ORDER BY at, id", tid);
  const firstConfirm = ups.find((u) => u.source === "carrier" && u.type === "confirmed" && u.thread_id === tid);
  let prev = null as Row | null;
  const material: { u: Row; told: boolean }[] = [];
  const delivered = ups.find((u) => u.thread_id === tid && u.source === "carrier" && u.type === "delivered" && u.status_after === "delivered");
  for (const u of ups) {
    const mine = u.thread_id === tid;
    const ds = byUpdate.get(Number(u.id)) ?? [];
    const facts: Fact[] = [];
    if (u.new_eta) facts.push({ k: "New ETA", v: eta(u.new_eta), tone: DELAYISH.has(u.type) ? "red" : undefined });
    if (u.flight) facts.push({ k: "Flight", v: String(u.flight) });
    if (u.awb) facts.push({ k: "AWB", v: String(u.awb) });
    if (u.delay_hours) facts.push({ k: "Delay", v: `+${Number(u.delay_hours)} h`, tone: "red" });
    if (u.source === "us") {
      const st6 = u.type === "shipment_opened";
      items.push({ key: `u${u.id}`, phase: "carrier", at: u.at, side: "us", title: st6 ? "Step 6: everyone informed" : String(u.summary ?? u.type),
        chip: st6 ? `${ds.length} drafts` : "", tone: st6 ? "amber" : "grey", text: st6 ? undefined : "", facts, drafts: ds });
      continue;
    }
    if (u.source === "customer") {
      const [label, tone] = CUSTOMER_TYPE[u.type] ?? [`Customer: ${String(u.type).replaceAll("_", " ")}`, "blue" as Tone];
      items.push({ key: `u${u.id}`, phase: "carrier", at: u.at, side: "customer", title: label, chip: "", tone,
        text: String(u.summary ?? ""), facts, mail: mailOf(u.mail_id), drafts: ds, clerk: clerkWords(clerkLater, u.mail_id) });
      continue;
    }
    // carrier mail
    let [label, tone] = CARRIER_TYPE[u.type] ?? [String(u.type).replaceAll("_", " "), "blue" as Tone];
    const rebookOk = u.type === "confirmed" && prev && ["cancelled_by_airline", "rebook_requested"].includes(prev.status_after) && u.status_after === "confirmed";
    const repeatConfirm = u.type === "confirmed" && firstConfirm && u.id !== firstConfirm.id && !rebookOk;
    const repeatDelay = DELAYISH.has(u.type) && prev && DELAYISH.has(prev.status_after)
      && (!u.new_eta || u.new_eta === prev.eta_after) && (!u.flight || u.flight === prev.flight_now);
    const lateMilestone = MILESTONE.has(u.type) && u.status_after !== u.type;
    if (rebookOk) { label = "Airline confirmed the new flight"; tone = "green"; }
    if (repeatConfirm || repeatDelay) { label = "Same news again, not sent again"; tone = "grey"; }
    if (lateMilestone) { label = `${label} (old news, status unchanged)`; tone = "grey"; }
    if (!mine) { label = `Not matched: ${matchWords(u.match)}`; tone = u.match?.startsWith("ambiguous") ? "amber" : "grey"; }
    if (mine && u.status_after) {
      const [sw, st] = STATUS[u.status_after] ?? [String(u.status_after), "blue" as Tone];
      facts.push({ k: "Status now", v: sw, tone: st, plain: true });
      if (u.eta_after) facts.push({ k: "ETA", v: eta(u.eta_after), tone: DELAYISH.has(u.status_after) ? "red" : undefined });
    }
    const who = String(u.sender ?? "");
    const whoName = names.get(who.toLowerCase()) ?? short(who);
    items.push({ key: `u${u.id}`, phase: "carrier", at: u.at, side: "carrier", title: label, chip: "", tone,
      text: String(u.summary ?? ""), facts: [{ k: "From", v: whoName || "carrier", plain: true }, ...facts, ...(u.match && mine ? [{ k: "Matched by", v: matchWords(u.match), plain: true }] : [])],
      mail: mailOf(u.mail_id), drafts: ds, clerk: clerkWords(clerkLater, u.mail_id) });
    if (mine) {
      const isMaterial = !repeatConfirm && !repeatDelay && !lateMilestone
        && (DELAYISH.has(u.type) || u.type === "cancelled" || MILESTONE.has(u.type) || rebookOk);
      if (isMaterial) material.push({ u, told: ds.some((d) => d.party === "customer") });
      prev = { ...u, flight_now: u.flight || prev?.flight_now || null, eta_after: u.eta_after ?? prev?.eta_after };
    }
  }

  // ---- invoice life: issued (with its draft), reminders, paid ----
  const inv = t.has("ops_invoices") ? all(db, "SELECT * FROM ops_invoices WHERE thread_id=?", tid)[0] : undefined;
  for (const d of loose) {
    const r = reasonOf.get(d.id) ?? "";
    let title = d.why, tone: Tone = "amber", chip = "Draft";
    if (r === "invoice after delivery") { title = `Invoice ${inv?.number ?? ""} issued after delivery`; tone = "blue"; chip = inv ? money(inv.amount, inv.currency) : "Invoice"; }
    else if (r.startsWith("payment reminder")) { title = `Invoice overdue: ${r}`; tone = "red"; chip = "Reminder"; }
    else if (r === "customer reported payment") continue; // shown on the customer's "we have paid" mail
    items.push({ key: `o${d.id}`, phase: "carrier", at: d.at, side: "us", title, chip, tone, facts: [], drafts: [d] });
  }
  // the paid-thanks draft hangs on the customer's paid mail
  const paidThanks = loose.filter((d) => reasonOf.get(d.id) === "customer reported payment");
  for (const p of paidThanks) {
    const host = [...items].reverse().find((it) => it.phase === "carrier" && it.side === "customer" && it.title === CUSTOMER_TYPE.paid[0] && (it.at ?? 0) <= (p.at ?? 0) + 1);
    if (host) host.drafts.push(p);
    else items.push({ key: `o${p.id}`, phase: "carrier", at: p.at, side: "us", title: p.why, chip: "Draft", tone: "amber", facts: [], drafts: [p] });
  }
  if (inv?.paid_at) {
    items.push({ key: "paid", phase: "carrier", at: inv.paid_at, side: "us", title: `Payment found, invoice ${inv.number} marked paid`, chip: "Paid", tone: "green",
      text: "The forwarder checked the bank and marked it paid (a command, not a mail).", facts: [], drafts: [] });
  }

  const clerkItems = items.filter((i) => i.phase === "clerk");
  const opsItems = items.filter((i) => i.phase === "carrier").sort((a, b) => (a.at ?? 0) - (b.at ?? 0));

  // ---- header ----
  const [sw, st] = STATUS[s.status] ?? [String(s.status ?? "?"), "blue" as Tone];
  const late = !!(s.eta_current && s.eta_planned && String(s.eta_current).slice(0, 10) > String(s.eta_planned).slice(0, 10));
  const [iw, it2] = inv ? INVOICE[inv.status] ?? [String(inv.status), "blue" as Tone] : ["No invoice yet (comes after delivery)", "grey" as Tone];
  const header: Header = {
    thread: tid, ref: String(s.our_ref ?? ""), route: `${s.origin ?? "?"} → ${s.destination ?? "?"}`, company: String(s.company ?? ""),
    customer: String(s.customer ?? ""), airline: String(s.airline ?? ""), trucker: String(s.trucker ?? ""), booking: String(s.booking_ref ?? ""),
    awb: String(s.awb ?? ""), flight: String(s.flight ?? ""), status: sw, statusTone: st,
    etaPlanned: eta(s.eta_planned), etaCurrent: eta(s.eta_current), late,
    invoice: inv ? `${inv.number} · ${money(inv.amount, inv.currency)} · ${iw}${inv.reminders ? ` · ${inv.reminders} reminder${inv.reminders > 1 ? "s" : ""}` : ""}` : iw,
    invoiceTone: it2, quote: money(s.quote_total, cur),
  };

  // ---- who was told what ----
  const order: Party[] = ["customer", "trucker", "airline", "partner", "bidder", "forwarder"];
  const parties = order.map((p) => ({ party: p, label: PARTY[p], drafts: drafts.filter((d) => d.party === p) }));

  // ---- carrier log ----
  const logRows = t.has("carrier_log") ? all(db, "SELECT * FROM carrier_log WHERE thread_id=? OR thread_id IS NULL ORDER BY at, id", tid) : [];
  const log: LogRow[] = logRows.map((r) => {
    const [w, tone] = LOG_KIND[r.kind] ?? [String(r.kind).replaceAll("_", " "), "grey" as Tone];
    return { carrier: String(r.carrier ?? ""), kind: `${w}${r.delay_hours ? ` +${Number(r.delay_hours)} h` : ""}`, detail: String(r.detail ?? "").split(" | ")[0], at: r.at ?? null, tone };
  });

  // ---- checks, all computed from the data ----
  const checks: Check[] = [];
  const told = material.filter((m) => m.told).length;
  checks.push(material.length === 0
    ? { label: "Customer told about every material update", ok: null, detail: "No delay, cancellation or movement news in this run." }
    : { label: "Customer told about every material update", ok: told === material.length,
      detail: `${told} of ${material.length} told${told < material.length ? `; not told: ${material.filter((m) => !m.told).map((m) => CARRIER_TYPE[m.u.type]?.[0] ?? m.u.type).join(", ")}` : ""}` });

  if (inv) {
    const okInv = !!delivered && Number(inv.issued_at) >= Number(delivered.at) - 1;
    checks.push({ label: "Invoice only after delivery", ok: okInv,
      detail: okInv ? `Delivered ${fmt(delivered!.at)}, invoice ${fmt(inv.issued_at)}` : delivered ? `Invoice ${fmt(inv.issued_at)} is before delivery ${fmt(delivered.at)}` : "Invoice exists but the shipment was never delivered" });
  } else {
    checks.push({ label: "Invoice only after delivery", ok: delivered ? false : true,
      detail: delivered ? "Delivered, but no invoice was written" : "Not delivered and no invoice: correct" });
  }

  const tracks = drafts.filter((d) => (reasonOf.get(d.id) ?? "").startsWith("tracking answer") && !d.shared);
  if (!tracks.length) checks.push({ label: "Tracking answer has the latest ETA", ok: null, detail: "Nobody asked where the shipment is." });
  else {
    const res = tracks.map((d) => {
      const before = ups.filter((u) => u.thread_id === tid && Number(u.at) <= Number(d.at ?? 0) && u.status_after);
      const lastSt = before.at(-1)?.status_after;
      const latest = [...before].reverse().find((u) => u.eta_after)?.eta_after ?? s.eta_planned;
      if (["cancelled_by_airline", "rebook_requested", "cancelled"].includes(lastSt)) return { ok: true, note: "no ETA while cancelled" };
      const day = String(latest ?? "");
      const time = /\d\d:\d\d/.exec(day)?.[0];
      const ok = !!day && dateForms(day).some((f) => d.body.includes(f)) && (!time || d.body.includes(time));
      return { ok, note: `${eta(day)}${ok ? "" : " missing"}` };
    });
    const ok = res.every((r) => r.ok);
    checks.push({ label: "Tracking answer has the latest ETA", ok, detail: `${res.filter((r) => r.ok).length} of ${res.length} answers: ${res.map((r) => r.note).join("; ")}` });
  }

  const mustLog = ups.filter((u) => u.thread_id === tid && u.source === "carrier" && (["cancelled", "price"].includes(u.type) || DELAYISH.has(u.type)));
  const loggedMails = new Set(logRows.map((r) => Number(r.mail_id)).filter(Boolean));
  const missingLog = mustLog.filter((u) => !loggedMails.has(Number(u.mail_id)) && !items.some((i) => i.key === `u${u.id}` && i.tone === "grey"));
  checks.push({ label: "Carrier log filled", ok: logRows.length > 0 && missingLog.length === 0,
    detail: logRows.length === 0 ? "Carrier log is empty" : `${logRows.length} entries${mustLog.length ? `; ${mustLog.length - missingLog.length} of ${mustLog.length} problem mails logged` : ""}` });

  const notDraft = drafts.filter((d) => d.status !== "draft").length;
  checks.push({ label: "Nothing sent: every message is a draft", ok: notDraft === 0, detail: `${drafts.length} messages, ${drafts.length - notDraft} drafts` });

  return { ...base, threads, thread: tid, header, items: [...clerkItems, ...opsItems], parties, log, checks };
}

function clerkWords(m: Map<number, string[]>, mailId: unknown): string | undefined {
  const w = mailId != null ? m.get(Number(mailId)) : undefined;
  return w?.length ? `The clerk alone ${[...new Set(w)].join(", then ")}.` : undefined;
}

export function fmt(ts: number | null | undefined): string {
  if (!ts) return "";
  return new Date(Number(ts) * 1000).toLocaleString("en-GB", { timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
