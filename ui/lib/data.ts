// One place the screens get data from: the real DB when it has sessions, demo data otherwise.
import { getDb } from "./db";
import { fakeDetail, fakeSessions } from "./fake";
import { ActionRow, EventRow, MailRow, QUOTE_SENT, Session, SessionDetail, Stats } from "./types";

export type Source = "live" | "demo";

function parse<T>(v: unknown, fallback: T): T {
  if (typeof v !== "string" || !v) return fallback;
  try { return JSON.parse(v) as T; } catch { return fallback; }
}

function rowToSession(r: Record<string, unknown>): Session {
  return {
    thread_id: r.thread_id as number, customer: (r.customer as string) ?? "", subject: (r.subject as string) ?? "",
    status: (r.status as Session["status"]) ?? "new",
    fields: parse(r.fields, {}), options: parse(r.options, []), chosen: parse(r.chosen, null),
    reply: (r.reply as string) ?? null, note: (r.note as string) ?? null,
    received_at: r.received_at as number, deadline: (r.deadline as number) ?? null,
    quoted_at: (r.quoted_at as number) ?? null, llm_cost_usd: (r.llm_cost_usd as number) ?? null,
  };
}

function useDemo(): boolean {
  if (process.env.UI_DEMO === "1") return true;
  const db = getDb();
  if (!db) return true;
  const n = db.prepare("SELECT COUNT(*) AS n FROM sessions").get().n as number;
  return n === 0;
}

export function getSessions(): { source: Source; sessions: Session[] } {
  if (useDemo()) return { source: "demo", sessions: fakeSessions() };
  const rows = getDb().prepare("SELECT * FROM sessions ORDER BY received_at DESC LIMIT 200").all() as Record<string, unknown>[];
  return { source: "live", sessions: rows.map(rowToSession) };
}

export function getDetail(id: number): { source: Source; session: SessionDetail | null } {
  if (useDemo()) return { source: "demo", session: fakeDetail(id) };
  const db = getDb();
  const r = db.prepare("SELECT * FROM sessions WHERE thread_id=?").get(id) as Record<string, unknown> | undefined;
  if (!r) return { source: "live", session: null };
  const events = (db.prepare("SELECT id, ts, kind, data FROM events WHERE thread_id=? ORDER BY id").all(id) as Record<string, unknown>[])
    .map((e): EventRow => ({ id: e.id as number, ts: e.ts as number, kind: e.kind as string, data: parse(e.data, {}) }));
  const mails = db.prepare("SELECT id, sender, subject, body, received_at, route FROM mails WHERE thread_id=? ORDER BY id").all(id) as MailRow[];
  let actions: ActionRow[] = [];
  try { actions = db.prepare("SELECT id, kind, body, created_at, done_at, result FROM actions WHERE thread_id=? ORDER BY id").all(id) as ActionRow[]; } catch { /* table not created yet */ }
  return { source: "live", session: { ...rowToSession(r), events, mails, actions } };
}

export function computeStats(sessions: Session[]): Stats {
  const quoted = sessions.filter((s) => QUOTE_SENT.includes(s.status));
  const times = quoted.filter((s) => s.quoted_at).map((s) => (s.quoted_at as number) - s.received_at).sort((a, b) => a - b);
  const median = times.length ? times[Math.floor(times.length / 2)] : null;
  const costs = quoted.map((s) => s.llm_cost_usd ?? 0);
  return {
    total: sessions.length, quoted: quoted.length,
    needs_human: sessions.filter((s) => s.status === "needs_human").length,
    open: sessions.filter((s) => ["new", "waiting_bids", "sending"].includes(s.status)).length,
    median_response_s: median,
    cost_per_quote_usd: quoted.length ? costs.reduce((a, b) => a + b, 0) / quoted.length : null,
    response_times: times,
  };
}
