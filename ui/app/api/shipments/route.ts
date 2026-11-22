import { NextResponse } from "next/server";
import { getShipments } from "@/lib/shipments";

export const dynamic = "force-dynamic";

// Read-only: every booking after the customer said yes, with its lifecycle. Nothing is sent from here.
export function GET() {
  return NextResponse.json(getShipments());
}
