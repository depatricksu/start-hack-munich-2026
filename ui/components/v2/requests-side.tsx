"use client";
// Right pane of v2 Requests: status, time to quote, every step in plain words, and the manual answer.
// Keyed on thread_id by the page, so local state (open/closed, draft) starts fresh for each request.
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { EASE, Item, Reveal, Skeleton, StatusBadge, clock, useNow } from "@/components/v2/ui";
import { groupOf, span, timeline } from "@/components/v2/requests-data";
import type { SessionDetail } from "@/lib/types";

const SHOWN = 8;

function TimeToQuote({ d }: { d: SessionDetail }) {
  const now = useNow(1000);
  const quoted = d.quoted_at != null;
  const s = (d.quoted_at ?? now) - d.received_at;
  return (
    <div>
      <div className="eyebrow">Time to quote</div>
      <div className={`tnum mt-1.5 text-[34px] font-semibold leading-none tracking-[-0.04em] ${quoted ? "text-[var(--fg)]" : "text-[var(--fg-2)]"}`}>
        {quoted || groupOf(d) === "live" ? span(s) : "-"}
      </div>
      <div className="mt-2 text-[13px] text-[var(--fg-2)]">
        {quoted ? `Mail at ${clock(d.received_at)}, quote at ${clock(d.quoted_at as number)}` : `Mail at ${clock(d.received_at)}, not quoted yet`}
      </div>
    </div>
  );
}

function Timeline({ d }: { d: SessionDetail }) {
  const steps = timeline(d.events);
  const [all, setAll] = useState(false);
  const hidden = all ? 0 : Math.max(0, steps.length - SHOWN);
  const shown = steps.slice(hidden);
  if (!steps.length) return <p className="text-[13px] text-[var(--fg-2)]">No steps logged yet.</p>;
  return (
    <div>
      {hidden > 0 && (
        <button onClick={() => setAll(true)} className="mb-3 text-[13px] text-[var(--accent)] transition-opacity duration-150 hover:opacity-80">
          Show {hidden} earlier {hidden === 1 ? "step" : "steps"}
        </button>
      )}
      <Reveal className="relative">
        <span className="absolute bottom-2 left-[3.5px] top-2 w-px bg-[var(--hair-2)]" />
        {shown.map((st, i) => {
          const last = i === shown.length - 1;
          return (
            <Item key={`${st.label}-${st.ts}`} className="relative flex items-baseline gap-3 py-1.5">
              <span className={`relative top-[-1px] h-2 w-2 shrink-0 self-center rounded-full border ${last
                ? "border-[var(--fg)] bg-[var(--fg)]" : "border-[var(--hair-2)] bg-[var(--bg)]"}`} />
              <span className={`min-w-0 flex-1 text-[13px] ${last ? "font-medium text-[var(--fg)]" : "text-[var(--fg-2)]"}`}>{st.label}</span>
              <span className="tnum shrink-0 text-[12px] text-[var(--fg-3)]">{clock(st.ts)}</span>
            </Item>
          );
        })}
      </Reveal>
    </div>
  );
}

