// OpenAI Chat Completions with function calling, for "Ask Relay". A small pure module: no imports, so a test can
// load it directly. It talks to api.openai.com only, with the global fetch. The key is sent as a header and is
// never put in a message, a log line or an error text (OpenAI's own error texts can quote part of it, so they
// are never passed on either).

export const OPENAI_URL = "https://api.openai.com/v1/chat/completions";
export const OPENAI_DEFAULT_MODEL = "gpt-4o-mini";

export type ToolDef = { name: string; description: string; input_schema: Record<string, unknown> };
export type ChatMessage = { role: "user" | "assistant"; content: string };
export type ToolRunner = (name: string, input: Record<string, unknown>) => { result: unknown; label: string };

export class ChatError extends Error {
  code: "auth" | "rate" | "api" | "network";
  constructor(code: "auth" | "rate" | "api" | "network", message: string) {
    super(message);
    this.code = code;
  }
}

// Not "strict": strict mode refuses a schema unless every property is required and extras are forbidden, and a
// refused schema is a 400 on the very first question. Plain function calling takes any JSON schema.
export function openaiTools(defs: ToolDef[]) {
  return defs.map((d) => ({ type: "function", function: { name: d.name, description: d.description, parameters: d.input_schema } }));
}

// One short sentence per failure. `body` is only read for a machine code, never shown.
export function explainStatus(status: number, model: string, code: string | null): ChatError {
  if (status === 401 || status === 403) return new ChatError("auth", "OpenAI rejected the API key. Check OPENAI_API_KEY in ui/.env.local and restart the UI.");
  if (status === 429) {
    if (code === "insufficient_quota") return new ChatError("rate", "The OpenAI account has no credit left. Add credit, then ask again.");
    return new ChatError("rate", "OpenAI says too many questions right now. Try again in a moment.");
  }
  if (status === 404) return new ChatError("api", `OpenAI does not know the model "${model}". Set RELAY_ASSISTANT_MODEL to a model your account can use.`);
  if (status >= 500) return new ChatError("api", `OpenAI is having a problem (${status}). Try again in a moment.`);
  return new ChatError("api", `OpenAI answered with an error (${status}).`);
}

// Newer reasoning models refuse max_tokens and want max_completion_tokens.
const wantsCompletionTokens = (model: string) => /^(o\d|gpt-5)/i.test(model);

type Fn = typeof fetch;
type ToolCall = { id: string; type?: string; function: { name: string; arguments: string } };
type Reply = { choices?: { finish_reason?: string; message?: { content?: string | null; tool_calls?: ToolCall[] } }[] };

const TOOL_RESULT_CAP = 40000;

export async function runOpenAI(o: {
  key: string; model: string; system: string; history: ChatMessage[]; tools: ToolDef[];
  runTool: ToolRunner; onStep: (s: { tool: string; label: string }) => void;
  maxSteps?: number; maxTokens?: number; fetchImpl?: Fn;
}): Promise<string> {
  const doFetch: Fn = o.fetchImpl ?? fetch;
  const maxSteps = o.maxSteps ?? 8;
  const maxTokens = o.maxTokens ?? 2000;
  const tools = openaiTools(o.tools);
  const messages: Record<string, unknown>[] = [{ role: "system", content: o.system }, ...o.history];

  for (let i = 0; i < maxSteps; i += 1) {
    let res: Response;
    try {
      res = await doFetch(OPENAI_URL, {
        method: "POST",
        headers: { "content-type": "application/json", authorization: `Bearer ${o.key}` },
        body: JSON.stringify({
          model: o.model, messages, tools, tool_choice: "auto",
          ...(wantsCompletionTokens(o.model) ? { max_completion_tokens: maxTokens } : { max_tokens: maxTokens }),
        }),
        signal: AbortSignal.timeout(90000),
      });
    } catch (e) {
      const timedOut = (e as Error)?.name === "TimeoutError";
      throw new ChatError("network", timedOut ? "OpenAI took too long to answer. Try again." : "Could not reach OpenAI. Check the network connection.");
    }
    if (!res.ok) {
      let code: string | null = null;
      try { code = ((await res.json()) as { error?: { code?: string | null } })?.error?.code ?? null; } catch { /* no body */ }
      throw explainStatus(res.status, o.model, code);
    }
    let data: Reply;
    try { data = (await res.json()) as Reply; } catch { throw new ChatError("api", "OpenAI sent an answer that could not be read."); }
    const choice = data.choices?.[0];
    const msg = choice?.message;
    if (!msg) throw new ChatError("api", "OpenAI sent an empty answer.");
    const calls = (msg.tool_calls ?? []).filter((c) => c?.function?.name);
    if (calls.length === 0) {
      const text = (msg.content ?? "").trim();
      if (choice?.finish_reason === "length") return `${text}\n\n(The answer was cut off because it got too long.)`;
      return text || "I found nothing to say about that.";
    }
    messages.push({ role: "assistant", content: msg.content ?? null, tool_calls: calls });
    for (const c of calls) {
      let input: Record<string, unknown> = {};
      try { const p = JSON.parse(c.function.arguments || "{}"); if (p && typeof p === "object") input = p; } catch { /* bad JSON: the tool answers with an error */ }
      const { result, label } = o.runTool(c.function.name, input);
      o.onStep({ tool: c.function.name, label });
      let content = JSON.stringify(result);
      if (content.length > TOOL_RESULT_CAP) content = `${content.slice(0, TOOL_RESULT_CAP)} [cut: result too long]`;
      messages.push({ role: "tool", tool_call_id: c.id, content });
    }
  }
  return "I could not finish this in the allowed number of lookups. Try a narrower question.";
}
