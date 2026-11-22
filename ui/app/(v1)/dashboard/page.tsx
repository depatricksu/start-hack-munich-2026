import { getDashboard } from "@/lib/dashboard";
import { DashboardView } from "@/components/dash";

export const dynamic = "force-dynamic";

// Forwarder dashboard: queue, live activity, shipments, pricing, carriers, customers. Data: lib/dashboard.ts.
export default function DashboardPage() {
  return <DashboardView initial={getDashboard()} />;
}
