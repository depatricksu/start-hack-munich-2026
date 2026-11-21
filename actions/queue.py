"""Take-over queue: a human reply typed in the UI is sent by the runner. Owner: Erik.

The UI never sends mail. It inserts a row into `actions`; `tick()` (called from the core loop) sends it through
`mailbox.send`, which respects DRY_RUN and is the only place that sends.

Table  actions(id, thread_id, kind, body, created_at, done_at, result)
kind   send_reply   send `body` to the customer in the thread. If we have not quoted yet, this IS our first
                    reply: the session is claimed so the loop never sends a second quote.
result 'sent', or 'error: ...' (the UI shows it)
"""
import time
from core import db, mailbox

SCHEMA = """CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, kind TEXT,
  body TEXT, created_at REAL, done_at REAL, result TEXT)"""

_ready = False
# Sessions where nobody has quoted yet: a human reply becomes the first (and only) quote.
_OPEN = ("needs_human", "failed", "expired", "new", "waiting_bids")


def ensure():
    global _ready
    if not _ready:
        db.con().execute(SCHEMA)
        _ready = True


def add(thread_id, kind, body):
    """Used by tests and scripts. The UI inserts the same row itself."""
    ensure()
    db.con().execute("INSERT INTO actions(thread_id,kind,body,created_at) VALUES(?,?,?,?)",
                     (thread_id, kind, body, time.time()))


def _finish(a, result):
    db.con().execute("UPDATE actions SET done_at=?, result=? WHERE id=?", (time.time(), result, a["id"]))
    db.event("human_action", a["thread_id"], action=a["kind"], result=result)


def handle(a):
    s = db.session(a["thread_id"])
    if not s:
        return _finish(a, "error: no such session")
    if a["kind"] != "send_reply":
        return _finish(a, "error: unsupported kind %s" % a["kind"])
    body = (a["body"] or "").strip()
    if not body:
        return _finish(a, "error: empty reply")
    first = s["quoted_at"] is None and s["status"] in _OPEN
    if s["status"] in ("new", "waiting_bids") and not db.claim_for_sending(s["thread_id"]):
        first = False                                        # the loop quoted in the same second: ours is a follow-up
    subject = s["subject"] if (s["subject"] or "").lower().startswith("re:") else "Re: %s" % s["subject"]
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=s["thread_id"], thread_id=s["thread_id"])
    if ok and first:
        db.update_session(s["thread_id"], status="quoted", reply=body, quoted_at=time.time(), note="sent by a human")
    _finish(a, "sent" if ok else "error: send failed")


def tick():
    """Send every pending action, oldest first. Never raises: one bad action must not stop the clerk."""
    try:
        ensure()
        for r in db.con().execute("SELECT * FROM actions WHERE done_at IS NULL ORDER BY id").fetchall():
            try:
                handle(dict(r))
            except Exception as e:
                _finish(dict(r), "error: %s" % e)
    except Exception as e:
        db.event("actions_error", error=str(e))
