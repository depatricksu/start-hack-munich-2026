import { Target } from "lucide-react";

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
  accepted: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  rejected: "bg-red-50 text-red-700 ring-red-200",
  pending: "bg-zinc-100 text-zinc-600 ring-zinc-200",
  open: "bg-zinc-100 text-zinc-600 ring-zinc-200",
  voided: "bg-zinc-100 text-zinc-400 ring-zinc-200",
  "no answer": "bg-zinc-100 text-zinc-400 ring-zinc-200",
};

function num(v: unknown): number | null {
  const n = typeof v === "number" ? v : typeof v === "string" ? Number(v) : NaN;
  return Number.isFinite(n) ? n : null;
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex-1 px-7 first:pl-0">
      <div className="num text-[11px] uppercase tracking-wider text-zinc-400">{label}</div>
      <div className={`num mt-2.5 text-[2.6rem] font-semibold leading-none tracking-tight ${tone ?? "text-black"}`}>{value}</div>
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
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-10 py-7">
        <div className="flex items-center justify-between">
          <h1 className="flex items-center gap-2.5 text-lg font-semibold tracking-tight">
            <Target size={18} /> Score
          </h1>
          <span className="num rounded-lg border border-zinc-300 px-3 py-1.5 text-sm text-zinc-700">5U scorer</span>
        </div>
        <p className="mt-2 text-sm text-zinc-500">Our result per request from the 5U scorer. Cost points are added once an hour.</p>

        {!s.ok && <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">Could not read the scorer: {s.error}</div>}
        {s.ok && rows.length === 0 && <div className="mt-6 rounded-xl border border-line bg-surface p-6 text-sm text-zinc-500">No scored requests yet. The first request arrives at 16:00.</div>}

        {rows.length > 0 && (hasVerdict || totalPoints != null) && (
          <div className="mt-6 flex divide-x divide-zinc-200 border-t border-zinc-200 pt-6">
            {totalPoints != null && <Stat label="Total points" value={totalPoints.toLocaleString("en-GB", { maximumFractionDigits: 1 })} tone="text-black" />}
            <Stat label="Scored" value={String(rows.length)} />
            {hasVerdict && <Stat label="Accepted" value={String(accepted)} tone={accepted ? "text-emerald-600" : "text-black"} />}
            {hasVerdict && <Stat label="Rejected" value={String(rejected)} tone={rejected ? "text-red-600" : "text-black"} />}
          </div>
        )}

        {rows.length > 0 && (
          <div className="mt-8 overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="num text-[11px] uppercase tracking-wider text-zinc-400">
                {Object.keys(rows[0]).slice(0, 8).map((k) => <th key={k} className="pb-2 pr-4 text-left font-medium">{k.replaceAll("_", " ")}</th>)}
              </tr></thead>
              <tbody>{rows.map((r, i) => (
                <tr key={i} className="border-t border-zinc-100">
                  {Object.entries(r).slice(0, 8).map(([k, v]) => (
                    <td key={k} className="num py-3 pr-4 align-top">
                      {k === "verdict" ? <span className={`rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONE[String(v).toLowerCase()] ?? "bg-zinc-100 text-zinc-600 ring-zinc-200"}`}>{String(v)}</span>
                        : typeof v === "object" && v != null ? (
                          <span className="flex flex-wrap gap-1">
                            {Object.entries(v as Record<string, unknown>).map(([pk, pv]) => (
                              <span key={pk} className="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-500">
                                {pk} <span className="font-semibold text-black">{String(pv)}</span>
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
    </div>
  );
}
