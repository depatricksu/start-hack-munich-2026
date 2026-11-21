"use client";
import { useEffect, useMemo, useState } from "react";
import { BigClock, Countdown, LANG_FLAG, StatusChip, bestOption, money, sameOption } from "@/components/bits";
import { EventRow, Option, Session, SessionDetail, Status } from "@/lib/types";

type Source = "live" | "demo";

const EVENT_LABEL: Record<string, string> = {
  mail_in: "Mail received", llm: "Read by the AI", options: "Prices found", waiting_bids: "Waiting for carrier bids",
  bid_wait_over: "Bid wait over", quote_sent: "Quote sent", mail_out: "Mail sent", mail_out_dry_run: "Mail prepared (dry run)",
  needs_human: "Handed to a human", rfq_expired: "Request expired", portal_error: "Portal error", error: "Error",
  quote_skipped_already_sent: "Second quote blocked",
};

function useJson<T>(url: string | null, every = 2000): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    if (!url) return;
    let alive = true;
    const load = () => fetch(url, { cache: "no-store" }).then((r) => r.json()).then((d) => alive && setData(d)).catch(() => {});
    load();
    const t = setInterval(load, every);
    return () => { alive = false; clearInterval(t); };
  }, [url, every]);
  return data;
}

function splitNote(note: string | null): { code: string | null; text: string } {
  if (!note) return { code: null, text: "" };
  const m = /^([a-z_]+):\s*([\s\S]*)$/.exec(note);
  return m ? { code: m[1], text: m[2] } : { code: null, text: note };
}

function Route({ s, className }: { s: Session; className?: string }) {
  const f = s.fields;
  return (
    <span className={`num font-semibold ${className ?? ""}`}>
      {f.origin ?? "???"} <span className="text-zinc-300">→</span> {f.destination ?? "???"}
    </span>
  );
}

// ---------- Left rail: the queue ----------

