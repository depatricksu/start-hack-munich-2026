"use client";
// Bell and pop-ups, top right on every page. lib/notifications.ts decides what is big enough to show up here.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Bell, TriangleAlert, X } from "lucide-react";
import type { Notice } from "@/lib/notification-types";

const SEEN_KEY = "relay.notifications.seen";
const POP_MAX_AGE_S = 15 * 60; // older problems wait in the bell when the page opens
const POP_MAX = 3;

function readSeen(): string[] {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]");
    return Array.isArray(v) ? v.map(String) : [];
  } catch { return []; }
}

function age(s: number) {
  if (s < 60) return "now";
  return s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h`;
}

function Body({ n, now }: { n: Notice; now: number }) {
  const red = n.severity === "critical";
  return (
    <div className="flex gap-3">
      <TriangleAlert size={18} aria-hidden className={`mt-0.5 shrink-0 ${red ? "text-red-400" : "text-amber-300"}`} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 pr-5">
          <span className="text-sm font-semibold text-white">{n.title}</span>
          {n.simulated && <span className="num rounded border border-white/20 px-1 text-[10px] uppercase text-zinc-300">Simulation</span>}
          <span className="num ml-auto shrink-0 text-[11px] text-zinc-500">{age(now - n.ts)}</span>
        </div>
        <div className="num mt-0.5 truncate text-[11px] text-zinc-400">{n.context}</div>
        <p className="mt-1.5 line-clamp-3 break-words text-[13px] leading-snug text-zinc-300">{n.detail}</p>
        <div className={`mt-2 text-xs font-medium ${red ? "text-red-300" : "text-amber-200"}`}>{n.action} →</div>
      </div>
    </div>
  );
}

export function Notifications() {
  const [items, setItems] = useState<Notice[]>([]);
  const [seen, setSeen] = useState<string[]>([]);
  const [pop, setPop] = useState<string[]>([]);
  const [now, setNow] = useState(0);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    let alive = true;
    const known = new Set<string>();
    const load = () => fetch("/api/notifications", { cache: "no-store" }).then((r) => r.json())
      .then((d: { notifications?: Notice[] }) => {
        if (!alive || !d.notifications) return;
        const t = Date.now() / 1000, read = readSeen();
        const fresh = d.notifications.filter((n) => !known.has(n.id) && !read.includes(n.id) && t - n.ts < POP_MAX_AGE_S).map((n) => n.id);
        d.notifications.forEach((n) => known.add(n.id));
        setItems(d.notifications);
        setSeen(read);
        setNow(t);
        if (fresh.length) setPop((p) => [...new Set([...fresh, ...p])]);
      }).catch(() => {});
    load();
    const timer = setInterval(load, 3000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const down = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("keydown", key);
    document.addEventListener("pointerdown", down);
    return () => { document.removeEventListener("keydown", key); document.removeEventListener("pointerdown", down); };
  }, [open]);

  function markRead(ids: string[]) {
    const next = [...new Set([...readSeen(), ...ids])].slice(-500);
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(next)); } catch { /* private window: read for this view only */ }
    setSeen(next);
    setPop((p) => p.filter((id) => !ids.includes(id)));
  }

  const unread = items.filter((n) => !seen.includes(n.id));
  const toasts = open ? [] : unread.filter((n) => pop.includes(n.id)).slice(0, POP_MAX);

  return (
    <div ref={box} className="relative z-50 flex h-12 shrink-0 items-center justify-end px-3">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open}
        aria-label={`Notifications, ${unread.length} unread`}
        className="relative flex h-9 w-9 items-center justify-center rounded-xl glass text-zinc-300 hover:text-white">
        <Bell size={17} aria-hidden />
        {unread.length > 0 && (
          <span className="num absolute -right-1 -top-1 min-w-4 rounded-full bg-red-500 px-1 text-center text-[10px] font-semibold leading-4 text-white">
            {unread.length > 9 ? "9+" : unread.length}
          </span>
        )}
      </button>

      {open && (
        <section aria-label="Notifications"
          className="absolute right-3 top-12 w-[380px] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-2xl border border-white/10 bg-[#141518] shadow-2xl">
          <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
            <h2 className="text-sm font-semibold text-white">Big problems <span className="font-normal text-zinc-500">last 24 h</span></h2>
            {unread.length > 0 && (
              <button onClick={() => markRead(unread.map((n) => n.id))} className="text-xs text-zinc-400 hover:text-white">Mark all read</button>
            )}
          </div>
          <div className="rail max-h-[70vh] overflow-y-auto">
            {items.length === 0 && <p className="px-4 py-8 text-center text-sm text-zinc-500">Nothing needs you.</p>}
            {items.map((n) => (
              <Link key={n.id} href={n.href} onClick={() => { markRead([n.id]); setOpen(false); }}
                className={`block border-b border-white/5 p-4 hover:bg-white/5 ${seen.includes(n.id) ? "opacity-50" : ""}`}>
                <Body n={n} now={now} />
              </Link>
            ))}
          </div>
        </section>
      )}

      <div aria-live="assertive" className="pointer-events-none absolute right-3 top-12 flex w-[380px] max-w-[calc(100vw-1.5rem)] flex-col gap-2">
        <AnimatePresence initial={false}>
          {toasts.map((n) => (
            <motion.div key={n.id} role="alert"
              initial={reduce ? false : { opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: reduce ? 0 : 40 }}
              className={`pointer-events-auto relative rounded-2xl border bg-[#141518] shadow-2xl ${n.severity === "critical" ? "border-red-500/50" : "border-amber-400/40"}`}>
              <Link href={n.href} onClick={() => markRead([n.id])} className="block p-4"><Body n={n} now={now} /></Link>
              <button onClick={() => markRead([n.id])} aria-label={`Dismiss: ${n.title}`}
                className="absolute right-2 top-2 rounded-md p-1 text-zinc-500 hover:text-white"><X size={14} aria-hidden /></button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
