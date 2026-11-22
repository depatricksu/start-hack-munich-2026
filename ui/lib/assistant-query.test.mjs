// The query process of Ask Relay (QUERY_CHILD in assistant.ts): it must answer normal questions, cap the rows, refuse
// to write, and above all be KILLED when a statement would run for ever. Run: node --test lib/assistant-query.test.mjs
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { DatabaseSync } from "node:sqlite";

const src = fs.readFileSync(new URL("./assistant.ts", import.meta.url), "utf8");
const CHILD = /const QUERY_CHILD = `([\s\S]*?)`;/.exec(src)?.[1];
const QUERY_MS = Number(/const QUERY_MS = (\d+);/.exec(src)?.[1]);

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ask-query-"));
const file = path.join(dir, "t.db");
const seed = new DatabaseSync(file);
seed.exec("CREATE TABLE bids(id INTEGER PRIMARY KEY, carrier TEXT, total REAL)");
const ins = seed.prepare("INSERT INTO bids(carrier, total) VALUES(?, ?)");
for (let i = 0; i < 300; i += 1) ins.run(`carrier ${i % 7}`, 100 + i);
seed.close();

function run(sql, ms = QUERY_MS) {
  const started = Date.now();
  const r = spawnSync(process.execPath, ["--no-warnings", "-e", CHILD], {
    input: JSON.stringify({ path: file, sql, cap: 200 }), encoding: "utf8", timeout: ms, killSignal: "SIGKILL",
  });
  return { r, took: Date.now() - started, out: r.stdout ? JSON.parse(r.stdout) : null };
}

test("the program text is found in assistant.ts", () => {
  assert.ok(CHILD && CHILD.includes("readOnly: true"));
  assert.equal(QUERY_MS, 5000);
});

test("a normal question is answered", () => {
  const { out } = run("SELECT carrier, COUNT(*) AS n, ROUND(SUM(total)) AS eur FROM bids GROUP BY carrier ORDER BY carrier");
  assert.equal(out.rows.length, 7);
  assert.equal(out.rows[0].carrier, "carrier 0");
  assert.equal(out.more, false);
});

test("at most 200 rows come back, and the caller is told there were more", () => {
  const { out } = run("SELECT id FROM bids");
  assert.equal(out.rows.length, 200);
  assert.equal(out.more, true);
});

test("an endless statement with no RECURSIVE keyword and no rows is killed", () => {
  const { r, took } = run("WITH c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c) SELECT count(*) FROM c", 1500);
  assert.equal(r.signal, "SIGKILL");
  assert.ok(took < 4000, `took ${took} ms`);
});

test("a count over a huge join is killed too", () => {
  const { r } = run("SELECT count(*) FROM bids a, bids b, bids c, bids d, bids e", 1500);
  assert.equal(r.signal, "SIGKILL");
});

test("the file is opened read-only: a write is refused", () => {
  const { out } = run("DELETE FROM bids");
  assert.match(out.error, /readonly/i);
  const check = new DatabaseSync(file, { readOnly: true });
  assert.equal(check.prepare("SELECT COUNT(*) AS n FROM bids").get().n, 300);
  check.close();
});

test("bad SQL comes back as an error text, not a crash", () => {
  const { r, out } = run("SELECT nope FROM nowhere");
  assert.equal(r.status, 0);
  assert.match(out.error, /no such table/i);
});
