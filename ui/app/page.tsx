"use client";
import { useEffect, useMemo, useState } from "react";
import { Countdown, LANG_FLAG, StatusChip, money } from "@/components/bits";
import { EventRow, FileRef, Option, Session, SessionDetail } from "@/lib/types";

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

function Route({ s }: { s: Session }) {
  const f = s.fields;
  return (
    <span className="num font-semibold">
      {f.origin ?? "???"} <span className="text-zinc-400">→</span> {f.destination ?? "???"}
    </span>
  );
}

function SessionRow({ s, active, onClick }: { s: Session; active: boolean; onClick: () => void }) {
  const urgent = s.status === "needs_human";
  return (
    <button onClick={onClick}
      className={`w-full text-left rounded-xl border px-4 py-3 transition ${active ? "border-zinc-900 bg-white shadow-sm" : "border-zinc-200 bg-white hover:border-zinc-300"} ${urgent ? "border-l-4 border-l-red-500" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <Route s={s} />
        <StatusChip status={s.status} />
      </div>
      <div className="mt-1 truncate text-sm text-zinc-600">{s.customer}</div>
      <div className="mt-2 flex items-center justify-between">
        <Countdown receivedAt={s.received_at} quotedAt={s.quoted_at} status={s.status} />
        <span className="num text-sm font-medium">{s.chosen ? money(s.chosen.total, s.chosen.currency) : "no price yet"}</span>
      </div>
    </button>
  );
}

function OptionsTable({ options, chosen }: { options: Option[]; chosen: Option | null }) {
  if (!options.length) return <p className="text-sm text-zinc-500">No prices found yet.</p>;
  return (
    <table className="w-full text-sm">
      <thead><tr className="text-left text-xs uppercase tracking-wide text-zinc-400">
        <th className="py-1 font-medium">Airline</th><th className="font-medium">Source</th><th className="font-medium">Days</th><th className="text-right font-medium">Total</th>
      </tr></thead>
      <tbody>
        {options.map((o, i) => {
          const isChosen = chosen && o.airline === chosen.airline && o.total === chosen.total;
          return (
            <tr key={i} className={`border-t border-zinc-100 ${isChosen ? "bg-emerald-50/60 font-medium" : ""}`}>
              <td className="py-1.5">{o.airline}{isChosen && <span className="ml-2 text-xs text-emerald-700">quoted</span>}</td>
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

// Files on a mail: the customer's request as PDF / Word / voice message, or the offer PDF on our reply.
function Files({ files, ours = false }: { files?: FileRef[]; ours?: boolean }) {
  if (!files || files.length === 0) return null;
  const size = (b: number | null) => (b == null ? "" : b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`);
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {files.map((f, i) => (
        <span key={i} title={f.type ?? undefined}
          className={`inline-flex items-center gap-2 rounded-md border px-2 py-1 text-xs ${ours ? "border-emerald-200 bg-white text-emerald-800" : "border-zinc-200 bg-white text-zinc-700"}`}>
          <span className={`rounded px-1 font-mono text-[10px] font-semibold uppercase ${ours ? "bg-emerald-100" : "bg-zinc-100"}`}>
            {(f.filename.split(".").pop() ?? "file").slice(0, 4)}
          </span>
          <span className="font-mono">{f.filename}</span>
          {f.bytes != null && <span className="text-zinc-400">{size(f.bytes)}</span>}
        </span>
      ))}
    </div>
  );
}

