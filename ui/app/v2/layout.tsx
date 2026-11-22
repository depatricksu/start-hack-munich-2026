import { Shell } from "@/components/v2/shell";

export const metadata = { title: "Relay" };

// Relay v2: cleaner frame next to the first version (which stays at /, /dashboard, /requests, ...).
export default function V2Layout({ children }: { children: React.ReactNode }) {
  return <Shell>{children}</Shell>;
}
