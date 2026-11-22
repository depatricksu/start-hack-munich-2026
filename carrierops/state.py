"""carrierops' own tables, the DB connection and the shipment state machine.

The clerk's DB is ATTACHed read-only as `clerk` (mode=ro), so carrierops cannot write a clerk table even by
mistake. Our own tables live in the main DB: the same file by default, or a separate file with --ops-db.

Shipment status (status column):
    confirmed -> picked_up -> handed_over -> departed -> arrived -> delivered          (milestones, never go back)
    delayed / offloaded / rebooked                                                      (exceptions, until delivered)
    cancelled_by_airline -> rebook_requested -> confirmed (the airline confirms the new flight)
    cancelled (the customer cancelled, or the airline confirmed our cancellation)
delivered and cancelled are final: later mails are stored and logged but do not change the status.
"""
import contextlib, json, os, sqlite3, time


def _q(path):
    """Quote a file path for an SQLite URI (no urllib: carrierops imports nothing network-related)."""
    return path.replace("%", "%25").replace("?", "%3f").replace("#", "%23")

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipment_state(
  thread_id INTEGER PRIMARY KEY, booking_ref TEXT, our_ref TEXT, airline TEXT, airline_email TEXT, airline_code TEXT,
  trucker TEXT, trucker_email TEXT, customer TEXT, customer_name TEXT, company TEXT, language TEXT, subject TEXT,
  lane TEXT, origin TEXT, destination TEXT, weight_kg REAL, volume_cbm REAL, pickup TEXT, goods TEXT, ready TEXT,
  quote_total TEXT, flight_quote TEXT, trucker_quote TEXT, currency TEXT, airline_price TEXT,
  status TEXT, milestone TEXT, eta_planned TEXT, eta_current TEXT, awb TEXT, flight TEXT, tracking_url TEXT,
  picked_up_at TEXT, departed_at TEXT, arrived_at TEXT, delivered_at TEXT, offer_flight TEXT, offer_date TEXT,
  last_customer_mail_id INTEGER, confirmed_at REAL, informed_at REAL, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS shipment_updates(
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, mail_id INTEGER, source TEXT, sender TEXT, type TEXT,
  ui_type TEXT, match TEXT, summary TEXT, new_eta TEXT, flight TEXT, awb TEXT, delay_hours REAL,
  status_after TEXT, eta_after TEXT, raw TEXT, at REAL);
CREATE UNIQUE INDEX IF NOT EXISTS shipment_updates_once ON shipment_updates(mail_id, source) WHERE mail_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, booking_ref TEXT, party TEXT, to_addr TEXT, subject TEXT,
  body TEXT, reason TEXT, in_reply_to INTEGER, update_id INTEGER,
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','sent','cancelled')),
  created_at REAL, dedupe_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS ops_invoices(
  thread_id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer TEXT, amount TEXT, currency TEXT, lines TEXT,
  language TEXT, status TEXT, issued_at REAL, due_at REAL, reminders INTEGER DEFAULT 0, last_reminder_at REAL,
  paid_reported_at REAL, paid_at REAL, outbox_id INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS carrier_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, carrier TEXT, thread_id INTEGER, mail_id INTEGER, kind TEXT,
  delay_hours REAL, detail TEXT, at REAL, dedupe_key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS carrierops_cursor(name TEXT PRIMARY KEY, value TEXT, updated_at REAL);
CREATE TABLE IF NOT EXISTS carrierops_seen(mail_id INTEGER PRIMARY KEY, result TEXT, at REAL);
"""
OWN_TABLES = ("shipment_state", "shipment_updates", "outbox", "ops_invoices", "carrier_log", "carrierops_cursor",
              "carrierops_seen")

MILESTONES = ("confirmed", "picked_up", "handed_over", "departed", "arrived", "delivered")
RANK = {m: i for i, m in enumerate(MILESTONES)}
EXCEPTIONS = ("delayed", "offloaded", "rebooked")
FINAL = ("delivered", "cancelled")
ACTIVE_NOT = ("delivered", "cancelled")


def connect(db_path, ops_db=None):
    """Open our own DB (ops_db or the same file) and ATTACH the clerk DB read-only as `clerk`."""
    if not os.path.exists(db_path):
        raise SystemExit("carrierops: no such DB: %s" % db_path)
    con = sqlite3.connect(ops_db or db_path, isolation_level=None, uri=True, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=10000")
    same = not ops_db or os.path.abspath(ops_db) == os.path.abspath(db_path)
    if same and con.execute("PRAGMA main.journal_mode").fetchone()[0].lower() != "wal":
        # Our write and the read-only clerk handle are two handles on one file: without WAL the reader blocks our
        # commit. The clerk always runs in WAL (core/db.py). We never switch the clerk's journal mode ourselves.
        con.close()
        raise SystemExit("carrierops: %s is not in WAL mode; use --ops-db FILE to keep our tables apart" % db_path)
    con.execute("ATTACH DATABASE ? AS clerk", ("file:%s?mode=ro" % _q(os.path.abspath(db_path)),))
    con.executescript(SCHEMA)
    return con


@contextlib.contextmanager
def tx(con):
    """One transaction: everything for one mail (and the cursor) commits together or not at all."""
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def clerk_has(con, table):
    return con.execute("SELECT 1 FROM clerk.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]


def one(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return dict(r) if r else None


def jload(s, default=None):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ cursor
def get_cursor(con, name="mail_id", default=0):
    r = one(con, "SELECT value FROM carrierops_cursor WHERE name=?", (name,))
    return int(r["value"]) if r else default


def set_cursor(con, value, name="mail_id", now=None):
    con.execute("INSERT OR REPLACE INTO carrierops_cursor(name,value,updated_at) VALUES(?,?,?)",
                (name, str(value), now or time.time()))


def mark_seen(con, mail_id, result, now):
    con.execute("INSERT OR REPLACE INTO carrierops_seen(mail_id,result,at) VALUES(?,?,?)", (mail_id, str(result)[:200], now))


# ------------------------------------------------------------------ shipments
def shipment(con, thread_id):
    return one(con, "SELECT * FROM shipment_state WHERE thread_id=?", (thread_id,))


def active_shipments(con):
    return rows(con, "SELECT * FROM shipment_state WHERE status NOT IN (%s)" % ",".join("?" * len(ACTIVE_NOT)), ACTIVE_NOT)


def save_shipment(con, thread_id, now, **cols):
    cols["updated_at"] = now
    if shipment(con, thread_id):
        con.execute("UPDATE shipment_state SET %s WHERE thread_id=?" % ",".join("%s=?" % k for k in cols),
                    list(cols.values()) + [thread_id])
    else:
        cols.update(thread_id=thread_id, created_at=now)
        con.execute("INSERT INTO shipment_state(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))),
                    list(cols.values()))


def next_status(status, milestone, typ):
    """The state machine: (status, milestone, update type) -> (new status, new milestone)."""
    milestone = milestone or "confirmed"
    if status in FINAL:
        return status, milestone
    if typ == "confirmed":
        if status in ("cancelled_by_airline", "rebook_requested"):
            return "confirmed", milestone
        return status, milestone
    if typ in RANK:
        if RANK[typ] > RANK.get(milestone, 0):
            return typ, typ
        return status, milestone                     # an older milestone arriving late never moves us back
    if typ in EXCEPTIONS:
        return typ, milestone
    if typ == "cancelled":
        return "cancelled_by_airline", milestone
    if typ == "cancel_confirmed":
        return "cancelled", milestone
    if typ in ("rebook_requested", "cancelled_by_customer"):
        return ("rebook_requested" if typ == "rebook_requested" else "cancelled"), milestone
    return status, milestone


def add_update(con, thread_id, mail_id, source, typ, now, sender=None, ui_type=None, match=None, summary=None,
               new_eta=None, flight=None, awb=None, delay_hours=None, status_after=None, eta_after=None, raw=None):
    cur = con.execute(
        "INSERT OR IGNORE INTO shipment_updates(thread_id,mail_id,source,sender,type,ui_type,match,summary,new_eta,flight,"
        "awb,delay_hours,status_after,eta_after,raw,at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (thread_id, mail_id, source, sender, typ, ui_type, match, summary, new_eta, flight, awb, delay_hours,
         status_after, eta_after, (raw or "")[:600], now))
    return cur.lastrowid if cur.rowcount else None


# ------------------------------------------------------------------ outbox (drafts only) and carrier log
def draft(con, thread_id, party, to_addr, subject, body, reason, key, now, in_reply_to=None, booking_ref=None,
          update_id=None):
    """Put one message into the outbox as a draft. Same dedupe_key twice = stored once. Never sends."""
    cur = con.execute(
        "INSERT OR IGNORE INTO outbox(thread_id,booking_ref,party,to_addr,subject,body,reason,in_reply_to,update_id,"
        "status,created_at,dedupe_key) VALUES(?,?,?,?,?,?,?,?,?,'draft',?,?)",
        (thread_id, booking_ref, party, to_addr or "", subject, body, reason, in_reply_to, update_id, now, key))
    return cur.lastrowid if cur.rowcount else None


def log_carrier(con, carrier, thread_id, kind, now, key, delay_hours=None, detail=None, mail_id=None):
    """Step 10: collect only. Nothing reads this table for pricing or choosing carriers."""
    con.execute("INSERT OR IGNORE INTO carrier_log(carrier,thread_id,mail_id,kind,delay_hours,detail,at,dedupe_key) "
                "VALUES(?,?,?,?,?,?,?,?)", (carrier, thread_id, mail_id, kind, delay_hours, (detail or "")[:400], now, key))
