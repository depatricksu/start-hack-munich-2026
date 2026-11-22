// Relay v2: one invoice as a document, with its own URL (/v2/invoices/INV-123). Read-only.
import Link from "next/link";
import { ArrowLeft, Download } from "lucide-react";
import { getInvoiceDoc } from "@/lib/invoice-doc";
import { InvoiceDocument } from "@/components/v2/invoice-document";

export const dynamic = "force-dynamic";

export default async function InvoicePage({ params }: { params: Promise<{ number: string }> }) {
  const { number: raw } = await params;
  // A hand-typed address like /v2/invoices/100%25 is not valid to decode: show "No such invoice", not an error page.
  let number = raw;
  try { number = decodeURIComponent(raw); } catch { /* keep it as typed */ }
  const d = getInvoiceDoc(number);
  const back = (
    <Link href="/v2/invoices" className="inline-flex items-center gap-1.5 text-[13px] text-[var(--fg-2)] transition-colors duration-150 hover:text-[var(--fg)]">
      <ArrowLeft size={14} />All invoices
    </Link>
  );
  if (!d) {
    return (
      <div className="mx-auto max-w-[900px] px-4 py-8 sm:px-6">
        {back}
        <h1 className="mt-4 text-[22px] font-semibold tracking-[-0.03em] text-[var(--fg)]">No such invoice</h1>
        <p className="mt-1 text-[14px] text-[var(--fg-2)]">There is no invoice with the number {number}.</p>
      </div>
    );
  }
  return (
    <div className="h-full overflow-y-auto scroll-thin">
      <div className="mx-auto max-w-[900px] space-y-5 px-4 py-8 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          {back}
          <span className="flex-1" />
          <Link href={`/v2/shipments?id=${d.threadId}`} className="btn btn-ghost">Open shipment</Link>
          <a href={`/api/invoices/${encodeURIComponent(d.number)}/pdf`} download className="btn btn-primary"><Download size={14} />Download PDF</a>
        </div>
        <InvoiceDocument d={d} />
        {d.body && (
          <details className="mx-auto max-w-[820px] text-[13px] text-[var(--fg-2)]">
            <summary className="cursor-pointer text-[var(--fg-3)] hover:text-[var(--fg-2)]">Mail text that goes with the invoice</summary>
            <pre className="mt-2 whitespace-pre-wrap rounded-md border border-[var(--hair)] bg-[var(--bg)] p-4 font-sans leading-relaxed">{d.body}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