function SessionRow({ s, active, onClick }: { s: Session; active: boolean; onClick: () => void }) {
  const urgent = s.status === "needs_human" || s.status === "failed";
  return (
    <button onClick={onClick}
      className={`w-full text-left rounded-lg border px-3 py-2.5 transition ${
        active ? "border-zinc-900 bg-white shadow-sm" : "border-line bg-surface hover:border-zinc-300"
      } ${urgent ? "border-l-[3px] border-l-red-500" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <Route s={s} className="text-[15px]" />
        <StatusChip status={s.status} />
      </div>
      <div className="mt-0.5 truncate text-[13px] text-zinc-500">{s.customer}</div>
      <div className="mt-1.5 flex items-center justify-between">
        <Countdown receivedAt={s.received_at} quotedAt={s.quoted_at} status={s.status} />
        <span className="num text-[13px] font-medium text-zinc-700">{s.chosen ? money(s.chosen.total, s.chosen.currency) : "—"}</span>
      </div>
    </button>
  );
}

const GROUPS: { key: string; label: string; match: Status[]; accent?: boolean }[] = [
  { key: "need", label: "Needs you", match: ["needs_human", "failed"], accent: true },
  { key: "live", label: "In flight", match: ["new", "waiting_bids", "sending"] },
  { key: "done", label: "Quoted", match: ["quoted", "booking", "booking_requested", "booked", "confirmed", "lost"] },
  { key: "closed", label: "Closed", match: ["expired"] },
];

function Rail({ sessions, source, activeId, onSelect }: { sessions: Session[]; source: Source; activeId: number | null; onSelect: (id: number) => void }) {
  const needCount = sessions.filter((s) => s.status === "needs_human" || s.status === "failed").length;
  return (
    <aside className="rail flex w-80 shrink-0 flex-col overflow-y-auto border-r border-line bg-surface-2 p-3">
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-sm font-semibold">Requests <span className="num text-zinc-400">{sessions.length}</span></h2>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ring-1 ring-inset ${
          source === "live" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200"}`}>
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${source === "live" ? "live-dot bg-emerald-500" : "bg-amber-500"}`} />
          {source === "live" ? "Live" : "Demo"}
        </span>
      </div>
      {needCount > 0 && (
        <div className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          <span className="font-semibold">{needCount}</span> {needCount === 1 ? "request needs" : "requests need"} a human now
        </div>
      )}
      <div className="space-y-4">
        {GROUPS.map((g) => {
          const rows = sessions.filter((s) => g.match.includes(s.status));
          if (!rows.length) return null;
          return (
            <div key={g.key}>
              <div className={`mb-1.5 flex items-center gap-2 px-1 text-xs font-semibold uppercase tracking-wide ${g.accent ? "text-red-600" : "text-zinc-400"}`}>
                {g.label} <span className="num font-normal text-zinc-400">{rows.length}</span>
              </div>
              <div className="space-y-2">
                {rows.map((s) => <SessionRow key={s.thread_id} s={s} active={s.thread_id === activeId} onClick={() => onSelect(s.thread_id)} />)}
              </div>
            </div>
          );
        })}
        {sessions.length === 0 && <p className="px-1 text-sm text-zinc-500">No requests yet.</p>}
      </div>
    </aside>
  );
}

// ---------- Centre: the facts ----------

function Fact({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="text-[11px] uppercase tracking-wide text-zinc-400">{k}</div>
      <div className={`num mt-0.5 font-semibold ${warn ? "text-amber-600" : ""}`}>{v}</div>
    </div>
  );
}

function OptionsTable({ options, chosen }: { options: Option[]; chosen: Option | null }) {
  if (!options.length) return <p className="text-sm text-zinc-500">No prices found yet.</p>;
  const best = bestOption(options);
  const sorted = [...options].sort((a, b) => Number(a.total_eur) - Number(b.total_eur));
  return (
    <table className="w-full text-sm">
      <thead><tr className="text-left text-[11px] uppercase tracking-wide text-zinc-400">
        <th className="py-1 font-medium">Airline</th><th className="font-medium">Source</th><th className="font-medium">Days</th><th className="text-right font-medium">Total</th>
      </tr></thead>
      <tbody>
        {sorted.map((o, i) => {
          const isChosen = sameOption(o, chosen);
          const isBest = sameOption(o, best);
          return (
            <tr key={i} className={`border-t border-zinc-100 ${isChosen ? "bg-emerald-50/70" : ""}`}>
              <td className="py-1.5">
                <span className={isChosen ? "font-medium" : ""}>{o.airline}</span>
                {isChosen && <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">QUOTED</span>}
                {isBest && !isChosen && <span className="ml-2 rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-500">CHEAPEST</span>}
              </td>
              <td className="text-zinc-500">{o.source}</td>
              <td className="num">{o.transit_days}</td>
              <td className="num text-right">{money(o.total, o.currency)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function QuoteCard({ chosen, options }: { chosen: Option; options: Option[] }) {
  const best = bestOption(options);
  const overBest = best && !sameOption(chosen, best) && Number(best.total_eur) > 0
    ? ((Number(chosen.total_eur) - Number(best.total_eur)) / Number(best.total_eur)) * 100 : 0;
  return (
    <div className="rounded-xl border border-emerald-200 bg-surface p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-zinc-400">Quote sent</div>
          <div className="num mt-1 text-4xl font-semibold tracking-tight">{money(chosen.total, chosen.currency)}</div>
          <div className="mt-1 text-sm text-zinc-600">{chosen.airline} · {chosen.transit_days} days · via {chosen.source}</div>
        </div>
        {overBest > 0.1
          ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-inset ring-amber-200">+{overBest.toFixed(1)}% over cheapest</span>
          : <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200">cheapest option</span>}
      </div>
    </div>
  );
}

function Timeline({ events, t0 }: { events: EventRow[]; t0: number }) {
  return (
    <ol className="space-y-2.5">
      {events.map((e, i) => (
        <li key={e.id} className="flex gap-3 text-sm">
          <span className="num w-10 shrink-0 text-right text-zinc-400">+{Math.max(0, Math.round(e.ts - t0))}s</span>
          <span className="relative flex flex-col items-center">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
              e.kind === "needs_human" || e.kind.includes("error") ? "bg-red-500" : e.kind === "quote_sent" ? "bg-emerald-500" : "bg-zinc-300"}`} />
            {i < events.length - 1 && <span className="mt-0.5 w-px flex-1 bg-zinc-200" />}
          </span>
          <span className="pb-0.5">{EVENT_LABEL[e.kind] ?? e.kind}</span>
        </li>
      ))}
    </ol>
  );
}

