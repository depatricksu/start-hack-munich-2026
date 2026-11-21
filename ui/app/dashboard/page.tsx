import { computeStats, getSessions } from "@/lib/data";
import { StatusChip } from "@/components/bits";

export const dynamic = "force-dynamic";

function money(total: string, currency = "EUR") {
  return `${Number(total).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bad" | "good" }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      <div className="text-[11px] uppercase tracking-wide text-zinc-400">{label}</div>
      <div className={`num mt-1 text-4xl font-semibold tracking-tight ${tone === "bad" ? "text-red-600" : tone === "good" ? "text-emerald-700" : ""}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-zinc-500">{hint}</div>}
    </div>
  );
}

export default function Dashboard() {
  const { source, sessions } = getSessions();
  const s = computeStats(sessions);
  const med = s.median_response_s;
  const rows = sessions.slice(0, 12);
  const max = Math.max(360, ...s.response_times);
  const underTime = s.response_times.filter((t) => t <= 120).length;
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-0.5 text-sm text-zinc-500">Scored per quote: price 45 · LLM cost 40 · time 15.</p>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ring-1 ring-inset ${source === "live" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200"}`}>
          <span className={`inline-block h-1.5 w-1.5 rounded-full ${source === "live" ? "live-dot bg-emerald-500" : "bg-amber-500"}`} />
          {source === "live" ? "Live" : "Demo"}</span>
      </div>
      <div className="grid grid-cols-4 gap-4">
        <Kpi label="Quotes sent" value={String(s.quoted)} hint={`of ${s.total} requests`} />
        <Kpi label="Needs human" value={String(s.needs_human)} tone={s.needs_human ? "bad" : "good"} hint={s.open ? `${s.open} still in flight` : "none waiting"} />
        <Kpi label="Median response" value={med == null ? "—" : `${Math.round(med)}s`} tone={med != null && med <= 120 ? "good" : med != null ? "bad" : undefined} hint={s.quoted ? `${underTime}/${s.quoted} under 120 s` : "full under 120 s"} />
        <Kpi label="LLM cost / quote" value={s.cost_per_quote_usd == null ? "—" : `$${s.cost_per_quote_usd.toFixed(5)}`} tone={s.cost_per_quote_usd != null && s.cost_per_quote_usd < 0.1 ? "good" : undefined} hint="zero points at $0.10" />
      </div>
      <section className="rounded-xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold">Response time per quote <span className="num font-normal text-zinc-400">target &lt; 120 s</span></h2>
        {s.response_times.length === 0 ? <p className="text-sm text-zinc-500">No quotes yet.</p> : (
          <div className="space-y-1.5">
            {s.response_times.map((t, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="num w-12 text-right text-xs text-zinc-500">{Math.round(t)}s</span>
                <div className="relative h-2.5 flex-1 rounded-full bg-zinc-100">
                  <div className="absolute inset-y-0 border-r border-dashed border-zinc-300" style={{ left: `${(120 / max) * 100}%` }} />
                  <div className={`h-2.5 rounded-full ${t <= 120 ? "bg-emerald-500" : t <= 240 ? "bg-amber-400" : "bg-red-500"}`} style={{ width: `${Math.min(100, (t / max) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="rounded-xl border border-line bg-surface p-5">
        <h2 className="mb-3 text-sm font-semibold">Latest requests</h2>
        <table className="w-full text-sm">
          <thead><tr className="text-left text-[11px] uppercase tracking-wide text-zinc-400"><th className="py-1 font-medium">Route</th><th className="font-medium">Customer</th><th className="font-medium">Status</th><th className="text-right font-medium">Quote</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.thread_id} className="border-t border-zinc-100">
              <td className="num py-2">{r.fields.origin ?? "?"} → {r.fields.destination ?? "?"}</td>
              <td className="text-zinc-600">{r.customer}</td>
              <td><StatusChip status={r.status} /></td>
              <td className="num text-right">{r.chosen ? money(r.chosen.total, r.chosen.currency) : "—"}</td>
            </tr>))}</tbody>
        </table>
      </section>
    </div>
  );
}
