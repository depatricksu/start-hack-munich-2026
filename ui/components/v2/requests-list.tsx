"use client";
// Left pane of v2 Requests: filter, search and the queue, newest first.
import { AnimatePresence, motion } from "motion/react";
import { Search } from "lucide-react";
import { EASE, SPRING, Segmented, Skeleton, StatusBadge, ago, route, useNow } from "@/components/v2/ui";
import { Filter, customerName, priceShort } from "@/components/v2/requests-data";
import type { Session } from "@/lib/types";

function Row({ s, active, now, onClick }: { s: Session; active: boolean; now: number; onClick: () => void }) {
  return (
    <button onClick={onClick}
      className={`group relative w-full rounded-md px-3 py-2.5 text-left transition-colors duration-150 ${active ? "" : "hover:bg-[var(--bg-2)]"}`}>
      {active && <motion.span layoutId="v2-req-sel" transition={SPRING} className="absolute inset-0 rounded-md border border-[var(--hair-2)] bg-[var(--bg-3)]" />}
      <span className="relative block">
        <span className="flex items-baseline gap-2">
          <span className="tnum truncate text-[14px] font-medium text-[var(--fg)]">{route(s.fields.origin, s.fields.destination)}</span>
          <span className="flex-1" />
          <span className="tnum shrink-0 text-[13px] text-[var(--fg)]">{priceShort(s.chosen) || <span className="text-[var(--fg-3)]">no price</span>}</span>
        </span>
        <span className="mt-1 flex items-center gap-2">
          <span className="min-w-0 truncate text-[13px] text-[var(--fg-2)]">{customerName(s.customer)}</span>
          <span className="tnum shrink-0 text-[12px] text-[var(--fg-3)]">{ago(now - s.received_at)} ago</span>
          <span className="flex-1" />
          <StatusBadge status={s.status} />
        </span>
      </span>
    </button>
  );
}

export function RequestList({ sessions, rows, filter, setFilter, counts, query, setQuery, activeId, onSelect }: {
  sessions: Session[] | null; rows: Session[]; filter: Filter; setFilter: (f: Filter) => void;
  counts: Record<Filter, number>; query: string; setQuery: (q: string) => void;
  activeId: number | null; onSelect: (id: number) => void;
}) {
  const now = useNow(15000);
  return (
    <aside className="flex w-[344px] shrink-0 flex-col border-r border-[var(--hair)]">
      <div className="space-y-3 border-b border-[var(--hair)] px-4 pb-3 pt-4">
        <div className="flex items-baseline gap-2">
          <h1 className="text-[20px] font-semibold tracking-[-0.03em] text-[var(--fg)]">Requests</h1>
          {sessions && <span className="tnum text-[13px] text-[var(--fg-3)]">{sessions.length}</span>}
        </div>
        <div className="[&_button]:whitespace-nowrap [&_button]:px-1.5 [&>div]:flex [&>div]:w-full [&_button]:flex-1">
          <Segmented id="req-filter" value={filter} onChange={setFilter} options={[
            { value: "all", label: "All", count: counts.all },
            { value: "need", label: "Needs you", count: counts.need },
            { value: "live", label: "In flight", count: counts.live },
            { value: "done", label: "Done", count: counts.done },
          ]} />
        </div>
        <label className="flex h-8 items-center gap-2 rounded-md border border-[var(--hair-2)] bg-[var(--bg-1)] px-2.5 transition-colors focus-within:border-[var(--accent)]">
          <Search size={14} className="shrink-0 text-[var(--fg-3)]" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search route, customer or #id"
            className="h-full min-w-0 flex-1 bg-transparent text-[13px] text-[var(--fg)] outline-none focus-visible:outline-none placeholder:text-[var(--fg-3)]" />
        </label>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto p-2">
        {!sessions ? (
          <div className="space-y-1">
            {Array.from({ length: 9 }, (_, i) => (
              <div key={i} className="space-y-2 px-3 py-2.5">
                <div className="flex justify-between"><Skeleton className="h-4 w-28" /><Skeleton className="h-4 w-14" /></div>
                <div className="flex justify-between"><Skeleton className="h-3.5 w-36" /><Skeleton className="h-[22px] w-20 rounded-full" /></div>
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="px-3 py-6 text-[13px] text-[var(--fg-2)]">
            {query ? "No request matches this search." : filter === "need" ? "Nothing needs you right now." : filter === "live" ? "No request is being worked on right now." : "No requests yet."}
          </p>
        ) : (
          // Keyed on filter and search, so switching them swaps the list at once; only new mail slides in.
          <div key={`${filter}|${query}`} className="space-y-0.5">
            <AnimatePresence initial={false}>
              {rows.map((s) => (
                <motion.div key={s.thread_id} layout="position"
                  initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  transition={{ duration: 0.3, ease: EASE }}>
                  <Row s={s} active={s.thread_id === activeId} now={now} onClick={() => onSelect(s.thread_id)} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </aside>
  );
}
