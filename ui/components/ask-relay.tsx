"use client";
import { Fragment, ReactNode, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, RotateCcw, X } from "lucide-react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { RelayMark } from "@/components/logo";
import { StatusChip, money } from "@/components/bits";
import type { SearchResult } from "@/lib/search";

const PHRASE = "Ask about a case, a customer, a carrier, or the numbers.";
const QUESTIONS = [
  "Why did we lose our last three quotes?",
  "Which carrier answers slowest?",
  "Which lanes do we win least often?",
  "Who owes us the most money?",
  "Sum up the newest booked case",
];

// Start-screen parts fade away; each message rises in a little.
const fade = { initial: { opacity: 0 }, animate: { opacity: 1, transition: { duration: 0.25 } }, exit: { opacity: 0, transition: { duration: 0.18 } } };
const rise = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.25 } };

type Msg = { role: "user" | "assistant"; text: string; steps?: string[]; failed?: boolean };

// The extractor sometimes stores the text "null" for an airport it could not read.
const iata = (c?: string | null) => (c && c !== "null" ? c : "???");

// "Counting, Counting, Reading #5" -> "Counting ×2 · Reading #5": the same lookup is named once.
function tally(steps: string[]): string {
  const n = new Map<string, number>();
  for (const x of steps) n.set(x, (n.get(x) ?? 0) + 1);
  return [...n.entries()].map(([x, c]) => (c > 1 ? `${x} ×${c}` : x)).join(" · ");
}

// Inline pieces of an answer: #1234 becomes a link to the request, **x** becomes bold.
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(#\d{3,6}\b|\*\*[^*]+\*\*)/g).map((p, i) => {
    if (/^#\d{3,6}$/.test(p))
      return <Link key={`${key}-${i}`} href={`/requests?id=${p.slice(1)}`} className="num rounded-md bg-white/10 px-1.5 py-0.5 text-[13px] text-white hover:bg-white/20">{p}</Link>;
    if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={`${key}-${i}`} className="font-semibold text-white">{p.slice(2, -2)}</strong>;
    return <Fragment key={`${key}-${i}`}>{p}</Fragment>;
  });
}

