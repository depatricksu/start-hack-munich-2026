// Read-only access to data/forwarder.db using Node's built-in SQLite (no native module to build).
// process.getBuiltinModule is used so the bundler never tries to resolve "node:sqlite".
import fs from "node:fs";
import path from "node:path";

export const DB_PATH = process.env.DB_PATH || path.join(process.cwd(), "..", "data", "forwarder.db");

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let db: any = null;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getDb(): any | null {
  if (db) return db;
  if (!fs.existsSync(DB_PATH)) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { DatabaseSync } = (process as any).getBuiltinModule("node:sqlite");
  db = new DatabaseSync(DB_PATH, { readOnly: true });
  return db;
}

// Writable connection used ONLY by the take-over route. It inserts into `actions`; the runner does the sending.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let wdb: any = null;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getWriteDb(): any | null {
  if (wdb) return wdb;
  if (!fs.existsSync(DB_PATH)) return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { DatabaseSync } = (process as any).getBuiltinModule("node:sqlite");
  wdb = new DatabaseSync(DB_PATH);
  wdb.exec("PRAGMA busy_timeout=3000");
  wdb.exec("CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, kind TEXT, body TEXT, created_at REAL, done_at REAL, result TEXT)");
  return wdb;
}
