import { Shell } from "@/components/v2/shell";

export const metadata = { title: "Relay" };

// Relay v2: the product interface. /, /requests, /shipments and /invoices redirect here (next.config.ts);
// the first version keeps only the screens v2 does not have yet (/carriers, /workflow, /dashboard, /score).
export default function V2Layout({ children }: { children: React.ReactNode }) {
  return <Shell>{children}</Shell>;
}
