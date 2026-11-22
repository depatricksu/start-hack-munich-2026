import { NextResponse } from "next/server";
import { getWorkflow } from "@/lib/workflow";

export const dynamic = "force-dynamic";

// Read-only: the whole job for one shipment from the offline simulation DBs (?s=c1..c8, optional &t=thread).
export function GET(req: Request) {
  const u = new URL(req.url);
  const t = Number(u.searchParams.get("t")) || null;
  return NextResponse.json(getWorkflow(u.searchParams.get("s"), t));
}
