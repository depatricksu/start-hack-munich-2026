import { Sidebar } from "@/components/sidebar";

// The first version (glass, sidebar). Its start page, requests, shipments and invoices now open Relay v2
// (redirects in next.config.ts); carriers, workflow, dashboard and score are still served from here.
export default function V1Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}
