import Link from "next/link";
import { AskRelay } from "@/components/ask-relay";
import { StatusChip } from "@/components/bits";
import { getSessions } from "@/lib/data";
import { QUOTE_SENT, Session } from "@/lib/types";

export const dynamic = "force-dynamic";

function eur(n: number) {
  return `€${n.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
}
function priceOf(s: Session) {
  return s.chosen ? Number(s.chosen.total_eur || 0) : 0;
}

// One size for every tile, so the four numbers line up.
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl glass px-5 py-4">
      <div className="num text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="num mt-1.5 whitespace-nowrap text-xl font-semibold tracking-tight text-white">{value}</div>
    </div>
  );
}

// Ask Relay: the question box, with the key numbers and the latest quotes under it (gone once you ask).
export default function AskRelayPage() {
  const { sessions } = getSessions();
  const quotes = sessions.filter((x) => x.chosen && QUOTE_SENT.includes(x.status));
  const sold = quotes.length;
  const revenue = quotes.reduce((a, x) => a + priceOf(x), 0);
  const customers = new Set(sessions.map((x) => x.customer.toLowerCase())).size;
  const latest = (quotes.length ? quotes : sessions).slice(0, 4);

  return (
    <div className="h-full p-2">
      <div className="h-full overflow-hidden rounded-2xl glass glass-hi">
        <AskRelay>
          <div className="mt-10 grid grid-cols-4 gap-3">
            <Stat label="Quotes sold" value={String(sold)} />
            <Stat label="Avg / quote" value={sold ? eur(revenue / sold) : "—"} />
            <Stat label="Customers" value={String(customers)} />
            <Stat label="Revenue" value={eur(revenue)} />
          </div>
          <div className="mt-8">
            <div className="mb-2 flex items-center justify-between px-1">
              <span className="num text-[11px] uppercase tracking-wider text-zinc-500">Latest quotes</span>
              <Link href="/requests" className="text-xs text-zinc-400 hover:text-white">View all</Link>
            </div>
            <div className="overflow-hidden rounded-2xl glass">
              {latest.map((r, i) => (
                <Link key={r.thread_id} href={`/requests?id=${r.thread_id}`}
                  className={`flex items-center gap-3 px-4 py-3 transition hover:bg-white/5 ${i > 0 ? "border-t border-line" : ""}`}>
                  <span className="num text-sm font-medium text-white">{r.fields.origin ?? "???"} <span className="text-zinc-600">→</span> {r.fields.destination ?? "???"}</span>
                  <span className="flex-1 truncate text-sm text-zinc-500">{r.customer}</span>
                  {r.chosen && <span className="num text-sm text-zinc-300">{eur(priceOf(r))}</span>}
                  <StatusChip status={r.status} />
                </Link>
              ))}
            </div>
          </div>
        </AskRelay>
      </div>
    </div>
  );
}
