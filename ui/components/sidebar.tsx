"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { Inbox, LayoutGrid, X } from "lucide-react";
import { RelayMark, SidebarToggleIcon } from "@/components/logo";
import { Session } from "@/lib/types";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutGrid },
  { href: "/requests", label: "Requests", icon: Inbox, badge: true },
];

function useNeed(): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    let alive = true;
    const load = () => fetch("/api/sessions", { cache: "no-store" }).then((r) => r.json())
      .then((d: { sessions?: Session[] }) => {
        if (!alive || !d.sessions) return;
        setN(d.sessions.filter((s) => s.status === "needs_human" || s.status === "failed").length);
      }).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return n;
}

function Field({ label, type, value, onChange }: { label: string; type: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="num text-[11px] uppercase tracking-wider text-zinc-500">{label}</span>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg glass-2 px-3 py-2 text-sm text-white outline-none focus:ring-1 focus:ring-white/30" />
    </label>
  );
}

function AccountPanel({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("Relay ops");
  const [email, setEmail] = useState("ops@relay.freight");
  const [pwd, setPwd] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    try {
      const a = JSON.parse(localStorage.getItem("relay.account") || "{}");
      if (a.name) setName(a.name);
      if (a.email) setEmail(a.email);
    } catch {}
  }, []);
  const save = () => {
    localStorage.setItem("relay.account", JSON.stringify({ name, email }));
    setSaved(true);
    setTimeout(() => setSaved(false), 1400);
  };
  return (
    <div className="absolute bottom-[4.5rem] left-2 right-2 z-50 rounded-2xl glass glass-hi p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-white">Account</span>
        <button onClick={onClose} className="text-zinc-500 hover:text-white"><X size={16} /></button>
      </div>
      <div className="space-y-3">
        <Field label="Name" type="text" value={name} onChange={setName} />
        <Field label="Email" type="email" value={email} onChange={setEmail} />
        <Field label="Password" type="password" value={pwd} onChange={setPwd} />
      </div>
      <button onClick={save} className="mt-4 w-full rounded-xl bg-white py-2 text-sm font-semibold text-black transition hover:bg-zinc-200">
        {saved ? "Saved" : "Save"}
      </button>
    </div>
  );
}

export function Sidebar() {
  const path = usePathname();
  const need = useNeed();
  const [open, setOpen] = useState(true);
  const [acct, setAcct] = useState(false);
  useEffect(() => { setOpen(localStorage.getItem("relay.nav") !== "closed"); }, []);
  const toggle = () => setOpen((o) => { localStorage.setItem("relay.nav", o ? "closed" : "open"); return !o; });
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <aside className={`relative m-2 flex shrink-0 flex-col rounded-2xl glass glass-hi p-2.5 transition-all duration-300 ${open ? "w-[224px]" : "w-[72px]"}`}>
      {/* open: logo left, toggle far right. collapsed: logo hidden, toggle takes its place. */}
      <div className={`flex items-center ${open ? "justify-between" : "justify-center"}`}>
        {open && (
          <Link href="/" className="flex items-center gap-2.5 rounded-xl px-2 py-1.5 transition hover:bg-white/5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl glass-2">
              <RelayMark className="h-5 w-5 text-white" />
            </span>
            <span className="text-[15px] font-semibold tracking-tight">Relay</span>
          </Link>
        )}
        <button onClick={toggle} title={open ? "Collapse sidebar" : "Expand sidebar"}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl glass-2 text-zinc-200 transition hover:bg-white/10 hover:text-white">
          <SidebarToggleIcon className="h-[18px] w-[18px]" />
        </button>
      </div>

      <nav className="mt-5 space-y-1">
        {NAV.map((n) => {
          const active = isActive(n.href);
          return (
            <Link key={n.label} href={n.href} title={n.label}
              className={`relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors ${open ? "" : "justify-center px-0"} ${active ? "font-medium text-white" : "text-zinc-400 hover:bg-white/5 hover:text-white"}`}>
              {active && (
                <motion.span layoutId="nav-active" transition={{ type: "spring", stiffness: 420, damping: 36 }}
                  className="absolute inset-0 rounded-xl glass-2" />
              )}
              <span className="relative z-10">
                <n.icon size={18} strokeWidth={2} className={active ? "text-white" : "text-zinc-500"} />
                {n.badge && need > 0 && !open && <span className="absolute -right-1.5 -top-1.5 h-2 w-2 rounded-full bg-red-500" />}
              </span>
              {open && <span className="relative z-10 flex-1">{n.label}</span>}
              {open && n.badge && need > 0 && <span className="relative z-10 num rounded-full bg-red-500/90 px-1.5 text-[11px] font-semibold text-white">{need}</span>}
            </Link>
          );
        })}
      </nav>

      {acct && <AccountPanel onClose={() => setAcct(false)} />}

      {/* clickable account */}
      <button onClick={() => setAcct((o) => !o)}
        className={`mt-auto flex items-center gap-2.5 rounded-xl px-2 py-2 text-left transition hover:bg-white/5 ${acct ? "glass-2" : ""} ${open ? "" : "justify-center px-0"}`}>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full glass-2 text-sm font-semibold text-white">R</span>
        {open && (
          <div className="flex-1 leading-tight">
            <div className="text-sm font-medium">Relay ops</div>
            <div className="text-xs text-zinc-500">View account</div>
          </div>
        )}
      </button>
    </aside>
  );
}
