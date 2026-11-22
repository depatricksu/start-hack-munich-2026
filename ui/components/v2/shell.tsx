"use client";
// Relay v2 frame: one floating glass bar with the five places, the live status and the bell; the page below.
// Top tabs instead of a sidebar give the three-pane Requests screen the full width.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ReactNode } from "react";
import { MotionConfig, motion } from "motion/react";
import { RelayMark } from "@/components/logo";
import { EASE, SPRING, ago, useJson, useNow } from "@/components/v2/ui";
import { Notifications } from "@/components/notifications";
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

// Honest status from the data itself: "Live" only when a mail came in during the last 10 minutes.
// Problems are not counted here any more: the bell next to it shows them.
function Status() {
  const d = useJson<{ sessions?: Session[] }>("/api/sessions", 4000);
  const now = useNow(15000);
  if (!d) return null; // nothing on the server render: it arrives with the first poll
  const last = Math.max(0, ...(d.sessions ?? []).map((s) => s.received_at));
  const live = last > 0 && now - last < 600;
  return (
    <span className="inline-flex h-8 items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 text-[12px] text-[var(--fg-2)]">
      <span className="relative flex h-1.5 w-1.5">
        {live && <span className="absolute inset-0 animate-ping rounded-full bg-[var(--ok)] opacity-60 motion-reduce:hidden" />}
        <span className={`relative h-1.5 w-1.5 rounded-full ${live ? "bg-[var(--ok)]" : "bg-[var(--fg-3)]"}`} />
      </span>
      {last ? (live ? "Live" : `Last mail ${ago(now - last)} ago`) : "No mail yet"}
    </span>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  return (
    <MotionConfig reducedMotion="user">
      <div className="v2 flex h-full flex-col">
        <header className="sticky top-0 z-20 shrink-0 px-4 pb-2 pt-3">
          <div className="lg mx-auto flex h-12 max-w-[1360px] items-center gap-3 rounded-full pl-2 pr-2.5">
            <Link href="/v2" className="flex items-center gap-2.5 pr-2">
              {/* The mark in its black version: white symbol on a black tile. */}
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-black text-white ring-1 ring-inset ring-white/15"><RelayMark className="h-4 w-4" /></span>
              <span className="text-[15px] font-semibold tracking-[-0.02em]">Relay</span>
            </Link>
            <nav className="flex items-center gap-0.5">
              {NAV.map((n) => {
                const on = active(path, n.href);
                return (
                  <Link key={n.href} href={n.href}
                    className={`relative flex h-8 items-center rounded-full px-3.5 text-[13px] transition-colors ${on ? "text-[var(--fg)]" : "text-[var(--fg-3)] hover:text-[var(--fg-2)]"}`}>
                    {on && <motion.span layoutId="v2-nav" transition={SPRING}
                      className="absolute inset-0 rounded-full border border-white/10 bg-white/[0.09] shadow-[inset_0_1px_0_rgba(255,255,255,0.18)]" />}
                    <span className="relative">{n.label}</span>
                  </Link>
                );
              })}
            </nav>
            <span className="flex-1" />
            <Status />
            <Notifications inline />
          </div>
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
