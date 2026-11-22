import { NextResponse } from "next/server";
import { getExceptions } from "@/lib/exceptions";

export const dynamic = "force-dynamic";

// Read-only list of what is off track (see lib/exceptions.ts).
export function GET() {
  return NextResponse.json({ items: getExceptions() });
}
