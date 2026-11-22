import { getInvoiceDoc } from "@/lib/invoice-doc";
import { renderInvoicePdf } from "@/lib/invoice-pdf";

export const dynamic = "force-dynamic";

// Read-only: the invoice as a PDF file, same content as /v2/invoices/<number>.
export async function GET(_req: Request, ctx: { params: Promise<{ number: string }> }) {
  const { number } = await ctx.params;
  const doc = getInvoiceDoc(number);
  if (!doc) return Response.json({ error: "no such invoice" }, { status: 404 });
  const bytes = await renderInvoicePdf(doc);
  return new Response(Buffer.from(bytes), {
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="invoice-${doc.number.replace(/[^\w.-]/g, "_")}.pdf"`,
      "Cache-Control": "no-store",
    },
  });
}
