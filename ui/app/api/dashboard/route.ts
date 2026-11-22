import { NextResponse } from "next/server";
import { getDashboard } from "@/lib/dashboard";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json(getDashboard());
}
