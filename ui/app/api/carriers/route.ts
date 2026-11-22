import { NextResponse } from "next/server";
import { getCarriers } from "@/lib/carriers";

export const dynamic = "force-dynamic";

// Read-only: carrier directory, their record, and every carrier mail sorted into a shipment update. Nothing is sent.
export function GET() {
  return NextResponse.json(getCarriers());
}
