export const dynamic = "force-dynamic";

type Row = Record<string, unknown>;

async function load(): Promise<{ ok: boolean; rows: Row[]; bookings: Row[]; error?: string }> {
  try {
    const base = process.env.UI_BASE_URL || "http://localhost:3000";
    const r = await fetch(`${base}/api/score`, { cache: "no-store" });
    const d = await r.json();
    if (!r.ok) return { ok: false, rows: [], bookings: [], error: String(d.error ?? r.status) };
    const rows = (d.requests ?? d.rounds ?? d.results ?? (Array.isArray(d) ? d : [])) as Row[];
    return { ok: true, rows, bookings: (d.bookings ?? []) as Row[] };
  } catch (e) { return { ok: false, rows: [], bookings: [], error: String(e) }; }
}

const TONE: Record<string, string> = {
  accepted: "bg-emerald-50 text-emerald-700 ring-emerald-200", rejected: "bg-red-50 text-red-700 ring-red-200",
  pending: "bg-amber-50 text-amber-800 ring-amber-200", open: "bg-sky-50 text-sky-700 ring-sky-200",
};

export default async function Score() {
  const s = await load();
  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <h1 className="text-xl font-semibold tracking-tight">Score</h1>
      <p className="text-sm text-zinc-500">Our result per request from the 5U scorer. Cost points are added once an hour.</p>
      {!s.ok && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Could not read the scorer: {s.error}</div>}
      {s.ok && s.rows.length === 0 && <div className="rounded-xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500">No scored requests yet. The first request arrives at 16:00.</div>}
      {s.rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white p-5">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-zinc-400">
              {Object.keys(s.rows[0]).slice(0, 8).map((k) => <th key={k} className="py-1 pr-4 font-medium">{k.replaceAll("_", " ")}</th>)}
            </tr></thead>
            <tbody>{s.rows.map((r, i) => (
              <tr key={i} className="border-t border-zinc-100">
                {Object.entries(r).slice(0, 8).map(([k, v]) => (
                  <td key={k} className="num py-1.5 pr-4">
                    {k === "verdict" ? <span className={`rounded-full px-2 py-0.5 text-xs ring-1 ring-inset ${TONE[String(v)] ?? "bg-zinc-100 text-zinc-600 ring-zinc-200"}`}>{String(v)}</span>
                      : typeof v === "object" ? JSON.stringify(v) : String(v ?? "")}
                  </td>))}
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
