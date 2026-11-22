// The invoice document as a PDF (A4, Helvetica, real text: selectable, searchable). Same content as the page:
// both read InvoiceDoc from invoice-doc.ts.
import { PDFDocument, StandardFonts, rgb, type PDFFont, type PDFPage } from "pdf-lib";
import type { InvoiceDoc } from "./invoice-doc";

const W = 595.28, H = 841.89, M = 48;
const INK = rgb(0.09, 0.09, 0.1), MUTED = rgb(0.42, 0.42, 0.45), HAIR = rgb(0.84, 0.84, 0.86);

export async function renderInvoicePdf(d: InvoiceDoc): Promise<Uint8Array> {
  const pdf = await PDFDocument.create();
  pdf.setTitle(`Invoice ${d.number}`);
  pdf.setSubject(`Invoice ${d.number}, ${d.reference}`);
  pdf.setCreator("Relay");
  pdf.setProducer("Relay");
  const reg = await pdf.embedFont(StandardFonts.Helvetica);
  const bold = await pdf.embedFont(StandardFonts.HelveticaBold);

  // Standard fonts only know WinAnsi: anything else becomes "?" instead of crashing the download.
  const clean = (s: string, f: PDFFont) => [...s.replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/[–—]/g, "-").replace(/→/g, "to")]
    .map((c) => { try { f.encodeText(c); return c; } catch { return "?"; } }).join("");

  let page: PDFPage = pdf.addPage([W, H]);
  let y = H - M; // the baseline cursor, moving down

  const newPage = () => { page = pdf.addPage([W, H]); y = H - M; };
  const ensure = (h: number) => { if (y - h < M + 30) newPage(); };
  const text = (s: string, x: number, size = 10, f = reg, color = INK, right = false) => {
    const t = clean(s, f);
    page.drawText(t, { x: right ? x - f.widthOfTextAtSize(t, size) : x, y, size, font: f, color });
  };
  const wrap = (s: string, width: number, size: number, f: PDFFont): string[] => {
    const out: string[] = [];
    let line = "";
    for (const word of clean(s, f).split(/\s+/).filter(Boolean)) {
      const next = line ? `${line} ${word}` : word;
      if (f.widthOfTextAtSize(next, size) <= width || !line) line = next; else { out.push(line); line = word; }
    }
    if (line) out.push(line);
    return out.length ? out : [""];
  };
  const rule = (color = HAIR) => page.drawLine({ start: { x: M, y }, end: { x: W - M, y }, thickness: 0.6, color });

  // Head: title left, number right.
  y -= 18;
  text("INVOICE", M, 22, bold);
  text(d.number, W - M, 14, bold, INK, true);
  y -= 30;

  // Seller (left) and the facts (right), side by side.
  const top = y;
  text("From", M, 8, reg, MUTED); y -= 14;
  text(d.seller.name, M, 11, bold); y -= 14;
  if (d.seller.contact) { text(d.seller.contact, M); y -= 13; }
  if (d.seller.email) { text(d.seller.email, M); y -= 13; }
  y -= 8;
  text("Bill to", M, 8, reg, MUTED); y -= 14;
  text(d.customer.email, M, 11, bold); y -= 14;
  if (d.customer.request) for (const l of wrap(`Your request: ${d.customer.request}`, 230, 9, reg)) { text(l, M, 9, reg, MUTED); y -= 12; }
  const leftEnd = y;

  y = top;
  const meta: [string, string][] = [
    ["Invoice number", d.number], ["Issue date", d.issued],
    ["Due date", d.termsDays ? `${d.due} (${d.termsDays} days)` : d.due],
    ["Status", d.status.paid ? `${d.status.label}, ${d.status.paid}` : d.status.label],
    ["Our reference", d.reference],
  ];
  if (d.bookings.length) meta.push([d.bookings.length > 1 ? "Booking references" : "Booking reference", d.bookings.join(", ")]);
  for (const [k, v] of meta) {
    text(k, 330, 9, reg, MUTED);
    text(v, W - M, 10, reg, INK, true);
    y -= 15;
  }
  y = Math.min(y, leftEnd) - 14;

  // Shipments: lane, airline, weight, volume, booking reference.
  ensure(60);
  rule(); y -= 14;
  const cols = { lane: M, airline: M + 120, weight: M + 300, volume: M + 372, booking: M + 440 };
  const head = () => {
    text("Lane", cols.lane, 8, bold, MUTED); text("Airline", cols.airline, 8, bold, MUTED);
    text("Weight", cols.weight + 50, 8, bold, MUTED, true); text("Volume", cols.volume + 50, 8, bold, MUTED, true);
    text("Booking", cols.booking, 8, bold, MUTED);
    y -= 14;
  };
  head();
  for (const l of d.legs) {
    const air = wrap(l.airline ?? "", cols.weight - cols.airline - 10, 10, reg);
    ensure(14 * air.length + 6);
    const lane = `${d.legs.length > 1 && l.n ? `${l.n}. ` : ""}${l.origin ?? "?"} to ${l.destination ?? "?"}`;
    text(lane, cols.lane);
    air.forEach((a, i) => { const keep = y; y -= i * 13; text(a, cols.airline); y = keep; });
    if (l.kg) text(`${l.kg} kg`, cols.weight + 50, 10, reg, INK, true);
    if (l.cbm) text(`${l.cbm} cbm`, cols.volume + 50, 10, reg, INK, true);
    if (l.booking) text(l.booking, cols.booking);
    y -= 13 * air.length + 4;
  }
  if (d.legs.length > 1 && (d.totalKg || d.totalCbm)) {
    text("All shipments", cols.lane, 9, reg, MUTED);
    if (d.totalKg) text(`${d.totalKg} kg`, cols.weight + 50, 9, reg, MUTED, true);
    if (d.totalCbm) text(`${d.totalCbm} cbm`, cols.volume + 50, 9, reg, MUTED, true);
    y -= 14;
  }
  y -= 6; rule(); y -= 18;

  // Price lines. Amounts are the strings from the database.
  const amountX = W - M;
  text("Description", M, 8, bold, MUTED); text(`Amount (${d.currency})`, amountX, 8, bold, MUTED, true);
  y -= 16;
  for (const g of d.groups) {
    if (g.title) { ensure(30); text(g.title, M, 10, bold); y -= 15; }
    for (const it of g.items) {
      const lines = wrap(it.label, amountX - M - 90, 10, reg);
      ensure(13 * lines.length + 6);
      lines.forEach((ln, i) => { const keep = y; y -= i * 13; text(ln, M + (g.title ? 10 : 0)); y = keep; });
      text(it.amount, amountX, 10, reg, INK, true);
      y -= 13 * lines.length + 5;
    }
  }
  if (d.itemsNote) { ensure(24); for (const l of wrap(d.itemsNote, W - 2 * M, 9, reg)) { text(l, M, 9, reg, MUTED); y -= 12; } }
  y -= 4;

  // Total, as invoiced.
  ensure(60);
  rule(INK); y -= 20;
  text("Total", M, 12, bold);
  text(`${d.total} ${d.currency}`, amountX, 14, bold, INK, true);
  y -= 30;

  ensure(30);
  const terms = d.termsDays ? `Payment terms: ${d.termsDays} days. ` : "";
  for (const l of wrap(`${terms}Please quote ${d.number} with your payment.`, W - 2 * M, 9, reg)) { text(l, M, 9, reg, MUTED); y -= 12; }

  return pdf.save({ useObjectStreams: false });
}
