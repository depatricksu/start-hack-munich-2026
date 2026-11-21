"""SQLite: our CRM + event log. One file, data/forwarder.db (git-ignored). The UI only reads it.

Tables
  mails     every mail we received (id = 5U mail id), with its route
  sessions  one row per RFQ thread (thread_id = id of the customer's first mail)
  bids      one row per bid we asked a carrier/trucker for (sourcing/ fills this)
  events    every step, in order (mail_in, route, llm, options, quote_sent, ...)
  state     small key/value store (since_id)

Session status: new -> waiting_bids -> sending -> quoted
                or: needs_human (we could not price it safely) / expired / failed
"""
import json, os, sqlite3, time
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS mails(id INTEGER PRIMARY KEY, sender TEXT, subject TEXT, body TEXT,
  thread_id INTEGER, route TEXT, received_at REAL, raw TEXT);
CREATE TABLE IF NOT EXISTS sessions(thread_id INTEGER PRIMARY KEY, customer TEXT, subject TEXT, status TEXT,
  fields TEXT, reply_template TEXT, options TEXT, chosen TEXT, reply TEXT, note TEXT,
  received_at REAL, deadline REAL, quoted_at REAL, llm_cost_usd REAL);
CREATE TABLE IF NOT EXISTS bids(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, carrier TEXT, kind TEXT,
  requested_at REAL, replied_at REAL, total TEXT, currency TEXT, transit_days INTEGER, raw TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, thread_id INTEGER, mail_id INTEGER,
  kind TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
"""

_con = None


def con():
    global _con
    if _con is None:
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        _con = sqlite3.connect(config.DB_PATH, isolation_level=None, check_same_thread=False)   # autocommit; shared with the supervisor's share thread (WAL + serialized mode)
        _con.row_factory = sqlite3.Row
        _con.execute("PRAGMA journal_mode=WAL")                        # UI can read while we write
        _con.executescript(SCHEMA)
    return _con


def event(kind, thread_id=None, mail_id=None, **data):
    """Log one step. Call this for every decision."""
    con().execute("INSERT INTO events(ts,thread_id,mail_id,kind,data) VALUES(?,?,?,?,?)",
                  (time.time(), thread_id, mail_id, kind, json.dumps(data, default=str)))
    print(time.strftime("%H:%M:%S"), kind, "thread=%s mail=%s" % (thread_id, mail_id),
          json.dumps(data, default=str)[:300], flush=True)


def get_state(key, default=None):
    r = con().execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_state(key, value):
    con().execute("INSERT OR REPLACE INTO state(key,value) VALUES(?,?)", (key, str(value)))


def save_mail(m):
    """Store a mail. Returns False if we already had it (so it is never handled twice)."""
    cur = con().execute("INSERT OR IGNORE INTO mails(id,sender,subject,body,thread_id,received_at,raw) VALUES(?,?,?,?,?,?,?)",
                        (m["id"], m["sender"], m["subject"], m["body"], m["thread_id"], m["received_at"], json.dumps(m["raw"])))
    return cur.rowcount == 1


def set_route(mail_id, route):
    con().execute("UPDATE mails SET route=? WHERE id=?", (route, mail_id))


def session(thread_id):
    r = con().execute("SELECT * FROM sessions WHERE thread_id=?", (thread_id,)).fetchone()
    return dict(r) if r else None


def new_session(m):
    con().execute("INSERT OR IGNORE INTO sessions(thread_id,customer,subject,status,received_at,deadline) VALUES(?,?,?,?,?,?)",
                  (m["thread_id"], m["sender"], m["subject"], "new", m["received_at"], m["received_at"] + config.BID_WAIT_S))


def update_session(thread_id, **cols):
    for k in ("fields", "options", "chosen"):
        if k in cols and not isinstance(cols[k], str):
            cols[k] = json.dumps(cols[k], default=str)
    sets = ",".join("%s=?" % k for k in cols)
    con().execute("UPDATE sessions SET %s WHERE thread_id=?" % sets, list(cols.values()) + [thread_id])


def claim_for_sending(thread_id):
    """True only once per thread. Only the first quote in a thread counts, so we never send two."""
    cur = con().execute("UPDATE sessions SET status='sending' WHERE thread_id=? AND status IN ('new','waiting_bids')",
                        (thread_id,))
    return cur.rowcount == 1


def waiting_sessions():
    return [dict(r) for r in con().execute("SELECT * FROM sessions WHERE status='waiting_bids'")]


def bids_for(thread_id):
    return [dict(r) for r in con().execute("SELECT * FROM bids WHERE thread_id=?", (thread_id,))]
