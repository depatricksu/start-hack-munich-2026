"use client";
// Ask Relay (v2): a question in plain words, answered from the forwarder's data by an assistant that can only read.
// While you type it also shows the matching cases at once (fixed rules, no AI call).
// Before the first question it is a start screen (title, example questions, key numbers, latest quotes).
// After it, the start screen fades, the conversation fills the page and the input glides to the bottom.
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, RotateCcw, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { RelayMark } from "@/components/logo";
import { Card, CountUp, EASE, Item, Reveal, StatusBadge, eur, money, route, shortMail } from "@/components/v2/ui";
import { Answer, tally } from "@/components/v2/ask-answer";
import type { SearchResult } from "@/lib/search";

export type LatestRow = { id: number | string; origin: string | null; destination: string | null; customer: string; price: number | null; status: string };
type Stats = { sold: number; avg: number; customers: number; revenue: number };
type Msg = { role: "user" | "assistant"; text: string; steps?: string[]; failed?: boolean };

const PHRASE = "Ask about a case, a customer, a carrier, or the numbers.";
const QUESTIONS = [
  "Why did we lose our last three quotes?",
  "Which carrier answers slowest?",
  "Which lanes do we win least often?",
  "Who owes us the most money?",
  "Sum up the newest booked case",
];

// Calm motion: the start screen fades quickly, the chat arrives a beat later, messages rise 8px.
const GLIDE = { type: "spring", stiffness: 260, damping: 32 } as const;
const fade = { initial: { opacity: 0 }, animate: { opacity: 1, transition: { duration: 0.3, ease: EASE } }, exit: { opacity: 0, transition: { duration: 0.2, ease: EASE } } };
const rise = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.4, ease: EASE } };

const fmtInt = (v: number) => Math.round(v).toLocaleString("en-GB");
const fmtEur = (v: number) => eur(v);

function Mark() {
  return (
    <span className="mt-[3px] flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-[var(--hair-2)] bg-[var(--bg-1)]">
      <RelayMark className="h-3.5 w-3.5 text-[var(--fg)]" />
    </span>
  );
}

// Three soft dots that breathe in turn, next to the latest lookup Relay is doing.
function Thinking({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-1 text-[13px] text-[var(--fg-3)]">
      <span className="flex items-center gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <motion.i key={i} className="block h-1 w-1 rounded-full bg-[var(--fg-3)]"
            animate={{ opacity: [0.25, 1, 0.25] }} transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut", delay: i * 0.18 }} />
        ))}
      </span>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={label} className="tnum text-[12px]"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
          {label}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}

function Tile({ label, value, format }: { label: string; value: number; format: (v: number) => string }) {
  return (
    <Card className="px-4 py-3.5" pad={false}>
      <div className="eyebrow">{label}</div>
      <CountUp value={value} format={format} className="mt-1.5 block whitespace-nowrap text-[20px] font-medium tracking-[-0.02em] text-[var(--fg)]" />
    </Card>
  );
}

