"use client";
// Relay v2 Shipments: everything after the customer said yes. List on the left, one shipment on the right.
import { Suspense, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import type { ShipmentDetail, ShipmentsData } from "@/lib/shipments";
import { Card, CountUp, EASE, Item, PageHead, Reveal, SPRING, Skeleton, day, route, shortMail, useJson } from "@/components/v2/ui";
import { Detail, DetailSkeleton, Kpi, ShipBadge, Strip } from "@/components/v2/shipments-parts";

export default function ShipmentsPage() {
  return <Suspense fallback={null}><ShipmentsView /></Suspense>;
}

function Loading() {
  return (
    <div className="mx-auto max-w-[1440px] space-y-6 px-6 py-8">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-4 gap-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[112px]" />)}</div>
      <div className="grid grid-cols-[380px_minmax(0,1fr)] gap-4"><Skeleton className="h-[480px]" /><DetailSkeleton /></div>
    </div>
  );
}

function ShipmentsView() {
  const router = useRouter();
  const urlId = Number(useSearchParams().get("id")) || null;
  const data = useJson<ShipmentsData>("/api/shipments", 10000);
  const rows = useMemo(() => [...(data?.rows ?? [])].sort((a, b) => b.at - a.at), [data]);
  const activeId = urlId ?? rows[0]?.thread ?? null;
  const raw = useJson<{ shipment: ShipmentDetail | null }>(activeId ? `/api/shipments/${activeId}` : null, 10000);
  // useJson keeps the last answer while the next id loads: only trust it when it is for the selected shipment.
  const detail = raw && (raw.shipment ? raw.shipment.thread === activeId : true) ? raw : null;

  if (!data) return <div className="h-full overflow-y-auto scroll-thin"><Loading /></div>;
  if (!data.available || rows.length === 0) {
    return (
      <div className="mx-auto max-w-[1440px] px-6 py-8">
        <PageHead title="Shipments" sub="Everything after the customer said yes." />
        <Card className="mt-6"><p className="text-[14px] text-[var(--fg-2)]">No bookings yet. A shipment shows here once a customer says yes and we book the flight.</p></Card>
      </div>
    );
  }
  const t = data.totals;

  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <Reveal className="mx-auto max-w-[1440px] space-y-6 px-6 py-8">
        <Item><PageHead title="Shipments" sub="Everything after the customer said yes." /></Item>

        <div className="grid grid-cols-4 gap-4">
          <Item><Kpi label="Active shipments" sub={t.cancelled ? `${t.cancelled} cancelled` : "Booked or confirmed"}><CountUp value={t.active} /></Kpi></Item>
          <Item><Kpi label="Waiting for airline" sub="Booked, not confirmed yet"><CountUp value={t.waiting} /></Kpi></Item>
          <Item>
            <Kpi label="Customer informed" sub="Told about their booking by Relay" tone={t.informed ? "text-[var(--ok)]" : undefined}>
              <CountUp value={t.informed} /><span className="tnum text-[var(--fg-3)]"> / </span><CountUp value={t.active} className="text-[var(--fg-2)]" />
            </Kpi>
          </Item>
          <Item>
            <Kpi label="Invoiced / paid" sub="Invoices written, invoices paid">
              <CountUp value={t.invoiced} /><span className="tnum text-[var(--fg-3)]"> / </span><CountUp value={t.paid} />
            </Kpi>
          </Item>
        </div>

        <div className="grid grid-cols-[380px_minmax(0,1fr)] items-start gap-4">
          <Item className="sticky top-4">
            <Card pad={false} className="flex max-h-[calc(100vh-56px-32px)] flex-col overflow-hidden">
              <div className="flex items-center border-b border-[var(--hair)] px-4 py-3">
                <span className="eyebrow">Newest first</span>
                <span className="flex-1" />
                <span className="tnum text-[12px] text-[var(--fg-3)]">{rows.length}</span>
              </div>
              <ul className="min-h-0 flex-1 overflow-y-auto p-1.5 scroll-thin">
                {rows.map((r) => {
                  const on = r.thread === activeId;
                  return (
                    <li key={r.thread}>
                      <button onClick={() => router.replace(`/v2/shipments?id=${r.thread}`, { scroll: false })} aria-current={on || undefined}
                        className={`relative block w-full rounded-md px-3 py-2.5 text-left transition-colors duration-150 ${on ? "" : "hover:bg-[var(--bg-2)]"}`}>
                        {on && <motion.span layoutId="ship-sel" transition={SPRING} className="absolute inset-0 rounded-md bg-[var(--bg-3)]" />}
                        <span className="relative block">
                          <span className="flex items-center gap-2">
                            <span className="tnum text-[13px] text-[var(--fg)]">{r.booking_ref ?? r.ref}</span>
                            <span className="tnum truncate text-[13px] text-[var(--fg-2)]">{route(r.origin, r.destination)}</span>
                            {r.flag && <span title="Carrier to watch" className={`h-1.5 w-1.5 shrink-0 rounded-full ${r.flag === "red" ? "bg-[var(--bad)]" : "bg-[var(--warn)]"}`} />}
                            <span className="flex-1" />
                            <ShipBadge status={r.status} />
                          </span>
                          <span className="mt-1 flex items-center gap-2 text-[13px] text-[var(--fg-3)]">
                            <span className="truncate text-[var(--fg-2)]">{shortMail(r.customer)}</span>
                            <span className="truncate">{r.airline ?? "No airline"}</span>
                            <span className="flex-1" />
                            <span className="tnum shrink-0 text-[12px]">{day(r.at)}</span>
                          </span>
                          <span className="mt-2 block"><Strip r={r} /></span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Card>
          </Item>

          <Item className="min-w-0">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={activeId ?? "none"} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.2, ease: EASE }}>
                {detail?.shipment ? <Detail d={detail.shipment} />
                  : detail ? <Card><p className="text-[14px] text-[var(--fg-2)]">No shipment with this number.</p></Card>
                  : <DetailSkeleton />}
              </motion.div>
            </AnimatePresence>
          </Item>
        </div>
      </Reveal>
    </div>
  );
}
