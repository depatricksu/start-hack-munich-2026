import { computeStats, getSessions } from "@/lib/data";

export const dynamic = "force-dynamic";

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "bad" | "good" }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5">
      <div className="text-xs uppercase tracking-wide text-zinc-400">{label}</div>
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
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ring-inset ${source === "live" ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-amber-50 text-amber-800 ring-amber-200"}`}>
          {source === "live" ? "Live data" : "Demo data"}</span>
      </div>
      <div className="grid grid-cols-4 gap-4">
        <Kpi label="Quotes sent" value={String(s.quoted)} hint={`${s.total} requests in total`} />
        <Kpi label="Needs human" value={String(s.needs_human)} tone={s.needs_human ? "bad" : "good"} hint="hand over to a person" />
        <Kpi label="Median response" value={med == null ? "-" : `${Math.round(med)}s`} tone={med != null && med <= 120 ? "good" : undefined} hint="full points under 120 s" />
        <Kpi label="LLM cost per quote" value={s.cost_per_quote_usd == null ? "-" : `$${s.cost_per_quote_usd.toFixed(5)}`} hint="zero points at $0.10" />
      </div>
      <section className="rounded-xl border border-zinc-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold">Response time per quote</h2>
        {s.response_times.length === 0 ? <p className="text-sm text-zinc-500">No quotes yet.</p> : (
          <div className="space-y-1.5">
            {s.response_times.map((t, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className="num w-12 text-right text-xs text-zinc-500">{Math.round(t)}s</span>
                <div className="h-2.5 flex-1 rounded-full bg-zinc-100">
                  <div className={`h-2.5 rounded-full ${t <= 120 ? "bg-emerald-500" : t <= 240 ? "bg-amber-400" : "bg-red-500"}`} style={{ width: `${Math.min(100, (t / max) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="rounded-xl border border-zinc-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold">Latest requests</h2>
        <table className="w-full text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-zinc-400"><th className="py-1 font-medium">Route</th><th className="font-medium">Customer</th><th className="font-medium">Status</th><th className="text-right font-medium">Quote</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.thread_id} className="border-t border-zinc-100">
              <td className="num py-1.5">{r.fields.origin ?? "?"} → {r.fields.destination ?? "?"}</td>
              <td className="text-zinc-600">{r.customer}</td><td>{r.status.replace("_", " ")}</td>
              <td className="num text-right">{r.chosen ? `${r.chosen.total} ${r.chosen.currency}` : "-"}</td>
            </tr>))}</tbody>
        </table>
      </section>
    </div>
  );
}
