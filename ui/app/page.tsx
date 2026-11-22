import Link from "next/link";
import { computeStats, getSessions } from "@/lib/data";
import { CommandBar } from "@/components/command-bar";
import { StatusChip } from "@/components/bits";
import { QUOTE_SENT, Session } from "@/lib/types";

export const dynamic = "force-dynamic";

function eur(n: number) {
  return `€${n.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
}
function priceOf(s: Session) {
  return s.chosen ? Number(s.chosen.total_eur || 0) : 0;
}

function Stat({ label, value }: { label: string; value: string }) {
  // Values vary a lot in length (0 vs €356,266). Scale the type down so long numbers stay inside the tile.
  const len = value.replace(/\s/g, "").length;
  const size = len > 9 ? "text-lg" : len > 7 ? "text-xl" : len > 5 ? "text-2xl" : "text-3xl";
  return (
    <div className="rounded-2xl glass px-5 py-4">
      <div className="num text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`num mt-1.5 ${size} font-semibold tracking-tight text-white whitespace-nowrap`}>{value}</div>
    </div>
  );
}

export default function Dashboard() {
  const { sessions } = getSessions();
  const s = computeStats(sessions);
  const quotes = sessions.filter((x) => x.chosen && QUOTE_SENT.includes(x.status));
  const sold = quotes.length;
  const revenue = quotes.reduce((a, x) => a + priceOf(x), 0);
  const avgPrice = sold ? revenue / sold : 0;
  const avgResp = s.response_times.length ? Math.round(s.response_times.reduce((a, b) => a + b, 0) / s.response_times.length) : null;
  const latest = (quotes.length ? quotes : sessions).slice(0, 4);

  return (
    <div className="h-full p-2">
      <div className="h-full overflow-y-auto rounded-2xl glass glass-hi">
      <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center px-6 py-16">
        <div className="text-center">
          <h1 className="text-[2rem] font-semibold tracking-tight text-white">Ask Relay.</h1>
          <p className="mt-2 text-[15px] text-zinc-500">A quote, a status, or what needs you. In plain words.</p>
        </div>
        <div className="mt-6"><CommandBar /></div>

        <div className="mt-10 grid grid-cols-4 gap-3">
          <Stat label="Quotes sold" value={String(sold)} />
          <Stat label="Avg / quote" value={sold ? eur(avgPrice) : "—"} />
          <Stat label="Avg response" value={avgResp == null ? "—" : `${avgResp}s`} />
          <Stat label="Revenue" value={eur(revenue)} />
        </div>

        <div className="mt-8">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="num text-[11px] uppercase tracking-wider text-zinc-500">Latest quotes</span>
            <Link href="/requests" className="text-xs text-zinc-400 hover:text-white">View all</Link>
          </div>
          <div className="overflow-hidden rounded-2xl glass">
            {latest.map((r, i) => (
              <Link key={r.thread_id} href="/requests"
                className={`flex items-center gap-3 px-4 py-3 transition hover:bg-white/5 ${i > 0 ? "border-t border-line" : ""}`}>
                <span className="num text-sm font-medium text-white">{r.fields.origin ?? "???"} <span className="text-zinc-600">→</span> {r.fields.destination ?? "???"}</span>
                <span className="flex-1 truncate text-sm text-zinc-500">{r.customer}</span>
                {r.chosen && <span className="num text-sm text-zinc-300">{eur(priceOf(r))}</span>}
                <StatusChip status={r.status} />
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
    </div>
  );
}
