import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Forwarder Control Room",
  description: "Live view of the autonomous air forwarder: sessions, takeover, score.",
};

const NAV = [
  { href: "/", label: "Sessions" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/score", label: "Score" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="h-full flex flex-col">
        <header className="flex items-center gap-6 border-b border-line bg-surface px-6 h-14 shrink-0">
          <div className="flex items-center gap-2.5 font-semibold tracking-tight">
            <span className="relative flex h-2.5 w-2.5">
              <span className="live-dot absolute inline-flex h-full w-full rounded-full bg-emerald-500" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
            </span>
            Forwarder Control Room
          </div>
          <nav className="flex gap-1 text-sm">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className="rounded-md px-3 py-1.5 text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900">
                {n.label}
              </Link>
            ))}
          </nav>
          <span className="ml-auto num text-xs text-zinc-400">autonomous air forwarder · 5U</span>
        </header>
        <main className="flex-1 min-h-0">{children}</main>
      </body>
    </html>
  );
}