function Override({ d }: { d: SessionDetail }) {
  const human = groupOf(d) === "need";
  const alreadyQuoted = d.quoted_at != null;
  const [open, setOpen] = useState(human);
  const [draft, setDraft] = useState(alreadyQuoted ? "" : d.reply ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function send() {
    setBusy(true); setMsg(null);
    try {
      const r = await fetch(`/api/sessions/${d.thread_id}/send`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ body: draft }),
      });
      const j = await r.json().catch(() => ({}));
      setMsg(r.ok ? { ok: true, text: "Queued. It shows below until the runner sends it." } : { ok: false, text: j.error ?? "Could not queue the reply." });
    } catch { setMsg({ ok: false, text: "Could not reach the server." }); }
    setBusy(false);
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} className="text-[13px] text-[var(--fg-2)] underline decoration-[var(--hair-2)] underline-offset-4 transition-colors duration-150 hover:text-[var(--fg)]">
        Write to the customer yourself
      </button>
    );
  }
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: EASE }}>
      <div className="flex items-baseline">
        <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-[var(--fg)]">{human ? "Your answer" : "Write to the customer"}</h3>
        <span className="flex-1" />
        {!human && <button onClick={() => setOpen(false)} className="text-[13px] text-[var(--fg-2)] transition-colors hover:text-[var(--fg)]">Close</button>}
      </div>
      <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--fg-2)]">
        {alreadyQuoted
          ? "We already quoted. Your message goes out as a normal follow-up in the same thread."
          : "Nothing has gone out yet. Your message becomes our one and only quote in this thread. State one all-in price with its currency."}
      </p>
      <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={8} placeholder="Write your reply to the customer"
        className="scroll-thin mt-3 w-full resize-y rounded-md border border-[var(--hair-2)] bg-[var(--bg-1)] p-3 text-[14px] leading-relaxed text-[var(--fg)] outline-none transition-colors placeholder:text-[var(--fg-3)] focus:border-[var(--accent)]" />
      <button onClick={send} disabled={busy || !draft.trim()} className="btn btn-primary mt-2 w-full justify-center">
        {busy ? "Queuing" : alreadyQuoted ? "Send follow-up" : "Send this quote"}
      </button>
      {msg && <p className={`mt-2 text-[13px] ${msg.ok ? "text-[var(--fg-2)]" : "text-[var(--bad)]"}`}>{msg.text}</p>}
      <p className="mt-2 text-[12px] text-[var(--fg-3)]">The runner sends it within a second. The UI never sends mail itself.</p>
    </motion.div>
  );
}

function Actions({ d }: { d: SessionDetail }) {
  if (!d.actions.length) return null;
  const pending = d.actions.some((a) => a.done_at == null);
  return (
    <div className="border-t border-[var(--hair)] pt-5">
      <div className="eyebrow mb-3">Your actions</div>
      <ul className="space-y-2">
        <AnimatePresence initial={false}>
          {d.actions.map((a) => (
            <motion.li key={a.id} layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: EASE }}
              className="rounded-md border border-[var(--hair)] bg-[var(--bg-1)] p-3">
              <div className="flex items-baseline gap-2 text-[13px]">
                <span className="font-medium text-[var(--fg)]">
                  {a.done_at == null ? "Queued, waiting for the runner" : a.result === "sent" ? "Sent" : a.result ?? "Done"}
                </span>
                <span className="flex-1" />
                <span className="tnum text-[12px] text-[var(--fg-3)]">{clock(a.done_at ?? a.created_at)}</span>
              </div>
              <div className="mt-1 line-clamp-2 text-[13px] text-[var(--fg-2)]">{a.body}</div>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
      {pending && <p className="mt-2 text-[12px] text-[var(--fg-3)]">The clerk picks it up on its next poll.</p>}
    </div>
  );
}

export function RequestSide({ d }: { d: SessionDetail }) {
  return (
    <div className="space-y-6 p-5">
      <StatusBadge status={d.status} />
      <TimeToQuote d={d} />
      <div className="border-t border-[var(--hair)] pt-5">
        <div className="eyebrow mb-3">What happened</div>
        <Timeline d={d} />
      </div>
      <div className="border-t border-[var(--hair)] pt-5"><Override d={d} /></div>
      <Actions d={d} />
    </div>
  );
}

export function SideSkeleton() {
  return (
    <div className="space-y-6 p-5">
      <Skeleton className="h-[22px] w-24 rounded-full" />
      <div className="space-y-2"><Skeleton className="h-3 w-24" /><Skeleton className="h-9 w-32" /><Skeleton className="h-3.5 w-48" /></div>
      <div className="space-y-3 border-t border-[var(--hair)] pt-5">
        <Skeleton className="h-3 w-28" />
        {Array.from({ length: 7 }, (_, i) => <div key={i} className="flex justify-between"><Skeleton className="h-3.5 w-44" /><Skeleton className="h-3.5 w-10" /></div>)}
      </div>
    </div>
  );
}
