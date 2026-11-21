import { NextResponse } from "next/server";
import { getSessions } from "@/lib/data";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(getSessions());
}