function Facts({ d }: { d: SessionDetail }) {
  const f = d.fields;
  const note = splitNote(d.note);
  const lang = (f.language ?? "").toLowerCase();
  return (
    <div className="mx-auto max-w-2xl space-y-5 p-6">
      <div>
        <div className="text-3xl"><Route s={d} /></div>
        <div className="mt-1.5 text-sm text-zinc-600">{d.customer}</div>
        <div className="text-sm text-zinc-400">{d.subject}</div>
      </div>

      {(d.status === "needs_human" || d.status === "failed") && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-red-800">
            Needs a human {note.code && <span className="num rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium">{note.code}</span>}
          </div>
          <p className="mt-1 text-sm text-red-700">{note.text || "The system could not price this safely. Step in on the right."}</p>
        </div>
      )}

      <div className="grid grid-cols-4 gap-3">
        <Fact k="Weight" v={f.weight_kg != null ? `${f.weight_kg} kg` : "?"} warn={f.weight_kg == null} />
        <Fact k="Volume" v={f.volume_cbm != null ? `${f.volume_cbm} cbm` : "?"} warn={f.volume_cbm == null} />
        <Fact k="Wants" v={f.prefer ?? "cheapest"} />
        <Fact k="Language" v={LANG_FLAG[lang] ?? (lang ? lang.toUpperCase() : "?")} />
      </div>

      {d.chosen && <QuoteCard chosen={d.chosen} options={d.options} />}

      <section className="rounded-xl border border-line bg-surface p-5">
        <h3 className="mb-2 text-sm font-semibold">Price options <span className="num font-normal text-zinc-400">{d.options.length}</span></h3>
        <OptionsTable options={d.options} chosen={d.chosen} />
      </section>

      <section className="rounded-xl border border-line bg-surface p-5">
        <h3 className="mb-3 text-sm font-semibold">Thread</h3>
        <div className="space-y-3">
          {d.mails.map((m) => (
            <div key={m.id} className="rounded-lg bg-surface-2 p-3 text-sm ring-1 ring-inset ring-line">
              <div className="mb-1 text-xs text-zinc-400">{m.sender}</div>
              <div className="whitespace-pre-wrap">{m.body}</div>
            </div>
          ))}
          {d.reply && (
            <div className="ml-8 rounded-lg bg-emerald-50 p-3 text-sm ring-1 ring-inset ring-emerald-100">
              <div className="mb-1 text-xs font-medium text-emerald-700">Our reply</div>
              <div className="whitespace-pre-wrap">{d.reply}</div>
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-line bg-surface p-5">
        <h3 className="mb-3 text-sm font-semibold">What the system did</h3>
        <Timeline events={d.events} t0={d.received_at} />
      </section>
    </div>
  );
}

// ---------- Right rail: the operator panel (always on screen) ----------

function Operator({ d }: { d: SessionDetail }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setDraft(d.reply ?? ""); setErr(null); }, [d.thread_id, d.reply]);
  const alreadyQuoted = d.quoted_at != null;
  const pending = d.actions.some((a) => a.done_at == null);

  async function send() {
    setBusy(true); setErr(null);
    try {
      const r = await fetch(`/api/sessions/${d.thread_id}/send`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: draft }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) setErr(j.error ?? "Could not queue the reply.");
    } catch { setErr("Could not reach the server."); }
    setBusy(false);
  }

  return (
    <aside className="rail flex w-[23rem] shrink-0 flex-col overflow-y-auto border-l border-line bg-surface p-5">
      <div className="flex items-center justify-between">
        <StatusChip status={d.status} lg />
      </div>

      <div className="mt-4 rounded-xl border border-line bg-surface-2 p-4">
        <BigClock receivedAt={d.received_at} quotedAt={d.quoted_at} status={d.status} />
      </div>

      <div className="mt-5">
        <div className="flex items-center gap-2">
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${alreadyQuoted ? "bg-zinc-400" : "bg-red-500"}`} />
          <h3 className="text-sm font-semibold">Step in</h3>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-zinc-500">
          {alreadyQuoted
            ? "We already quoted. Your message goes out as a normal follow-up in the same thread."
            : "Nothing has gone out yet. Your message becomes our one and only quote in this thread — state one all-in price with its currency."}
        </p>
        <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={8}
          placeholder="Write your reply to the customer…"
          className="mt-2 w-full rounded-lg border border-line bg-white p-3 text-sm outline-none focus:border-zinc-900" />
        <button onClick={send} disabled={busy || !draft.trim()}
          className={`mt-2 w-full rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition disabled:opacity-40 ${
            alreadyQuoted ? "bg-zinc-900 hover:bg-zinc-800" : "bg-red-600 hover:bg-red-500"}`}>
          {busy ? "Queuing…" : alreadyQuoted ? "Send follow-up as human" : "Take over — send this quote"}
        </button>
        {err && <p className="mt-2 text-xs text-red-600">{err}</p>}
        <p className="mt-2 text-[11px] text-zinc-400">The runner sends it within a second. The UI never sends mail itself.</p>
      </div>

      {d.actions.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Your actions</h4>
          <ul className="space-y-2 text-xs">
            {d.actions.map((a) => (
              <li key={a.id} className="rounded-lg bg-surface-2 p-2.5 ring-1 ring-inset ring-line">
                <div className={`font-medium ${a.done_at == null ? "text-amber-700" : a.result === "sent" ? "text-emerald-700" : "text-red-600"}`}>
                  {a.done_at == null ? "Queued — waiting for the runner" : a.result === "sent" ? "Sent" : a.result ?? "done"}
                </div>
                <div className="mt-0.5 line-clamp-2 text-zinc-500">{a.body}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {pending && <p className="mt-3 text-[11px] text-amber-700">An action is queued. The clerk picks it up on its next poll.</p>}
    </aside>
  );
}

// ---------- Page ----------

export default function Sessions() {
  const list = useJson<{ source: Source; sessions: Session[] }>("/api/sessions");
  const [sel, setSel] = useState<number | null>(null);
  const sessions = useMemo(() => list?.sessions ?? [], [list]);
  const activeId = sel ?? sessions.find((s) => s.status === "needs_human")?.thread_id ?? sessions[0]?.thread_id ?? null;
  const detail = useJson<{ source: Source; session: SessionDetail | null }>(activeId ? `/api/sessions/${activeId}` : null);

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <Rail sessions={sessions} source={list?.source ?? "demo"} activeId={activeId} onSelect={setSel} />
      <section className="flex-1 overflow-y-auto">
        {detail?.session ? <Facts d={detail.session} /> : <div className="p-10 text-sm text-zinc-500">Select a request.</div>}
      </section>
      {detail?.session && <Operator d={detail.session} />}
    </div>
  );
}
