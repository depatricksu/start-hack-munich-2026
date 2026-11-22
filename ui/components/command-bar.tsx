"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowUp, X } from "lucide-react";
import { RelayMark } from "@/components/logo";
import { StatusChip, money } from "@/components/bits";
import type { SearchResult } from "@/lib/search";

const PHRASE = "Find a case: a lane, a customer, a booking, a word from the mail.";
const EXAMPLES = ["HAM RUH", "lost today", "nordlicht", "lost last 3h", "korean", "dangerous goods", "stuck"];

// The extractor sometimes stores the text "null" for an airport it could not read.
const iata = (c?: string | null) => (c && c !== "null" ? c : "???");

// Ask Relay: type plain words, get the matching cases from the runner's data. It searches as you type
// (after a short pause) and on Enter. Read-only, no AI call, nothing is sent.
export function CommandBar() {
  const [v, setV] = useState("");
  const [focused, setFocused] = useState(false);
  const [shown, setShown] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  useEffect(() => {
    let i = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = () => {
      i += 1;
      if (i > PHRASE.length) {
        timer = setTimeout(() => { i = 0; setShown(""); timer = setTimeout(tick, 350); }, 2200);
        return;
      }
      setShown(PHRASE.slice(0, i));
      timer = setTimeout(tick, 45);
    };
    timer = setTimeout(tick, 400);
    return () => clearTimeout(timer);
  }, []);

  async function run(q: string) {
    const n = ++seq.current;
    if (!q.trim()) { setRes(null); setBusy(false); return; }
    setBusy(true);
    try {
      const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`, { cache: "no-store" });
      const d = (await r.json()) as SearchResult;
      if (n === seq.current) setRes(d);           // ignore answers to older keystrokes
    } finally {
      if (n === seq.current) setBusy(false);
    }
  }

  // Search shortly after the user stops typing.
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  function change(next: string) {
    setV(next);
    if (debounce.current) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => run(next), 220);
  }
  function pick(q: string) { setV(q); run(q); input.current?.focus(); }
  function clear() { setV(""); run(""); input.current?.focus(); }

  return (
    <div className="w-full">
      <form onSubmit={(e) => { e.preventDefault(); run(v); }}
        className="flex w-full items-center gap-4 rounded-[26px] glass glass-hi px-5 py-4">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl glass-2">
          <RelayMark className="h-4 w-4 text-white" />
        </span>
        <div className="relative flex-1">
          <input
            ref={input}
            value={v}
            onChange={(e) => change(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={(e) => { if (e.key === "Escape") clear(); }}
            aria-label="Search cases"
            className="w-full bg-transparent text-[15px] text-white outline-none"
          />
          {!v && !focused && (
            <div className="pointer-events-none absolute inset-0 flex items-center text-[15px] text-zinc-500">
              {shown}<span className="caret" />
            </div>
          )}
        </div>
        {v && (
          <button type="button" onClick={clear} aria-label="Clear" className="text-zinc-500 hover:text-white">
            <X size={16} />
          </button>
        )}
        <button type="submit" aria-label="Search"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-white text-black transition hover:bg-zinc-200">
          <ArrowUp size={18} strokeWidth={2.5} />
        </button>
      </form>

      {!v && (
        <div className="mt-3 flex flex-wrap justify-center gap-1.5">
          {EXAMPLES.map((x) => (
            <button key={x} onClick={() => pick(x)}
              className="num rounded-full glass-2 px-2.5 py-1 text-[12px] text-zinc-400 transition hover:text-white">{x}</button>
          ))}
        </div>
      )}

      {v && res && res.query === v.trim() && (
        <div className="mt-3 overflow-hidden rounded-2xl glass">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
            <span className="text-sm font-medium text-white">{res.summary}</span>
            {res.understood.length > 0 && (
              <span className="num text-[11px] text-zinc-500">read as: {res.understood.join(" · ")}</span>
            )}
            {busy && <span className="load-dots ml-auto"><i /><i /><i /></span>}
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            {res.hits.map((h, i) => (
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
                <span className="num shrink-0 text-[11px] text-zinc-600">
                  {new Date(h.s.received_at * 1000).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="num w-24 shrink-0 text-right text-[13px] text-zinc-300">
                  {h.s.chosen ? money(h.s.chosen.total, h.s.chosen.currency) : "—"}
                </span>
                <StatusChip status={h.s.status} />
              </Link>
            ))}
          </div>
          {res.total > res.hits.length && (
            <div className="border-t border-line px-4 py-2 text-[12px] text-zinc-500">
              Showing the newest {res.hits.length} of {res.total}. Add a word to narrow it down.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
