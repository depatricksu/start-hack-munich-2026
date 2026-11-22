// An invoice as a sheet of light paper inside the dark UI. Pure markup, no hooks: the page renders it on the server.
import type { InvoiceDoc } from "@/lib/invoice-doc";

const TONE = { ok: "bg-emerald-100 text-emerald-800", warn: "bg-amber-100 text-amber-800", bad: "bg-red-100 text-red-800", idle: "bg-zinc-200 text-zinc-700" };

function Label({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-zinc-500">{children}</div>;
}

export function InvoiceDocument({ d }: { d: InvoiceDoc }) {
  const facts: [string, React.ReactNode][] = [
    ["Invoice number", d.number],
    ["Issue date", d.issued],
    ["Due date", d.termsDays ? `${d.due} (${d.termsDays} days)` : d.due],
    ["Status", <span key="s" className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${TONE[d.status.tone]}`}>{d.status.label}{d.status.paid ? `, ${d.status.paid}` : ""}</span>],
    ["Our reference", d.reference],
  ];
  if (d.bookings.length) facts.push([d.bookings.length > 1 ? "Booking references" : "Booking reference", d.bookings.join(", ")]);

  return (
    <article className="mx-auto w-full max-w-[820px] rounded-md bg-white px-10 py-10 text-[13px] text-zinc-900 shadow-[0_8px_40px_rgba(0,0,0,0.45)] sm:px-14">
      <header className="flex items-start justify-between gap-6">
        <h2 className="text-[26px] font-semibold tracking-[-0.02em]">Invoice</h2>
        <div className="tnum text-[16px] font-semibold">{d.number}</div>
      </header>

      <div className="mt-8 grid gap-8 sm:grid-cols-2">
        <div className="space-y-6">
          <div>
            <Label>From</Label>
            <div className="mt-1.5 text-[14px] font-semibold">{d.seller.name}</div>
            {d.seller.contact && <div>{d.seller.contact}</div>}
            {d.seller.email && <div>{d.seller.email}</div>}
          </div>
          <div>
            <Label>Bill to</Label>
            <div className="mt-1.5 break-all text-[14px] font-semibold">{d.customer.email}</div>
            {d.customer.request && <div className="mt-0.5 text-zinc-600">Your request: {d.customer.request}</div>}
          </div>
        </div>
        <dl className="space-y-1.5">
          {facts.map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-4">
              <dt className="text-zinc-500">{k}</dt>
              <dd className="tnum text-right">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      <section className="mt-9">
        <Label>{d.legs.length > 1 ? "Shipments" : "Shipment"}</Label>
        <div className="mt-2 overflow-x-auto border-y border-zinc-200">
          <table className="w-full min-w-[520px] text-left">
            <thead>
              <tr className="text-[11px] text-zinc-500">
                <th className="py-2 pr-3 font-medium">Lane</th><th className="py-2 pr-3 font-medium">Airline</th>
                <th className="py-2 pr-3 text-right font-medium">Weight</th><th className="py-2 pr-3 text-right font-medium">Volume</th>
                <th className="py-2 font-medium">Booking</th>
              </tr>
            </thead>
            <tbody>
              {d.legs.map((l, i) => (
                <tr key={i} className="border-t border-zinc-100 align-top">
                  <td className="tnum py-2 pr-3 whitespace-nowrap">{d.legs.length > 1 && l.n ? `${l.n}. ` : ""}{l.origin ?? "?"} → {l.destination ?? "?"}</td>
                  <td className="py-2 pr-3">{l.airline}</td>
                  <td className="tnum py-2 pr-3 text-right whitespace-nowrap">{l.kg ? `${l.kg} kg` : ""}</td>
                  <td className="tnum py-2 pr-3 text-right whitespace-nowrap">{l.cbm ? `${l.cbm} cbm` : ""}</td>
                  <td className="tnum py-2 whitespace-nowrap">{l.booking}</td>
                </tr>
              ))}
              {d.legs.length > 1 && (d.totalKg || d.totalCbm) && (
                <tr className="border-t border-zinc-100 text-zinc-500">
                  <td className="py-2 pr-3" colSpan={2}>All shipments</td>
                  <td className="tnum py-2 pr-3 text-right whitespace-nowrap">{d.totalKg ? `${d.totalKg} kg` : ""}</td>
                  <td className="tnum py-2 pr-3 text-right whitespace-nowrap">{d.totalCbm ? `${d.totalCbm} cbm` : ""}</td>
                  <td />
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mt-8">
        <div className="flex justify-between"><Label>Description</Label><Label>Amount ({d.currency})</Label></div>
        <div className="mt-2 border-t border-zinc-200">
          {d.groups.map((g, gi) => (
            <div key={gi}>
              {g.title && <div className="pt-3 text-[12px] font-semibold">{g.title}</div>}
              {g.items.map((it, i) => (
                <div key={i} className={`flex items-baseline justify-between gap-6 border-b border-zinc-100 py-2 ${g.title ? "pl-3" : ""}`}>
                  <span>{it.label}</span><span className="tnum shrink-0">{it.amount}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        {d.itemsNote && <p className="mt-2 text-[12px] text-zinc-500">{d.itemsNote}</p>}
        <div className="mt-3 flex items-baseline justify-between gap-6 border-t-2 border-zinc-900 pt-3">
          <span className="text-[15px] font-semibold">Total</span>
          <span className="tnum text-[20px] font-semibold">{d.total} {d.currency}</span>
        </div>
      </section>

      <p className="mt-8 text-[12px] text-zinc-500">
        {d.termsDays ? `Payment terms: ${d.termsDays} days. ` : ""}Please quote {d.number} with your payment.
      </p>
    </article>
  );
}
