import { NextResponse } from "next/server";
import { markPaid } from "@/lib/invoices";

export const dynamic = "force-dynamic";

// POST {"key": "INV-123"}: the forwarder saw the money. Same as `python3 -m booking.invoice --paid 123`.
export async function POST(req: Request) {
  const { key } = (await req.json().catch(() => ({}))) as { key?: string };
  if (!key) return NextResponse.json({ error: "key missing" }, { status: 400 });
  const inv = markPaid(String(key));
  return inv ? NextResponse.json(inv) : NextResponse.json({ error: "no such invoice" }, { status: 404 });
}
