import { Overview } from "@/components/v2/overview";
import { getDashboard } from "@/lib/dashboard";
import { getExceptions } from "@/lib/exceptions";
import { computeStats, getSessions } from "@/lib/data";

export const dynamic = "force-dynamic";

// Relay v2 Overview. First paint from the server; the page then polls /api/dashboard and /api/exceptions.
export default function OverviewPage() {
  const stats = computeStats(getSessions().sessions);
  return <Overview initial={getDashboard()} initialOff={getExceptions()} quoteSeconds={stats.median_response_s} />;
}
