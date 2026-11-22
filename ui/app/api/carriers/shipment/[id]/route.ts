import { NextResponse } from "next/server";
import { getShipmentUpdates } from "@/lib/carriers";

export const dynamic = "force-dynamic";

// Read-only: the carrier updates for one shipment, and whether the customer heard about each one.
export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  return NextResponse.json(getShipmentUpdates(Number(id)));
}