export function Ask({ stats, latest }: { stats: Stats; latest: LatestRow[] }) {
  const [v, setV] = useState("");
  const [focused, setFocused] = useState(false);
  const [shown, setShown] = useState("");
  const [hits, setHits] = useState<SearchResult | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<string[]>([]);
  const [ready, setReady] = useState<boolean | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    fetch("/api/ask", { cache: "no-store" }).then((r) => r.json()).then((d) => setReady(!!d.ready)).catch(() => setReady(false));
  }, []);

  // Typewriter placeholder: slow and calm, a long pause on the full sentence.
  useEffect(() => {
    let i = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      i += 1;
      if (i > PHRASE.length) { timer = setTimeout(() => { i = 0; setShown(""); timer = setTimeout(tick, 600); }, 3200); return; }
      setShown(PHRASE.slice(0, i));
      timer = setTimeout(tick, 65);
    };
    timer = setTimeout(tick, 700);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, live, busy]);

  async function find(q: string) {
    const n = ++seq.current;
    if (!q.trim()) { setHits(null); return; }
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { cache: "no-store" });
      const d = (await r.json()) as SearchResult;
      if (n === seq.current) setHits(d); // ignore answers to older keystrokes
    } catch { /* the quick list is a convenience; the question still works */ }
  }
  function change(next: string) {
    setV(next);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => find(next), 220);
  }

  async function send(q0: string) {
    const q = q0.trim();
    if (!q || busy) return;
    if (debounce.current) clearTimeout(debounce.current);
    seq.current += 1;
    setV(""); setHits(null);
    const turns = [...msgs.filter((m) => !m.failed), { role: "user" as const, text: q }];
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setBusy(true); setLive([]);
    const steps: string[] = [];
    let done: Msg | null = null;
    try {
      const r = await fetch("/api/ask", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ turns: turns.map(({ role, text }) => ({ role, text })) }) });
      if (!r.ok || !r.body) {
        const d = await r.json().catch(() => ({}));
        if (d.error === "no_key") setReady(false);
        done = { role: "assistant", text: d.message ?? "The assistant did not answer.", failed: true };
      } else {
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done: eof } = await reader.read();
          if (eof) break;
          buf += dec.decode(value, { stream: true });
          let nl: number;
          while ((nl = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
            if (!line) continue;
            const d = JSON.parse(line) as { step?: { label: string }; answer?: string; error?: string; message?: string };
            if (d.step) { steps.push(d.step.label); setLive([...steps]); }
            else if (d.answer != null) done = { role: "assistant", text: d.answer, steps: [...steps] };
            else if (d.error) done = { role: "assistant", text: d.message ?? "The assistant did not answer.", failed: true };
          }
        }
      }
    } catch {
      done = { role: "assistant", text: "The connection broke before the answer arrived.", failed: true };
    }
    setMsgs((m) => [...m, done ?? { role: "assistant", text: "The assistant did not answer.", failed: true }]);
    setBusy(false); setLive([]);
    input.current?.focus();
  }

  const chatting = msgs.length > 0 || busy;
  const showHits = !!(v && hits && hits.query === v.trim() && hits.hits.length > 0);

  const form = (
    <form onSubmit={(e) => { e.preventDefault(); send(v); }}
      className="flex h-12 w-full items-center gap-3 rounded-xl border border-[var(--hair-2)] bg-[var(--bg-1)] pl-4 pr-2 transition-[border-color,box-shadow] duration-150 focus-within:border-[var(--accent)] focus-within:shadow-[0_0_0_3px_var(--accent-soft)]">
      <RelayMark className="h-4 w-4 shrink-0 text-[var(--fg-3)]" />
      <div className="relative flex-1">
        <input
          ref={input} value={v} maxLength={2000}
          onChange={(e) => change(e.target.value)}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          onKeyDown={(e) => { if (e.key === "Escape") change(""); }}
          aria-label="Ask Relay" style={{ outline: "none" }}
          className="w-full bg-transparent text-[15px] text-[var(--fg)]"
        />
        {!v && (
          <div className="pointer-events-none absolute inset-0 flex items-center overflow-hidden whitespace-nowrap text-[15px] text-[var(--fg-3)]">
            {chatting || focused ? (chatting ? "Ask a follow-up" : "Ask Relay anything") : <>{shown}<span className="caret opacity-60" /></>}
          </div>
        )}
      </div>
      {v && (
        <button type="button" onClick={() => { change(""); input.current?.focus(); }} aria-label="Clear"
          className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--fg-3)] transition-colors hover:text-[var(--fg)]">
          <X size={15} />
        </button>
      )}
      <button type="submit" aria-label="Ask" disabled={busy || !v.trim()}
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--fg)] text-[#0a0a0a] transition-[background,opacity,transform] duration-150 hover:bg-white active:scale-95 disabled:opacity-30">
        <ArrowUp size={16} strokeWidth={2.5} />
      </button>
    </form>
  );

  const notice = ready === false && (
    <p className="mt-3 text-center text-[13px] leading-relaxed text-[var(--warn)]">
      The assistant has no key yet, so questions cannot be answered. Finding cases by words still works.
      Add <span className="tnum text-[12px]">RELAY_ASSISTANT_KEY</span> to <span className="tnum text-[12px]">ui/.env.local</span> and restart the UI.
    </p>
  );

  const matches = (
    <AnimatePresence initial={false}>
      {showHits && hits && (
        <motion.div key="hits" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.28, ease: EASE }} className="overflow-hidden">
          <div className={chatting ? "pb-3" : "pt-3"}>
            <Card pad={false} className="overflow-hidden">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[var(--hair)] px-4 py-2.5">
                <span className="text-[13px] font-medium text-[var(--fg)]">Matching cases <span className="text-[var(--fg-3)]">· {hits.summary}</span></span>
                <span className="ml-auto text-[12px] text-[var(--fg-3)]">Press Enter to ask Relay instead</span>
              </div>
              <div className="scroll-thin max-h-[300px] overflow-y-auto">
                {hits.hits.slice(0, 8).map((h, i) => (
                  <Link key={h.s.thread_id} href={`/v2/requests?id=${h.s.thread_id}`}
                    className={`flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[var(--bg-2)] ${i > 0 ? "border-t border-[var(--hair)]" : ""}`}>
                    <span className="tnum w-14 shrink-0 text-[12px] text-[var(--fg-3)]">#{h.s.thread_id}</span>
                    <span className="tnum w-28 shrink-0 text-[13px] text-[var(--fg)]">{route(h.s.fields.origin, h.s.fields.destination)}</span>
                    <span className="min-w-0 flex-1 truncate text-[13px] text-[var(--fg-2)]">
                      {shortMail(h.s.customer)}
                      {h.booking && <span className="tnum ml-2 text-[12px] text-[var(--fg-3)]">{h.booking}</span>}
                    </span>
                    <span className="tnum w-28 shrink-0 text-right text-[13px] text-[var(--fg-2)]">
                      {h.s.chosen ? money(h.s.chosen.total, h.s.chosen.currency) : ""}
                    </span>
                    <StatusBadge status={h.s.status} />
                  </Link>
                ))}
              </div>
              {hits.total > 8 && (
                <div className="border-t border-[var(--hair)] px-4 py-2 text-[12px] text-[var(--fg-3)]">Showing the newest 8 of {hits.total}.</div>
              )}
            </Card>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  // One tree for both states, so nothing is torn down when the first question is sent: the input keeps its
  // place in the DOM and glides from the middle to the bottom, the start screen fades, the answers fade in.
  return (
    <motion.div layoutScroll className={`scroll-thin relative h-full ${chatting ? "overflow-hidden" : "overflow-y-auto"}`}>
      <AnimatePresence>
        {chatting && (
          <motion.button key="new" type="button" {...fade} onClick={() => { setMsgs([]); change(""); }} disabled={busy}
            className="btn btn-ghost absolute right-5 top-4 z-10 h-7 text-[12px]">
            <RotateCcw size={12} /> New conversation
          </motion.button>
        )}
      </AnimatePresence>
      <div className={`relative mx-auto flex max-w-[720px] flex-col px-6 ${chatting ? "h-full" : "min-h-full"}`}>
        <AnimatePresence mode="popLayout" initial={false}>
          {chatting ? (
            <motion.div key="chat" initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: 0.35, delay: 0.15, ease: EASE } }}
              exit={{ opacity: 0, transition: { duration: 0.15 } }}
              className="scroll-thin -mx-6 min-h-0 flex-1 overflow-y-auto px-6 pb-6 pt-16">
              <div className="space-y-6">
                {msgs.map((m, i) => m.role === "user" ? (
                  <motion.div key={i} {...rise} className="flex justify-end">
                    <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[var(--bg-3)] px-4 py-2.5 text-[15px] leading-relaxed text-[var(--fg)]">{m.text}</div>
                  </motion.div>
                ) : (
                  <motion.div key={i} {...rise} className="flex gap-3">
                    <Mark />
                    <div className="min-w-0 flex-1">
                      {m.failed ? (
                        <div className="rounded-lg border border-[var(--bad-soft)] bg-[var(--bad-soft)] px-3 py-2 text-[14px] leading-relaxed text-[var(--bad)]">
                          <span className="eyebrow mr-2 !text-[var(--bad)]">Failed</span>{m.text}
                        </div>
                      ) : <Answer text={m.text} />}
                      {!!m.steps?.length && (
                        <div className="tnum mt-2.5 text-[12px] leading-relaxed text-[var(--fg-3)]">Looked at: {tally(m.steps)}</div>
                      )}
                    </div>
                  </motion.div>
                ))}
                {busy && (
                  <motion.div {...rise} className="flex gap-3">
                    <Mark />
                    <Thinking label={live.length ? live[live.length - 1] : "Thinking"} />
                  </motion.div>
                )}
                <div ref={end} />
              </div>
            </motion.div>
          ) : (
            <motion.div key="title" {...fade} className="flex flex-1 flex-col justify-end pb-7 pt-12 text-center">
              <Reveal>
                <Item><h1 className="text-[32px] font-semibold leading-tight tracking-[-0.04em] text-[var(--fg)]">Ask Relay.</h1></Item>
                <Item><p className="mx-auto mt-2 max-w-[460px] text-[15px] leading-relaxed text-[var(--fg-2)]">Ask anything about your cases, customers, carriers and money. Relay looks it up and answers.</p></Item>
              </Reveal>
            </motion.div>
          )}
          <motion.div key="input" layout="position" transition={GLIDE} className="relative z-[1] shrink-0">
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 0.1, ease: EASE }}>
              {chatting && matches}
              {form}
              {notice}
              {!chatting && matches}
            </motion.div>
          </motion.div>
          {chatting ? <motion.div key="foot" className="h-6 shrink-0" /> : (
            <motion.div key="start" {...fade} className="flex flex-1 flex-col pb-10">
              <div className={`transition-opacity duration-200 ${v ? "pointer-events-none opacity-0" : ""}`}>
                <Reveal>
                  <Item className="mt-4 flex flex-wrap justify-center gap-2">
                    {QUESTIONS.map((x) => (
                      <button key={x} onClick={() => send(x)} disabled={ready === false}
                        className="h-8 rounded-full border border-[var(--hair-2)] px-3.5 text-[13px] text-[var(--fg-2)] transition-colors hover:bg-[var(--bg-2)] hover:text-[var(--fg)] disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-[var(--fg-2)]">
                        {x}
                      </button>
                    ))}
                  </Item>
                  <Item className="mt-12 grid grid-cols-4 gap-3">
                    <Tile label="Quotes sold" value={stats.sold} format={fmtInt} />
                    <Tile label="Avg / quote" value={stats.avg} format={fmtEur} />
                    <Tile label="Customers" value={stats.customers} format={fmtInt} />
                    <Tile label="Revenue" value={stats.revenue} format={fmtEur} />
                  </Item>
                  <Item className="mt-8">
                    <div className="mb-2.5 flex items-center justify-between px-1">
                      <span className="eyebrow">Latest quotes</span>
                      <Link href="/v2/requests" className="text-[13px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg)]">View all</Link>
                    </div>
                    <Card pad={false} className="overflow-hidden">
                      {latest.map((r, i) => (
                        <Link key={r.id} href={`/v2/requests?id=${r.id}`}
                          className={`flex items-center gap-4 px-4 py-3 transition-colors hover:bg-[var(--bg-2)] ${i > 0 ? "border-t border-[var(--hair)]" : ""}`}>
                          <span className="tnum w-24 shrink-0 text-[13px] text-[var(--fg)]">{route(r.origin, r.destination)}</span>
                          <span className="min-w-0 flex-1 truncate text-[14px] text-[var(--fg-2)]">{r.customer}</span>
                          {r.price != null && <span className="tnum text-[13px] text-[var(--fg)]">{eur(r.price)}</span>}
                          <StatusBadge status={r.status} />
                        </Link>
                      ))}
                      {!latest.length && <div className="px-4 py-6 text-center text-[14px] text-[var(--fg-3)]">No quotes yet.</div>}
                    </Card>
                  </Item>
                </Reveal>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