// The assistant is told to write plain sentences and "- " bullets only, so this is all the formatting needed.
function Answer({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = (k: string) => {
    if (!list.length) return;
    out.push(<ul key={k} className="my-1.5 space-y-1 pl-4">{list.map((x, i) => <li key={i} className="list-disc marker:text-zinc-600">{inline(x, `${k}-${i}`)}</li>)}</ul>);
    list = [];
  };
  text.split("\n").forEach((line, i) => {
    const b = /^\s*[-•]\s+(.*)$/.exec(line);
    if (b) { list.push(b[1]); return; }
    flush(`l${i}`);
    if (line.trim()) out.push(<p key={`p${i}`} className="my-1.5 whitespace-pre-wrap">{inline(line, `p${i}`)}</p>);
  });
  flush("end");
  return <div className="text-[14.5px] leading-relaxed text-zinc-200">{out}</div>;
}

// Ask Relay: a question in plain words, answered from the runner's data by an assistant that can only read.
// While you type it also shows the matching cases at once (fixed rules, no AI call).
// Before the first question it is a start screen (title and example questions). After it, the
// start screen goes away: the conversation fills the page and the input stays at the bottom.
export function AskRelay({ children }: { children?: ReactNode }) {
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

  useEffect(() => {
    let i = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      i += 1;
      if (i > PHRASE.length) { timer = setTimeout(() => { i = 0; setShown(""); timer = setTimeout(tick, 350); }, 2200); return; }
      setShown(PHRASE.slice(0, i));
      timer = setTimeout(tick, 45);
    };
    timer = setTimeout(tick, 400);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, live, busy]);

  async function find(q: string) {
    const n = ++seq.current;
    if (!q.trim()) { setHits(null); return; }
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { cache: "no-store" });
      const d = (await r.json()) as SearchResult;
      if (n === seq.current) setHits(d);           // ignore answers to older keystrokes
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

  const form = (
    <form onSubmit={(e) => { e.preventDefault(); send(v); }}
        className="flex w-full items-center gap-4 rounded-[26px] glass glass-hi px-5 py-4">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl glass-2">
          <RelayMark className="h-4 w-4 text-white" />
        </span>
        <div className="relative flex-1">
          <input
            ref={input} value={v} maxLength={2000}
            onChange={(e) => change(e.target.value)}
            onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
            onKeyDown={(e) => { if (e.key === "Escape") change(""); }}
            aria-label="Ask Relay"
            className="w-full bg-transparent text-[15px] text-white outline-none"
          />
          {!v && !focused && (
            <div className="pointer-events-none absolute inset-0 flex items-center overflow-hidden whitespace-nowrap text-[15px] text-zinc-500">
              {chatting ? "Ask a follow-up" : <>{shown}<span className="caret" /></>}
            </div>
          )}
        </div>
        {v && (
          <button type="button" onClick={() => { change(""); input.current?.focus(); }} aria-label="Clear" className="text-zinc-500 hover:text-white">
            <X size={16} />
          </button>
        )}
        <button type="submit" aria-label="Ask" disabled={busy || !v.trim()}
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-black transition hover:bg-zinc-200 disabled:opacity-40">
          <ArrowUp size={18} strokeWidth={2.5} />
        </button>
      </form>
  );
  const notice = ready === false && (
        <p className="mt-3 text-center text-[12.5px] text-amber-300/90">
          The assistant has no key yet, so questions cannot be answered. Finding cases by words still works.
          Add <span className="num">RELAY_ASSISTANT_KEY</span> to <span className="num">ui/.env.local</span> and restart the UI.
        </p>
      );
  const matches = v && hits && hits.query === v.trim() && hits.hits.length > 0 && (
        <div className="overflow-hidden rounded-2xl glass">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
            <span className="text-sm font-medium text-white">Matching cases · {hits.summary}</span>
            <span className="ml-auto text-[11px] text-zinc-500">Press Enter to ask Relay instead</span>
          </div>
          <div className="max-h-[300px] overflow-y-auto">
            {hits.hits.slice(0, 8).map((h, i) => (
              <Link key={h.s.thread_id} href={`/requests?id=${h.s.thread_id}`}
                className={`flex items-center gap-3 px-4 py-2.5 transition hover:bg-white/5 ${i > 0 ? "border-t border-line" : ""}`}>
                <span className="num w-14 shrink-0 text-[12px] text-zinc-500">#{h.s.thread_id}</span>
                <span className="num w-28 shrink-0 text-sm font-medium text-white">
                  {iata(h.s.fields.origin)} <span className="text-zinc-600">→</span> {iata(h.s.fields.destination)}
                </span>
                <span className="min-w-0 flex-1 truncate text-[13px] text-zinc-500">
                  {h.s.customer.split("@")[0]}
                  {h.booking && <span className="num ml-2 text-zinc-400">{h.booking}</span>}
                </span>
                <span className="num w-24 shrink-0 text-right text-[13px] text-zinc-300">
                  {h.s.chosen ? money(h.s.chosen.total, h.s.chosen.currency) : "—"}
                </span>
                <StatusChip status={h.s.status} />
              </Link>
            ))}
          </div>
          {hits.total > 8 && (
            <div className="border-t border-line px-4 py-2 text-[12px] text-zinc-500">Showing the newest 8 of {hits.total}.</div>
          )}
        </div>
      );

  // One tree for both states, so nothing is torn down when the first question is sent: the input keeps its
  // place in the DOM and glides from the middle to the bottom, the start screen fades, the answers fade in.
  return (
    <MotionConfig reducedMotion="user">
    <motion.div layoutScroll className={`relative h-full ${chatting ? "overflow-hidden" : "overflow-y-auto"}`}>
      <AnimatePresence>
        {chatting && (
          <motion.button key="new" type="button" {...fade} onClick={() => { setMsgs([]); change(""); }} disabled={busy}
            className="absolute right-4 top-3 z-10 flex items-center gap-1.5 rounded-full glass-2 px-3 py-1 text-[12px] text-zinc-400 transition-colors hover:text-white disabled:opacity-40">
            <RotateCcw size={12} /> New conversation
          </motion.button>
        )}
      </AnimatePresence>
      <div className={`relative mx-auto flex max-w-2xl flex-col px-6 ${chatting ? "h-full" : "min-h-full"}`}>
        <AnimatePresence mode="popLayout" initial={false}>
          {chatting ? (
            <motion.div key="chat" initial={{ opacity: 0 }} animate={{ opacity: 1, transition: { duration: 0.3, delay: 0.12 } }} exit={{ opacity: 0, transition: { duration: 0.15 } }}
              className="min-h-0 flex-1 overflow-y-auto pb-4 pt-12">
        <div className="space-y-3">
          {msgs.map((m, i) => m.role === "user" ? (
            <motion.div key={i} {...rise} className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-white px-4 py-2.5 text-[14.5px] text-black">{m.text}</div>
            </motion.div>
          ) : (
            <motion.div key={i} {...rise} className="flex gap-3">
              <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl glass-2"><RelayMark className="h-4 w-4 text-white" /></span>
              <div className={`min-w-0 flex-1 rounded-2xl rounded-tl-md glass px-4 py-2.5 ${m.failed ? "border border-red-500/30" : ""}`}>
                {m.failed ? <p className="text-[14px] text-red-300">{m.text}</p> : <Answer text={m.text} />}
                {!!m.steps?.length && (
                  <div className="num mt-2 border-t border-line pt-2 text-[11px] text-zinc-500">Looked at: {tally(m.steps)}</div>
                )}
              </div>
            </motion.div>
          ))}
          {busy && (
            <motion.div {...rise} className="flex gap-3">
              <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl glass-2"><RelayMark className="h-4 w-4 text-white" /></span>
              <div className="flex-1 rounded-2xl rounded-tl-md glass px-4 py-3">
                <div className="flex items-center gap-2.5 text-[13px] text-zinc-400">
                  <span className="load-dots"><i /><i /><i /></span>
                  <span>{live.length ? live[live.length - 1] : "Thinking"}</span>
                </div>
              </div>
            </motion.div>
          )}
          <div ref={end} />
        </div>
            </motion.div>
          ) : (
            <motion.div key="title" {...fade} className="flex flex-1 flex-col justify-end pb-6 pt-10 text-center">
              <h1 className="text-[2rem] font-semibold tracking-tight text-white">Ask Relay.</h1>
              <p className="mt-2 text-[15px] text-zinc-500">Ask anything about your cases, customers, carriers and money. Relay looks it up and answers.</p>
            </motion.div>
          )}
          <motion.div key="input" layout="position" transition={{ type: "spring", stiffness: 260, damping: 32 }} className="shrink-0">
            {chatting && matches && <div className="mb-3">{matches}</div>}
            {form}
            {notice}
            {!chatting && matches && <div className="mt-3">{matches}</div>}
          </motion.div>
          {chatting ? <div key="foot" className="h-5 shrink-0" /> : (
            <motion.div key="start" {...fade} className="flex flex-1 flex-col pb-8">
              <div className={`mt-3 flex flex-wrap justify-center gap-1.5 transition-opacity ${v ? "pointer-events-none opacity-0" : ""}`}>
                {QUESTIONS.map((x) => (
                  <button key={x} onClick={() => send(x)} disabled={ready === false}
                    className="rounded-full glass-2 px-3 py-1 text-[12px] text-zinc-400 transition hover:text-white disabled:opacity-40">{x}</button>
                ))}
              </div>
              {children && <div className={`transition-opacity ${v ? "pointer-events-none opacity-0" : ""}`}>{children}</div>}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
    </MotionConfig>
  );
}
