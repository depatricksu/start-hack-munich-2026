"use client";
// Relay v2 frame: one slim top bar with the five places, a live status on the right, the page below.
// Top tabs instead of a sidebar give the three-pane Requests screen the full width.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { MotionConfig, motion } from "motion/react";
import { RelayMark } from "@/components/logo";
import { EASE, SPRING, ago, useJson, useNow } from "@/components/v2/ui";
import type { Session } from "@/lib/types";

const NAV = [
  { href: "/v2", label: "Overview" },
  { href: "/v2/ask", label: "Ask Relay" },
  { href: "/v2/requests", label: "Requests" },
  { href: "/v2/shipments", label: "Shipments" },
  { href: "/v2/invoices", label: "Invoices" },
];

function active(path: string, href: string) {
  return href === "/v2" ? path === "/v2" : path.startsWith(href);
}

function Status() {
  const d = useJson<{ sessions?: Session[] }>("/api/sessions", 4000);
  const need = d?.sessions?.filter((s) => s.status === "needs_human" || s.status === "failed").length ?? 0;
  const now = useNow(15000);
  if (!d) return null; // nothing on the server render: the count arrives with the first poll
  // Honest status from the data itself: "Live" only when a mail came in during the last 10 minutes.
  const last = Math.max(0, ...(d.sessions ?? []).map((s) => s.received_at));
  const live = last > 0 && now - last < 600;
  return (
    <div className="flex items-center gap-2">
      <Link href="/v2/requests?filter=need"
        className={`inline-flex h-7 items-center gap-2 rounded-full border px-3 text-[12px] font-medium transition-colors ${need
          ? "border-transparent bg-[var(--warn-soft)] text-[var(--warn)]"
          : "border-[var(--hair-2)] text-[var(--fg-3)] hover:text-[var(--fg-2)]"}`}>
        {need ? `${need} need${need === 1 ? "s" : ""} you` : "Nothing needs you"}
      </Link>
      <span className="inline-flex h-7 items-center gap-2 rounded-full border border-[var(--hair-2)] px-3 text-[12px] text-[var(--fg-2)]">
        <span className="relative flex h-1.5 w-1.5">
          {live && <span className="absolute inset-0 animate-ping rounded-full bg-[var(--ok)] opacity-60 motion-reduce:hidden" />}
          <span className={`relative h-1.5 w-1.5 rounded-full ${live ? "bg-[var(--ok)]" : "bg-[var(--fg-3)]"}`} />
        </span>
        {last ? (live ? "Live" : `Last mail ${ago(now - last)} ago`) : "No mail yet"}
      </span>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  return (
    <MotionConfig reducedMotion="user">
      <div className="v2 flex h-full flex-col">
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-6 border-b border-[var(--hair)] bg-[var(--bg)]/85 px-5 backdrop-blur-md">
          <Link href="/v2" className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-[var(--fg)] text-[#0a0a0a]"><RelayMark className="h-4 w-4" /></span>
            <span className="text-[15px] font-semibold tracking-[-0.02em]">Relay</span>
          </Link>
          <nav className="flex h-full items-center gap-1">
            {NAV.map((n) => {
              const on = active(path, n.href);
              return (
                <Link key={n.href} href={n.href}
                  className={`relative flex h-full items-center px-3 text-[14px] transition-colors ${on ? "text-[var(--fg)]" : "text-[var(--fg-3)] hover:text-[var(--fg-2)]"}`}>
                  {n.label}
                  {on && <motion.span layoutId="v2-nav" transition={SPRING} className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-[var(--fg)]" />}
                </Link>
              );
            })}
          </nav>
          <span className="flex-1" />
          <Status />
          <Link href="/dashboard" className="text-[12px] text-[var(--fg-3)] transition-colors hover:text-[var(--fg-2)]">Classic view</Link>
        </header>
        {/* Each screen fades and rises in a little when you switch to it. */}
        <motion.main key={path} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: EASE }}
          className="min-h-0 flex-1 overflow-hidden">
          {children}
        </motion.main>
      </div>
    </MotionConfig>
  );
}
