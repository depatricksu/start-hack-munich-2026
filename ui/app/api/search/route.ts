import { NextResponse } from "next/server";
import { search } from "@/lib/search";

export const dynamic = "force-dynamic";

// Read-only search over the runner's data. GET /api/search?q=HAM RUH lost
export function GET(req: Request) {
  const q = new URL(req.url).searchParams.get("q") ?? "";
  return NextResponse.json(search(q.slice(0, 200)));
}
