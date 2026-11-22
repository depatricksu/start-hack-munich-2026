import { NextResponse } from "next/server";
import { getShipment } from "@/lib/shipments";

export const dynamic = "force-dynamic";

// Read-only: one shipment with its "after the yes" messages (drafts the forwarder reads; nothing is sent).
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return NextResponse.json({ shipment: getShipment(Number(id)) });
}
