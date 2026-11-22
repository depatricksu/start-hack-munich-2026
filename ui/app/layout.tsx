import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Notifications } from "@/components/notifications";
import { Sidebar } from "@/components/sidebar";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Relay — Freight ops",
  description: "Autonomous air forwarder: live overview, requests, take-over and score.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="h-full">
        <div className="flex h-full">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <Notifications />
            <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
