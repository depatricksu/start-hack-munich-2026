"use client";
// Relay v2 Requests: the queue on the left, one request in the middle, its steps and the manual answer on the right.
// /v2/requests?id=123 opens a request, ?filter=need opens the "Marked" filter. useSearchParams needs Suspense.
import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { motion } from "motion/react";
import { EASE, route, useJson } from "@/components/v2/ui";
import { Filter, groupOf } from "@/components/v2/requests-data";
import { RequestList } from "@/components/v2/requests-list";
import { DetailSkeleton, RequestDetail } from "@/components/v2/requests-detail";
import { RequestSide, SideSkeleton } from "@/components/v2/requests-side";
import type { Session, SessionDetail } from "@/lib/types";

const FILTERS: Filter[] = ["all", "need", "live", "done"];

export default function RequestsPage() {
  return <Suspense fallback={null}><RequestsView /></Suspense>;
}

function RequestsView() {
  const params = useSearchParams();
  const urlId = Number(params.get("id")) || null;
  const urlFilter = params.get("filter") as Filter | null;
  const [filter, setFilter] = useState<Filter>(urlFilter && FILTERS.includes(urlFilter) ? urlFilter : "all");
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState<number | null>(null);

  const list = useJson<{ sessions: Session[] }>("/api/sessions", 3000);
  const sessions = useMemo(() => (list ? [...list.sessions].sort((a, b) => b.received_at - a.received_at) : null), [list]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, need: 0, live: 0, done: 0 };
    for (const s of sessions ?? []) { c.all++; c[groupOf(s)]++; }
    return c;
  }, [sessions]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/^#/, "");
    return (sessions ?? []).filter((s) => {
      if (filter !== "all" && groupOf(s) !== filter) return false;
      if (!q) return true;
      const hay = `${s.thread_id} ${s.customer} ${route(s.fields.origin, s.fields.destination)} ${s.fields.origin ?? ""}${s.fields.destination ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [sessions, filter, query]);

  const exists = (id: number | null) => id != null && !!sessions?.some((s) => s.thread_id === id);
  const activeId = (exists(sel) ? sel : null) ?? (exists(urlId) ? urlId : null) ?? rows[0]?.thread_id ?? sessions?.[0]?.thread_id ?? null;

  const detail = useJson<{ session: SessionDetail | null }>(activeId ? `/api/sessions/${activeId}` : null, 2000);
  // Until the new request's data arrives, the old one stays; the panes fade in once it is there.
  const d = detail?.session ?? null;
  const loading = !sessions || (activeId != null && !detail);

  return (
    <div className="flex h-full">
      <RequestList sessions={sessions} rows={rows} filter={filter} setFilter={setFilter} counts={counts}
        query={query} setQuery={setQuery} activeId={activeId} onSelect={setSel} />

      {loading ? (
        <>
          <section className="min-w-0 flex-1 overflow-hidden"><DetailSkeleton /></section>
          <aside className="w-[340px] shrink-0 border-l border-[var(--hair)]"><SideSkeleton /></aside>
        </>
      ) : !d ? (
        <section className="flex min-w-0 flex-1 items-center justify-center">
          <p className="text-[14px] text-[var(--fg-2)]">{sessions && sessions.length ? "This request could not be found." : "No requests yet. New mail shows up here by itself."}</p>
        </section>
      ) : (
        <>
          <motion.section key={`c${d.thread_id}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: EASE }}
            className="scroll-thin min-w-0 flex-1 overflow-y-auto">
            <RequestDetail d={d} />
          </motion.section>
          <motion.aside key={`s${d.thread_id}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3, ease: EASE, delay: 0.04 }}
            className="scroll-thin w-[340px] shrink-0 overflow-y-auto border-l border-[var(--hair)]">
            <RequestSide d={d} />
          </motion.aside>
        </>
      )}
    </div>
  );
}
