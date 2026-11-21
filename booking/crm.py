"""Our own CRM for bookings (task 04/05). 5U has no status call, so this table is the truth.

One row per customer thread. Own table, so core/db.py stays untouched.
status: requested (mail sent to airline) > booked (portal said 201) > confirmed ("Booking BK-... confirmed" arrived)
"""
import json, time
from core import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings(thread_id INTEGER PRIMARY KEY, team_reference TEXT UNIQUE, customer TEXT,
  subject TEXT, last_customer_mail_id INTEGER, rate_id TEXT, booking_reference TEXT, airline TEXT, airline_code TEXT,
  origin TEXT, destination TEXT, weight_kg REAL, volume_cbm REAL, transit_days INTEGER, price TEXT, currency TEXT,
  source TEXT, status TEXT, language TEXT, created_at REAL, booked_at REAL, confirmed_at REAL, raw TEXT);
"""
_ready = False


def con():
    global _ready
    c = db.con()
    if not _ready:
        c.executescript(SCHEMA)
        _ready = True
    return c


def team_reference(thread_id):
    return "GOOGLE-%s" % thread_id


def upsert(thread_id, **cols):
    c = con()
    if "raw" in cols and not isinstance(cols["raw"], str):
        cols["raw"] = json.dumps(cols["raw"], default=str)
    if c.execute("SELECT 1 FROM bookings WHERE thread_id=?", (thread_id,)).fetchone():
        sets = ",".join("%s=?" % k for k in cols)
        c.execute("UPDATE bookings SET %s WHERE thread_id=?" % sets, list(cols.values()) + [thread_id])
    else:
        cols = dict(cols, thread_id=thread_id, team_reference=team_reference(thread_id), created_at=time.time())
        c.execute("INSERT INTO bookings(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), list(cols.values()))


def get(thread_id):
    r = con().execute("SELECT * FROM bookings WHERE thread_id=?", (thread_id,)).fetchone()
    return dict(r) if r else None


def find(booking_reference=None, team_ref=None):
    """Find a booking by BK- reference or by our GOOGLE-<thread> reference."""
    for col, val in (("booking_reference", booking_reference), ("team_reference", team_ref)):
        if val:
            r = con().execute("SELECT * FROM bookings WHERE %s=?" % col, (val,)).fetchone()
            if r:
                return dict(r)
    return None
