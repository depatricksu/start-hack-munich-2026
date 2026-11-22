import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { fmt, getWorkflow, HARNESS_CMD, HARNESS_CMD_ONE, PARTY, type Check, type Draft, type Item, type Mail, type Tone, type Workflow } from "@/lib/workflow";

export const dynamic = "force-dynamic";

// Color = state only: green done, blue in progress / info, amber needs a person / draft / missing, red delay or cancel, grey over.
const TONE: Record<Tone, string> = {
  green: "bg-emerald-400/12 text-emerald-300 ring-emerald-400/25",
  blue: "bg-sky-400/12 text-sky-300 ring-sky-400/25",
  amber: "bg-amber-400/12 text-amber-300 ring-amber-400/25",
  red: "bg-red-400/12 text-red-300 ring-red-400/25",
  grey: "bg-white/5 text-zinc-400 ring-white/10",
};
const TEXT: Record<Tone, string> = { green: "text-emerald-300", blue: "text-sky-300", amber: "text-amber-300", red: "text-red-300", grey: "text-zinc-400" };
const DOT: Record<Tone, string> = { green: "bg-emerald-400", blue: "bg-sky-400", amber: "bg-amber-400", red: "bg-red-400", grey: "bg-zinc-500" };

function Chip({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${TONE[tone]}`}>{children}</span>;
}

function MailBox({ m, label, note }: { m: Mail; label: string; note?: string }) {
  return (
    <details className="group mt-2">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-[11px] text-zinc-400 hover:text-white [&::-webkit-details-marker]:hidden">
        <ChevronDown size={12} className="transition group-open:rotate-180" />{label}
      </summary>
      <div className="mt-1.5 rounded-lg bg-black/20 p-3 ring-1 ring-inset ring-white/6">
        <div className="text-xs text-zinc-500">{m.from !== "us" && <span className="num">{m.from} · </span>}{m.subject}{note && <span className="text-zinc-600"> · {note}</span>}</div>
        <pre className="num mt-2 max-h-72 overflow-auto whitespace-pre-wrap text-[12px] leading-relaxed text-zinc-400">{m.body}</pre>
      </div>
    </details>
  );
}

function DraftRow({ d, showParty = true }: { d: Draft; showParty?: boolean }) {
  return (
    <details className="group rounded-lg bg-white/[0.02] px-3 py-2 ring-1 ring-inset ring-white/7">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[12px] [&::-webkit-details-marker]:hidden">
        <ChevronDown size={12} className="shrink-0 text-zinc-500 transition group-open:rotate-180" />
        {showParty && <span className="w-[118px] shrink-0 text-zinc-300">{PARTY[d.party]}</span>}
        <span className="min-w-0 flex-1 truncate text-zinc-400">{d.why}</span>
        {d.to ? <span className="num hidden max-w-[220px] truncate text-[11px] text-zinc-500 xl:inline">{d.to}</span> : <Chip tone="amber">missing address</Chip>}
        <Chip tone={d.status === "draft" ? "amber" : d.status === "sent" ? "green" : "grey"}>{d.status === "draft" ? "Draft" : d.status}</Chip>
      </summary>
      <div className="mt-2 text-xs text-zinc-500">
        To <span className="num text-zinc-300">{d.to || "—"}</span> · <span className="num">{fmt(d.at)}</span>
        {d.shared && <span className="text-zinc-600"> · not tied to one shipment</span>}
      </div>
      <div className="mt-0.5 text-xs text-zinc-200">{d.subject}</div>
      <pre className="num mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-black/20 p-3 text-[12px] leading-relaxed text-zinc-400 ring-1 ring-inset ring-white/6">{d.body}</pre>
    </details>
  );
}

function Step({ it }: { it: Item }) {
  const us = it.side === "us", cust = it.side === "customer", note = it.side === "clerk";
  const box = us ? "ml-auto max-w-[88%] rounded-2xl rounded-br-md bg-white/[0.06] ring-1 ring-inset ring-white/12 p-3.5"
    : cust ? "max-w-[88%] rounded-2xl rounded-bl-md bg-white/[0.035] ring-1 ring-inset ring-white/8 p-3.5"
    : note ? "rounded-xl border-l-2 border-white/10 bg-white/[0.015] py-2 pl-3.5 pr-3"
    : "rounded-xl border-l-2 border-white/15 bg-white/[0.025] py-2.5 pl-3.5 pr-3";
  const who = us ? "Us" : cust ? "Customer" : note ? "Note" : "Carrier";
  return (
    <li className="flex">
      <div className={`min-w-0 w-full ${us || cust ? "" : ""}`}>
        <div className={box}>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${DOT[it.tone]}`} />
            <span className="text-[11px] uppercase tracking-wide text-zinc-500">{who}</span>
            <span className={`text-[13px] font-semibold ${note ? "text-zinc-400" : "text-white"}`}>{it.title}</span>
            {it.chip && <Chip tone={it.tone}>{it.chip}</Chip>}
            <span className="num ml-auto text-[11px] text-zinc-500">{fmt(it.at)}</span>
          </div>
          {it.text && <p className="mt-1 text-[13px] text-zinc-300">{it.text}</p>}
          {it.facts.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-[12px]">
              {it.facts.map((f, i) => (
                <span key={i} className="text-zinc-500">{f.k} <span className={`${f.plain ? "" : "num "}${f.tone ? TEXT[f.tone] : "text-zinc-200"}`}>{f.v}</span></span>
              ))}
            </div>
          )}
          {it.clerk && <p className="mt-1.5 text-[11px] text-zinc-500">{it.clerk}</p>}
          {it.mail && <MailBox m={it.mail} label="Show the mail" />}
          {it.out && <MailBox m={it.out} label="Show our mail" note={it.out.note} />}
          {it.drafts.length > 0 && (
            <div className="mt-2.5 space-y-1.5">
              <div className="text-[11px] text-zinc-500">{it.drafts.length === 1 ? "Draft written" : `${it.drafts.length} drafts written`}</div>
              {it.drafts.map((d) => <DraftRow key={d.id} d={d} />)}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function Phase({ n, title, sub, items }: { n: number; title: string; sub: string; items: Item[] }) {
  return (
    <section className="rounded-2xl glass p-5">
      <div className="flex items-baseline gap-2">
        <span className="num text-xs text-zinc-500">{n}</span>
        <h2 className="text-sm font-semibold text-white">{title}</h2>
        <span className="num ml-auto text-xs text-zinc-500">{items.length} steps</span>
      </div>
      <p className="mt-0.5 text-xs text-zinc-500">{sub}</p>
      <ol className="mt-4 space-y-2.5">
        {items.map((it) => <Step key={it.key} it={it} />)}
        {items.length === 0 && <li className="text-sm text-zinc-500">Nothing in this run.</li>}
      </ol>
    </section>
  );
}

function CheckRow({ c }: { c: Check }) {
  const tone: Tone = c.ok === null ? "grey" : c.ok ? "green" : "red";
  return (
    <li className="flex items-start gap-2.5">
      <Chip tone={tone}>{c.ok === null ? "n/a" : c.ok ? "Yes" : "No"}</Chip>
      <div className="min-w-0">
        <div className="text-[13px] text-zinc-200">{c.label}</div>
        <div className="num text-[11px] text-zinc-500">{c.detail}</div>
      </div>
    </li>
  );
}

function Problem({ w }: { w: Workflow }) {
  return (
    <section className="rounded-2xl glass p-6">
      <h2 className="text-sm font-semibold text-white">No simulation data to show</h2>
      <p className="mt-1 text-sm text-zinc-400">{w.problem}</p>
      <p className="mt-3 text-xs text-zinc-500">Folder in use: <span className="num text-zinc-300">{w.dir}</span> (set <span className="num">SIM_DB_DIR</span> to change it). Make the files with the offline harness:</p>
      <pre className="num mt-2 overflow-auto rounded-lg bg-black/20 p-3 text-[12px] text-zinc-300 ring-1 ring-inset ring-white/6">{HARNESS_CMD}{"\n"}{HARNESS_CMD_ONE}</pre>
    </section>
  );
}

export default async function WorkflowPage({ searchParams }: PageProps<"/workflow">) {
  const sp = await searchParams;
  const s = typeof sp.s === "string" ? sp.s : null;
  const t = typeof sp.t === "string" ? Number(sp.t) || null : null;
  const w = getWorkflow(s, t);
  const h = w.header;
  const clerk = w.items.filter((i) => i.phase === "clerk");
  const ops = w.items.filter((i) => i.phase === "carrier");

  return (
    <div className="h-full overflow-y-auto p-2">
      <div className="mx-auto max-w-[1400px] space-y-3 px-2 py-3">
        <div className="px-1">
          <h1 className="text-xl font-semibold tracking-tight text-white">Workflow</h1>
          <p className="mt-0.5 text-sm text-zinc-500">The whole job for one shipment, from the customer&apos;s request to the paid invoice.</p>
        </div>

        <div className="flex items-center gap-3 rounded-xl bg-amber-400/[0.06] px-4 py-2.5 ring-1 ring-inset ring-amber-400/25">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
          <span className="text-sm text-amber-200">Simulation data, offline research runs, not the live game. Messages are drafts, nothing was sent.</span>
        </div>

        <nav className="grid grid-cols-4 gap-2" aria-label="Scenarios">
          {w.scenarios.map((sc) => {
            const active = sc.id === w.id;
            return (
              <Link key={sc.id} href={`/workflow?s=${sc.id}`} title={sc.desc}
                className={`rounded-xl px-3 py-2 transition ${active ? "glass-2 ring-1 ring-inset ring-white/20" : "hover:bg-white/[0.04]"}`}>
                <div className="flex items-center gap-2">
                  <span className="num text-[11px] text-zinc-500">{sc.id}</span>
                  <span className={`truncate text-[13px] ${active ? "font-semibold text-white" : "text-zinc-300"}`}>{sc.name}</span>
                  {!sc.exists && <span className="ml-auto"><Chip tone="amber">missing</Chip></span>}
                </div>
                <div className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-zinc-500">{sc.desc}</div>
              </Link>
            );
          })}
        </nav>

        {w.threads.length > 1 && (
          <div className="flex items-center gap-2 px-1 text-xs text-zinc-500">
            <span>{w.threads.length} shipments in this run:</span>
            {w.threads.map((x) => (
              <Link key={x.thread} href={`/workflow?s=${w.id}&t=${x.thread}`}
                className={`num rounded-md px-2 py-1 ${x.thread === w.thread ? "glass-2 text-white" : "text-zinc-400 hover:text-white"}`}>{x.label}</Link>
            ))}
          </div>
        )}

        {w.problem || !h ? <Problem w={w} /> : (
          <>
            <section className="rounded-2xl glass p-5">
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="num text-2xl font-semibold tracking-tight text-white">{h.route}</div>
                  <div className="mt-1 text-sm text-zinc-400">{h.company} <span className="num text-xs text-zinc-600">· {h.customer}</span></div>
                </div>
                <Chip tone={h.statusTone}>{h.status}</Chip>
              </div>
              <div className="mt-3 grid grid-cols-4 gap-x-6 gap-y-2 text-[13px]">
                {([
                  ["Booking", h.booking, true], ["Our ref", h.ref, true], ["Airline", h.airline, false], ["Trucker", h.trucker || "—", false],
                  ["AWB", h.awb || "not reported yet", !!h.awb], ["Flight", h.flight || "not reported yet", !!h.flight], ["Quote", h.quote, true],
                ] as [string, string, boolean][]).map(([k, v, n]) => (
                  <div key={k}><div className="text-[11px] text-zinc-500">{k}</div><div className={`${n ? "num" : ""} truncate ${v === "not reported yet" ? "text-zinc-500" : "text-zinc-200"}`}>{v}</div></div>
                ))}
                <div>
                  <div className="text-[11px] text-zinc-500">ETA planned → current</div>
                  <div className="num text-zinc-200">{h.etaPlanned} → <span className={h.late ? "text-red-300" : "text-zinc-200"}>{h.etaCurrent}</span></div>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2 text-[13px]">
                <span className="text-[11px] text-zinc-500">Invoice</span>
                <span className={`num ${TEXT[h.invoiceTone]}`}>{h.invoice}</span>
              </div>
            </section>

            <div className="grid grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] items-start gap-3">
              <div className="space-y-3">
                <Phase n={1} title="RFQ clerk (steps 1–5)" items={clerk}
                  sub="Request, quote, yes, booking. From the clerk's mails and event log in this run (dry run: its mails were not sent)." />
                <Phase n={2} title="Carrier part (carrierops)" items={ops}
                  sub="After the airline confirmed: every carrier mail, what it changed, and the drafts it produced for each party." />
              </div>

              <aside className="space-y-3">
                <section className="rounded-2xl glass p-5">
                  <h2 className="text-sm font-semibold text-white">Checks</h2>
                  <p className="mt-0.5 text-xs text-zinc-500">Computed from this run&apos;s data.</p>
                  <ul className="mt-3 space-y-2.5">{w.checks.map((c) => <CheckRow key={c.label} c={c} />)}</ul>
                </section>

                <section className="rounded-2xl glass p-5">
                  <h2 className="text-sm font-semibold text-white">Who was told what</h2>
                  <p className="mt-0.5 text-xs text-zinc-500">Every draft per party, in order.</p>
                  <div className="mt-3 space-y-3">
                    {w.parties.map((p) => (
                      <div key={p.party}>
                        <div className="mb-1 flex items-baseline gap-2">
                          <span className="text-[12px] font-semibold text-zinc-200">{p.label}</span>
                          <span className="num text-[11px] text-zinc-500">{p.drafts.length}</span>
                        </div>
                        {p.drafts.length ? (
                          <div className="space-y-1">{p.drafts.map((d) => <DraftRow key={d.id} d={d} showParty={false} />)}</div>
                        ) : <p className="text-[12px] text-zinc-600">Nothing.</p>}
                      </div>
                    ))}
                  </div>
                </section>

                <section className="rounded-2xl glass p-5">
                  <h2 className="text-sm font-semibold text-white">Carrier log <span className="font-normal text-zinc-500">(only collected)</span></h2>
                  <p className="mt-0.5 text-xs text-zinc-500">Written for later carrier ratings. Nothing reads it yet.</p>
                  <ul className="mt-3 space-y-1.5">
                    {w.log.map((l, i) => (
                      <li key={i} className="text-[12px]">
                        <div className="flex items-center gap-2">
                          <span className="text-zinc-300">{l.carrier}</span>
                          <Chip tone={l.tone}>{l.kind}</Chip>
                          <span className="num ml-auto text-[11px] text-zinc-500">{fmt(l.at)}</span>
                        </div>
                        {l.detail && <div className="truncate text-[11px] text-zinc-500" title={l.detail}>{l.detail}</div>}
                      </li>
                    ))}
                    {w.log.length === 0 && <li className="text-[12px] text-zinc-500">Empty.</li>}
                  </ul>
                </section>
              </aside>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
