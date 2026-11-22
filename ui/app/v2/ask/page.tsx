import { Ask, type LatestRow } from "@/components/v2/ask";
import { getSessions } from "@/lib/data";
import { QUOTE_SENT, Session } from "@/lib/types";

export const dynamic = "force-dynamic";

const priceOf = (s: Session) => (s.chosen ? Number(s.chosen.total_eur || 0) : 0);

// Ask Relay: the question box, with the key numbers and the latest quotes under it (gone once you ask).
export default function AskPage() {
  const { sessions } = getSessions();
  const quotes = sessions.filter((x) => x.chosen && QUOTE_SENT.includes(x.status));
  const sold = quotes.length;
  const revenue = quotes.reduce((a, x) => a + priceOf(x), 0);
  const customers = new Set(sessions.map((x) => x.customer.toLowerCase())).size;
  const latest: LatestRow[] = (quotes.length ? quotes : sessions).slice(0, 4).map((r) => ({
    id: r.thread_id,
    origin: r.fields.origin ?? null,
    destination: r.fields.destination ?? null,
    customer: r.customer,
    price: r.chosen ? priceOf(r) : null,
    status: r.status,
  }));

  return <Ask stats={{ sold, avg: sold ? revenue / sold : 0, customers, revenue }} latest={latest} />;
}
