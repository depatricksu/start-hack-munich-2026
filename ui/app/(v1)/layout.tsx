import { Sidebar } from "@/components/sidebar";

// The first version (glass, sidebar). Kept as it is; the new version lives under /v2.
export default function V1Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}
