// Run: node --experimental-strip-types --test lib/openai-chat.test.mjs
// fetch is mocked: nothing here talks to the network and no real key is used.
import test from "node:test";
import assert from "node:assert/strict";
import { runOpenAI, OPENAI_URL, OPENAI_DEFAULT_MODEL } from "./openai-chat.ts";

const KEY = "sk-test-not-a-real-key";
const TOOLS = [{ name: "get_case", description: "Read one request.", input_schema: { type: "object", properties: { thread_id: { type: "integer" } }, required: ["thread_id"], additionalProperties: false } }];
const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const base = (fetchImpl, extra = {}) => ({
  key: KEY, model: OPENAI_DEFAULT_MODEL, system: "SYS", history: [{ role: "user", content: "How is #41888?" }], tools: TOOLS,
  runTool: (name, input) => ({ result: { ok: true, name, input }, label: "Reading" }), onStep: () => {}, fetchImpl, ...extra,
});

test("one tool call round trip ends in a final answer, with the right request body", async () => {
  const calls = [];
  const steps = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init, body: JSON.parse(init.body) });
    if (calls.length === 1) return json(200, { choices: [{ finish_reason: "tool_calls", message: { content: null, tool_calls: [{ id: "call_1", type: "function", function: { name: "get_case", arguments: "{\"thread_id\":41888}" } }] } }] });
    return json(200, { choices: [{ finish_reason: "stop", message: { content: " It is booked. " } }] });
  };
  const out = await runOpenAI(base(fetchImpl, { onStep: (s) => steps.push(s) }));
  assert.equal(out, "It is booked.");
  assert.equal(calls.length, 2);
  const first = calls[0];
  assert.equal(first.url, OPENAI_URL);
  assert.equal(first.url, "https://api.openai.com/v1/chat/completions");
  assert.equal(first.init.method, "POST");
  assert.equal(first.init.headers.authorization, `Bearer ${KEY}`);
  assert.equal(first.body.model, "gpt-4o-mini");
  assert.equal(first.body.max_tokens, 2000);
  assert.deepEqual(first.body.messages, [{ role: "system", content: "SYS" }, { role: "user", content: "How is #41888?" }]);
  assert.equal(first.body.tools.length, 1);
  assert.equal(first.body.tools[0].type, "function");
  assert.equal(first.body.tools[0].function.name, "get_case");
  assert.deepEqual(first.body.tools[0].function.parameters, TOOLS[0].input_schema);
  // second request carries the assistant tool call and the tool result
  const m = calls[1].body.messages;
  assert.equal(m[2].role, "assistant");
  assert.equal(m[2].tool_calls[0].id, "call_1");
  assert.equal(m[3].role, "tool");
  assert.equal(m[3].tool_call_id, "call_1");
  assert.deepEqual(JSON.parse(m[3].content), { ok: true, name: "get_case", input: { thread_id: 41888 } });
  assert.deepEqual(steps, [{ tool: "get_case", label: "Reading" }]);
});

test("the tool loop is capped", async () => {
  let n = 0;
  const fetchImpl = async () => { n += 1; return json(200, { choices: [{ finish_reason: "tool_calls", message: { content: null, tool_calls: [{ id: `c${n}`, function: { name: "get_case", arguments: "{}" } }] } }] }); };
  const out = await runOpenAI(base(fetchImpl, { maxSteps: 3 }));
  assert.equal(n, 3);
  assert.match(out, /allowed number of lookups/);
});

test("model comes from the caller; reasoning models get max_completion_tokens", async () => {
  let body;
  const fetchImpl = async (_u, init) => { body = JSON.parse(init.body); return json(200, { choices: [{ finish_reason: "stop", message: { content: "ok" } }] }); };
  await runOpenAI(base(fetchImpl, { model: "gpt-5-mini" }));
  assert.equal(body.model, "gpt-5-mini");
  assert.equal(body.max_completion_tokens, 2000);
  assert.equal(body.max_tokens, undefined);
});

const failure = async (status, body, model) => {
  const fetchImpl = async () => json(status, body);
  try { await runOpenAI(base(fetchImpl, model ? { model } : {})); } catch (e) { return e; }
  assert.fail("should have thrown");
};

test("401 becomes one readable sentence and never echoes the key", async () => {
  const e = await failure(401, { error: { message: `Incorrect API key provided: ${KEY}`, code: "invalid_api_key" } });
  assert.equal(e.code, "auth");
  assert.match(e.message, /OpenAI rejected the API key/);
  assert.match(e.message, /OPENAI_API_KEY/);
  assert.ok(!e.message.includes(KEY) && !e.message.includes("sk-"));
});

test("429, 404, 500 and network failure are readable too", async () => {
  assert.match((await failure(429, { error: { code: "insufficient_quota" } })).message, /no credit/);
  const rate = await failure(429, { error: { code: "rate_limit_exceeded" } });
  assert.equal(rate.code, "rate");
  assert.match(rate.message, /Try again/);
  const nf = await failure(404, { error: { code: "model_not_found" } }, "gpt-nope");
  assert.match(nf.message, /does not know the model "gpt-nope"/);
  assert.match((await failure(503, {})).message, /\(503\)/);
  const down = async () => { throw new TypeError("fetch failed"); };
  await assert.rejects(runOpenAI(base(down)), (e) => e.code === "network" && /Could not reach OpenAI/.test(e.message));
});
