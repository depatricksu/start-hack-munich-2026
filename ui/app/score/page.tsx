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
  voided: "bg-zinc-100 text-zinc-500 ring-zinc-200", "no answer": "bg-zinc-100 text-zinc-500 ring-zinc-200",
};

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      <div className="text-[11px] uppercase tracking-wide text-zinc-400">{label}</div>
      <div className={`num mt-1 text-4xl font-semibold tracking-tight ${tone ?? ""}`}>{value}</div>
    </div>
  );
}

export default async function Score() {
  const s = await load();
  const rows = s.rows;
  const pointsKey = rows.length ? Object.keys(rows[0]).find((k) => /points?|score/i.test(k) && num(rows[0][k]) != null) : undefined;
  const totalPoints = pointsKey ? rows.reduce((a, r) => a + (num(r[pointsKey]) ?? 0), 0) : null;
  const verdicts = rows.map((r) => String(r.verdict ?? "").toLowerCase());
  const accepted = verdicts.filter((v) => v === "accepted").length;
  const rejected = verdicts.filter((v) => v === "rejected").length;
  const hasVerdict = verdicts.some(Boolean);

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Score</h1>
        <p className="mt-0.5 text-sm text-zinc-500">Our result per request from the 5U scorer. Cost points are added once an hour.</p>
      </div>

      {!s.ok && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Could not read the scorer: {s.error}</div>}
      {s.ok && rows.length === 0 && <div className="rounded-xl border border-line bg-surface p-6 text-sm text-zinc-500">No scored requests yet. The first request arrives at 16:00.</div>}

      {rows.length > 0 && (hasVerdict || totalPoints != null) && (
        <div className="grid grid-cols-4 gap-4">
          {totalPoints != null && <Stat label="Total points" value={totalPoints.toLocaleString("en-GB", { maximumFractionDigits: 1 })} tone="text-emerald-700" />}
          <Stat label="Scored requests" value={String(rows.length)} />
          {hasVerdict && <Stat label="Accepted" value={String(accepted)} tone={accepted ? "text-emerald-700" : ""} />}
          {hasVerdict && <Stat label="Rejected" value={String(rejected)} tone={rejected ? "text-red-600" : ""} />}
        </div>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface p-5">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-[11px] uppercase tracking-wide text-zinc-400">
              {Object.keys(rows[0]).slice(0, 8).map((k) => <th key={k} className="py-1 pr-4 font-medium">{k.replaceAll("_", " ")}</th>)}
            </tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i} className="border-t border-zinc-100">
                {Object.entries(r).slice(0, 8).map(([k, v]) => (
                  <td key={k} className="num py-2 pr-4 align-top">
                    {k === "verdict" ? <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE[String(v).toLowerCase()] ?? "bg-zinc-100 text-zinc-600 ring-zinc-200"}`}>{String(v)}</span>
                      : typeof v === "object" && v != null ? (
                        <span className="flex flex-wrap gap-1">
                          {Object.entries(v as Record<string, unknown>).map(([pk, pv]) => (
                            <span key={pk} className="rounded bg-surface-2 px-1.5 py-0.5 text-[11px] text-zinc-600 ring-1 ring-inset ring-line">
                              {pk} <span className="font-semibold text-zinc-800">{String(pv)}</span>
                            </span>
                          ))}
                          {Object.keys(v as object).length === 0 && <span className="text-zinc-300">—</span>}
                        </span>
                      ) : String(v ?? "")}
                  </td>))}
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
