// Read-only access to data/forwarder.db using Node's built-in SQLite (no native module to build).
// process.getBuiltinModule is used so the bundler never tries to resolve "node:sqlite".
import fs from "node:fs";
import path from "node:path";

export const DB_PATH = process.env.DB_PATH || path.join(process.cwd(), "..", "data", "forwarder.db");

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let db: any = null;
let opened = ""; // inode + size + mtime of the file the open connection belongs to

// The DB file can be replaced while the UI runs (a fresh snapshot downloaded over the old one).
// An open connection keeps reading the old file's pages mixed with the new file, which shows garbage.
// So the connection is reopened whenever the file on disk is a different file than the one we opened.
// The -wal file counts too: a WAL left over from an older file makes SQLite read the new file as "malformed".
function stamp(): string {
  const st = fs.statSync(DB_PATH);
  const w = fs.existsSync(`${DB_PATH}-wal`) ? fs.statSync(`${DB_PATH}-wal`) : null;
  return `${st.ino}:${st.size}:${st.mtimeMs}|${w ? `${w.ino}:${w.mtimeMs}` : "-"}`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function getDb(): any | null {
  if (!fs.existsSync(DB_PATH)) return null;
  const now = stamp();
  if (db && now === opened) return db;
  if (db) { try { db.close(); } catch { /* already closed */ } }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const { DatabaseSync } = (process as any).getBuiltinModule("node:sqlite");
  db = new DatabaseSync(DB_PATH, { readOnly: true });
  opened = now;
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
