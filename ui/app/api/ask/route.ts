import { NextResponse } from "next/server";
import { ask, assistantKey, assistantModel, provider, AssistantError, Turn } from "@/lib/assistant";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 120;

// Is the assistant set up? The page asks this once to decide what to show.
export function GET() {
  return NextResponse.json({ ready: !!assistantKey(), model: assistantModel(), provider: provider() });
}

// POST {turns:[{role,text}]} -> a stream of JSON lines: {step} while it looks things up, then {answer} or {error}.
export async function POST(req: Request) {
  let turns: Turn[] = [];
  try {
    const body = (await req.json()) as { turns?: unknown };
    if (Array.isArray(body.turns))
      turns = body.turns.filter((t): t is Turn => !!t && typeof t === "object"
        && ((t as Turn).role === "user" || (t as Turn).role === "assistant") && typeof (t as Turn).text === "string" && (t as Turn).text.trim() !== "");
  } catch { /* handled below */ }
  if (!turns.length || turns[turns.length - 1].role !== "user")
    return NextResponse.json({ error: "bad_request", message: "Send a question." }, { status: 400 });
  if (!assistantKey())
    return NextResponse.json({ error: "no_key", message: "The assistant has no key yet. Add OPENAI_API_KEY to ui/.env.local and restart the UI." }, { status: 503 });

  const enc = new TextEncoder();
  const stream = new ReadableStream({
    async start(ctrl) {
      const send = (o: unknown) => ctrl.enqueue(enc.encode(`${JSON.stringify(o)}\n`));
      try {
        const answer = await ask(turns, (step) => send({ step }));
        send({ answer });
      } catch (e) {
        if (e instanceof AssistantError) send({ error: e.code, message: e.message });
        else { console.error("ask failed", e); send({ error: "api", message: "Something went wrong while answering." }); }
      } finally {
        ctrl.close();
      }
    },
  });
  return new Response(stream, { headers: { "content-type": "application/x-ndjson; charset=utf-8", "cache-control": "no-store" } });
}
