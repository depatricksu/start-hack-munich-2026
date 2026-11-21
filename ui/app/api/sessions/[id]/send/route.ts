import { NextResponse } from "next/server";
import { getWriteDb } from "@/lib/db";
import { getDetail } from "@/lib/data";

export const dynamic = "force-dynamic";

// A human reply from the UI. We only queue it; the runner (the only sender) sends it within a second.
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const tid = Number(id);
  const { body } = (await req.json().catch(() => ({}))) as { body?: string };
  const text = (body ?? "").trim();
  if (!text) return NextResponse.json({ error: "The reply is empty." }, { status: 400 });
  if (text.length > 5000) return NextResponse.json({ error: "The reply is too long (max 5000 characters)." }, { status: 400 });
  const { source, session } = getDetail(tid);
  if (source === "demo") return NextResponse.json({ error: "Demo data: nothing is sent." }, { status: 409 });
  if (!session) return NextResponse.json({ error: "No such request." }, { status: 404 });
  const db = getWriteDb();
  if (!db) return NextResponse.json({ error: "Database not found." }, { status: 500 });
  db.prepare("INSERT INTO actions(thread_id, kind, body, created_at) VALUES(?, 'send_reply', ?, ?)").run(tid, text, Date.now() / 1000);
  return NextResponse.json({ ok: true });
}
