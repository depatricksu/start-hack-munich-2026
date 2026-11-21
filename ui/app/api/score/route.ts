import { NextResponse } from "next/server";
import fs from "node:fs";
import path from "node:path";

export const dynamic = "force-dynamic";

// The 5U key stays on the server. Read it from the env or from the repo .env (never sent to the browser).
function apiKey(): string {
  if (process.env.FIVEU_API_KEY) return process.env.FIVEU_API_KEY;
  try {
    const t = fs.readFileSync(path.join(process.cwd(), "..", ".env"), "utf8");
    return /^FIVEU_API_KEY=(.+)$/m.exec(t)?.[1]?.trim() ?? "";
  } catch { return ""; }
}

export async function GET() {
  const base = process.env.FIVEU_BASE_URL || "https://api.start-hack.5u.ai";
  const key = apiKey();
  if (!key) return NextResponse.json({ error: "no key" }, { status: 500 });
  const r = await fetch(`${base}/v1/board/me`, { headers: { "X-API-Key": key }, cache: "no-store" });
  return NextResponse.json(await r.json().catch(() => ({})), { status: r.status });
}