function Timeline({ events, t0 }: { events: EventRow[]; t0: number }) {
  return (
    <ol className="space-y-2">
      {events.map((e) => (
        <li key={e.id} className="flex gap-3 text-sm">
          <span className="num w-12 shrink-0 text-right text-zinc-400">+{Math.max(0, Math.round(e.ts - t0))}s</span>
          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${e.kind === "needs_human" || e.kind.includes("error") ? "bg-red-500" : e.kind === "quote_sent" ? "bg-emerald-500" : "bg-zinc-300"}`} />
          <span>{EVENT_LABEL[e.kind] ?? e.kind}</span>
        </li>
      ))}
    </ol>
  );
}


function TakeOver({ d, draft, setDraft }: { d: SessionDetail; draft: string; setDraft: (v: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const alreadyQuoted = d.quoted_at != null;
  async function send() {
    setBusy(true); setErr(null);
    const r = await fetch(`/api/sessions/${d.thread_id}/send`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: draft }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) setErr(j.error ?? "Could not queue the reply."); else setDraft("");
    setBusy(false);
  }
  return (
    <section className="rounded-xl border-2 border-dashed border-zinc-300 bg-white p-5">
      <h3 className="text-sm font-semibold">Take over</h3>
      <p className="mb-2 text-xs text-zinc-500">
        {alreadyQuoted ? "We already quoted. A new message goes out as a normal follow-up in the same thread."
          : "Nothing has gone out yet. Your message becomes our one and only quote in this thread, so state one all-in price with its currency."}
      </p>
      <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={5} placeholder="Your reply to the customer"
        className="w-full rounded-lg border border-zinc-200 p-3 text-sm outline-none focus:border-zinc-900" />
      <div className="mt-2 flex items-center gap-3">
        <button onClick={send} disabled={busy || !draft.trim()}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">{busy ? "Queuing..." : "Send as human"}</button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
      {d.actions.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-zinc-100 pt-3 text-xs">
          {d.actions.map((a) => (
            <li key={a.id} className="flex gap-2">
              <span className={a.done_at == null ? "text-amber-700" : a.result === "sent" ? "text-emerald-700" : "text-red-600"}>
                {a.done_at == null ? "Queued, waiting for the runner" : a.result === "sent" ? "Sent" : a.result}
              </span>
              <span className="truncate text-zinc-400">{a.body}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Detail({ d }: { d: SessionDetail }) {
  const f = d.fields;
  const note = splitNote(d.note);
  const [draft, setDraft] = useState("");
  useEffect(() => { setDraft(d.reply ?? ""); }, [d.thread_id, d.reply]);
  const lang = (f.language ?? "").toLowerCase();
  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-2xl"><Route s={d} /></div>
          <div className="mt-1 text-sm text-zinc-600">{d.customer}</div>
          <div className="text-sm text-zinc-400">{d.subject}</div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <StatusChip status={d.status} />
          <Countdown receivedAt={d.received_at} quotedAt={d.quoted_at} status={d.status} />
        </div>
      </div>

      {(d.status === "needs_human" || d.status === "failed") && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-red-800">
            Needs a human {note.code && <span className="num rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium">{note.code}</span>}
          </div>
          <p className="mt-1 text-sm text-red-700">{note.text || "The system could not price this safely."}</p>
        </div>
      )}

      <div className="grid grid-cols-4 gap-3">
        {[["Weight", f.weight_kg != null ? `${f.weight_kg} kg` : "?"], ["Volume", f.volume_cbm != null ? `${f.volume_cbm} cbm` : "?"],
          ["Wants", f.prefer ?? "cheapest"], ["Language", LANG_FLAG[lang] ?? (lang ? lang.toUpperCase() : "?")]].map(([k, v]) => (
          <div key={k} className="rounded-xl border border-zinc-200 bg-white p-3">
            <div className="text-xs uppercase tracking-wide text-zinc-400">{k}</div>
            <div className="num mt-0.5 font-semibold">{v}</div>
          </div>
        ))}
      </div>

      {d.chosen && (
        <div className="rounded-xl border border-emerald-200 bg-white p-5">
          <div className="text-xs uppercase tracking-wide text-zinc-400">Quote</div>
          <div className="num mt-1 text-4xl font-semibold tracking-tight">{money(d.chosen.total, d.chosen.currency)}</div>
          <div className="mt-1 text-sm text-zinc-600">{d.chosen.airline} · {d.chosen.transit_days} days · via {d.chosen.source}</div>
        </div>
      )}

      <section className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="mb-2 text-sm font-semibold">Price options</h3>
        <OptionsTable options={d.options} chosen={d.chosen} />
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold">Thread</h3>
        <div className="space-y-3">
          {d.mails.map((m) => (
            <div key={m.id} className="rounded-lg bg-zinc-50 p-3 text-sm">
              <div className="mb-1 text-xs text-zinc-400">{m.sender}</div>
              <div className="whitespace-pre-wrap">{m.body}</div>
              <Files files={m.files} />
            </div>
          ))}
          {d.reply && (
            <div className="ml-8 rounded-lg bg-emerald-50 p-3 text-sm">
              <div className="mb-1 text-xs text-emerald-700">Our reply{d.reply_files?.length ? " · with attachment" : ""}</div>
              <div className="whitespace-pre-wrap">{d.reply}</div>
              <Files files={d.reply_files} ours />
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-zinc-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold">What the system did</h3>
        <Timeline events={d.events} t0={d.received_at} />
      </section>

      <TakeOver d={d} draft={draft} setDraft={setDraft} />
    </div>
  );
}

export default function Sessions() {
  const list = useJson<{ source: Source; sessions: Session[] }>("/api/sessions");
  const [sel, setSel] = useState<number | null>(null);
  const sessions = useMemo(() => list?.sessions ?? [], [list]);
  const activeId = sel ?? sessions.find((s) => s.status === "needs_human")?.thread_id ?? sessions[0]?.thread_id ?? null;
  const detail = useJson<{ source: Source; session: SessionDetail | null }>(activeId ? `/api/sessions/${activeId}` : null);

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <aside className="w-96 shrink-0 overflow-y-auto border-r border-zinc-200 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Requests <span className="num text-zinc-400">{sessions.length}</span></h2>
          {list && <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ring-inset ${list.source === "live" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200"}`}>
            {list.source === "live" ? "Live data" : "Demo data"}</span>}
        </div>
        <div className="space-y-2">
          {sessions.map((s) => <SessionRow key={s.thread_id} s={s} active={s.thread_id === activeId} onClick={() => setSel(s.thread_id)} />)}
          {list && sessions.length === 0 && <p className="text-sm text-zinc-500">No requests yet.</p>}
        </div>
      </aside>
      <section className="flex-1 overflow-y-auto">
        {detail?.session ? <Detail d={detail.session} /> : <div className="p-10 text-sm text-zinc-500">Select a request.</div>}
      </section>
    </div>
  );
}
