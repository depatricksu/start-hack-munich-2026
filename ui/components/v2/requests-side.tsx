"use client";
// Right pane of v2 Requests: status, time to quote, the current step in one line, and the manual answer.
// Keyed on thread_id by the page, so local state (open/closed, draft) starts fresh for each request.
import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, ChevronDown, PenLine } from "lucide-react";
import { EASE, Skeleton, StatusBadge, clock, useNow } from "@/components/v2/ui";
import { groupOf, span, timeline } from "@/components/v2/requests-data";
import type { SessionDetail } from "@/lib/types";


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

// A request is still being worked on in these states; everything else is done (or waiting for the customer).
const WORKING: Record<string, number> = { new: 18, waiting_bids: 46, sending: 78, booking: 88, booking_requested: 88 };

// What happened, the way the first version showed it: ONE line that changes as the request moves on, four moving
// dots while Relay is still working on it, a tick when it is done. The earlier steps open on demand.
function Progress({ d }: { d: SessionDetail }) {
  const steps = timeline(d.events);
  const [open, setOpen] = useState(false);
  const last = steps[steps.length - 1];
  if (!last) return <p className="text-[13px] text-[var(--fg-2)]">No steps logged yet.</p>;
  const working = d.status in WORKING;
  const earlier = steps.slice(0, -1).reverse(); // newest first
  return (
    <div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
        <motion.div className="h-full rounded-full bg-[var(--fg)]" initial={false}
          animate={{ width: `${WORKING[d.status] ?? 100}%`, opacity: working ? [0.75, 1, 0.75] : 1 }}
          transition={{ width: { type: "spring", stiffness: 120, damping: 22 }, opacity: working ? { duration: 2.4, repeat: Infinity } : { duration: 0.2 } }} />
      </div>
      <div className="mt-4 flex items-start gap-3">
        <span className="mt-0.5 flex h-5 w-6 shrink-0 items-center justify-center">
          {working
            ? <span className="load-dots"><i /><i /><i /><i /></span>
            : <span className="flex h-4 w-4 items-center justify-center rounded-full bg-[var(--fg)] text-[#0a0a0a]"><Check size={11} strokeWidth={3} /></span>}
        </span>
        <div className="min-w-0 flex-1">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={last.label}
              initial={{ opacity: 0, y: 8, filter: "blur(5px)" }} animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -8, filter: "blur(5px)" }} transition={{ duration: 0.32, ease: "easeOut" }}
              className="text-[14px] font-medium leading-snug text-[var(--fg)]">
              {last.label}
            </motion.div>
          </AnimatePresence>
          <div className="tnum mt-0.5 text-[12px] text-[var(--fg-3)]">{clock(last.ts)}</div>
          {earlier.length > 0 && (
            <button onClick={() => setOpen((o) => !o)} aria-expanded={open}
              className="mt-1.5 flex items-center gap-1 text-[12px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg-2)]">
              {open ? "Hide the earlier steps" : `${earlier.length} earlier ${earlier.length === 1 ? "step" : "steps"}`}
              <ChevronDown size={12} className={`transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
            </button>
          )}
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: EASE }} className="mt-3 space-y-2 overflow-hidden border-t border-[var(--hair)] pt-3">
            {earlier.map((st) => (
              <li key={`${st.label}-${st.ts}`} className="flex items-center gap-2.5 text-[13px] text-[var(--fg-2)]">
                <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-white/15 text-[var(--fg)]"><Check size={9} strokeWidth={3} /></span>
                <span className="min-w-0 flex-1 truncate">{st.label}</span>
                <span className="tnum shrink-0 text-[12px] text-[var(--fg-3)]">{clock(st.ts)}</span>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

function Override({ d }: { d: SessionDetail }) {
  const alreadyQuoted = d.quoted_at != null;
  // Relay answers on its own. Writing to the customer by hand is an override, so it starts closed on every request.
  const [open, setOpen] = useState(false);
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
      <div className="flex justify-end">
        <button onClick={() => setOpen(true)} className="lg lg-pill"><PenLine size={14} /> Write to the customer yourself</button>
      </div>
    );
  }
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: EASE }}>
      <div className="flex items-baseline">
        <h3 className="text-[15px] font-semibold tracking-[-0.01em] text-[var(--fg)]">Write to the customer</h3>
        <span className="flex-1" />
        <button onClick={() => setOpen(false)} className="text-[13px] text-[var(--fg-2)] transition-colors hover:text-[var(--fg)]">Close</button>
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
    <div className="flex min-h-full flex-col p-5">
      <div className="space-y-6">
        <StatusBadge status={d.status} />
        <TimeToQuote d={d} />
        <div className="border-t border-[var(--hair)] pt-5">
          <div className="eyebrow mb-3">What happened</div>
          <Progress d={d} />
        </div>
        <Actions d={d} />
      </div>
      {/* Pinned to the bottom right of the pane. */}
      <div className="mt-auto pt-6"><Override d={d} /></div>
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
