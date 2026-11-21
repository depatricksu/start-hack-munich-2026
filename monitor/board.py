"""Watch our own score: /v1/board/me -> verdict per request, matched to our sessions. Runs NEXT TO the runner.

    python -m monitor.board            # every BOARD_POLL_S (60) seconds, on the runner machine (needs the key + DB)
    python -m monitor.board --once     # one read, prints verdicts and reasons

Why: 5U changes the setup about once an hour without telling us; we only see it as rejected quotes.
This stores each verdict in table `board_results` next to our session and logs:
  board_verdict  one per request when its verdict changes (accepted / rejected / ...), with the reason code
  board_alert    when ALERT_N of the last ALERT_WINDOW finished requests were rejected for the same reason
5U's field names are not fixed in the spec, so several spellings are accepted.
"""
import datetime as dt, json, os, sys, time
from collections import Counter

from core import config, db, mailbox

POLL_S = float(os.environ.get("BOARD_POLL_S", "60"))
ALERT_WINDOW, ALERT_N = 6, 3
FINAL = ("accepted", "rejected", "no answer", "voided")

SCHEMA = """CREATE TABLE IF NOT EXISTS board_results(round TEXT PRIMARY KEY, thread_id INTEGER, verdict TEXT,
  reason TEXT, points REAL, booked INTEGER, sent_at REAL, raw TEXT, updated_at REAL);"""


def con():
    c = db.con()
    c.executescript(SCHEMA)
    return c


def _get(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def _ts(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def rows_of(data):
    if isinstance(data, list):
        return data
    for k in ("requests", "results", "rounds", "items", "data"):
        if isinstance(data, dict) and isinstance(data.get(k), list):
            return data[k]
    return []


def normalize(r):
    pts = _get(r, "points", "score", "total")
    if isinstance(pts, dict):
        pts = sum(v for v in pts.values() if isinstance(v, (int, float)))
    return {
        "round": str(_get(r, "round", "round_id", "request_id", "id")),
        "verdict": (str(_get(r, "verdict", "status", "result") or "")).lower(),
        "reason": _get(r, "reason_code", "reason", "code"),
        "points": pts,
        "booked": bool(_get(r, "booked", "is_booked")),
        "sent_at": _ts(_get(r, "sent_at", "sent", "request_sent_at", "created_at")),
        "mail_id": _get(r, "message_id", "mail_id", "request_message_id", "rfq_message_id", "thread_id"),
        "raw": r,
    }


def match_thread(n):
    """Our session for this request: by mail id if 5U gives one, else the session received closest to sent_at."""
    c = con()
    if n["mail_id"] is not None:
        row = c.execute("SELECT thread_id FROM sessions WHERE thread_id=?", (n["mail_id"],)).fetchone()
        if row:
            return row["thread_id"]
    if n["sent_at"]:
        row = c.execute("SELECT thread_id, ABS(received_at-?) AS d FROM sessions ORDER BY d LIMIT 1",
                        (n["sent_at"],)).fetchone()
        if row and row["d"] <= 30:
            return row["thread_id"]
    return None


def ingest(data):
    """Store all results; return list of (normalized, changed: bool)."""
    c, out = con(), []
    for r in rows_of(data):
        n = normalize(r)
        if n["round"] == "None":
            continue
        old = c.execute("SELECT verdict FROM board_results WHERE round=?", (n["round"],)).fetchone()
        tid = match_thread(n)
        c.execute("INSERT OR REPLACE INTO board_results(round, thread_id, verdict, reason, points, booked, sent_at, raw,"
                  " updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (n["round"], tid, n["verdict"], n["reason"], n["points"], int(n["booked"]), n["sent_at"],
                   json.dumps(n["raw"], default=str), time.time()))
        changed = not old or old["verdict"] != n["verdict"]
        if changed:
            db.event("board_verdict", tid, None, round=n["round"], verdict=n["verdict"], reason=n["reason"],
                     points=n["points"])
        out.append((n, changed))
    return out


def alert():
    """Same rejection reason piling up in the latest finished requests -> something changed at 5U."""
    rows = con().execute("SELECT verdict, reason FROM board_results WHERE verdict IN (%s) ORDER BY sent_at DESC LIMIT ?"
                         % ",".join("?" * len(FINAL)), (*FINAL, ALERT_WINDOW)).fetchall()
    reasons = Counter(r["reason"] or "?" for r in rows if r["verdict"] == "rejected")
    if reasons:
        reason, n = reasons.most_common(1)[0]
        if n >= ALERT_N:
            return {"reason": reason, "rejected": n, "of_last": len(rows)}
    return None


def summary():
    c = con()
    by = c.execute("SELECT verdict, COUNT(*) n, SUM(points) p FROM board_results GROUP BY verdict").fetchall()
    why = c.execute("SELECT reason, COUNT(*) n FROM board_results WHERE verdict='rejected' GROUP BY reason "
                    "ORDER BY n DESC").fetchall()
    lines = ["%-10s %3d  %7.1f pts" % (r["verdict"], r["n"], r["p"] or 0) for r in by]
    lines += ["  rejected: %-30s %d" % (r["reason"], r["n"]) for r in why]
    return "\n".join(lines) or "no results yet"


def tick():
    status, data = mailbox.api("GET", "/v1/board/me")
    if status != 200:
        db.event("board_error", status=status, detail=str(data)[:200])
        return
    ingest(data)
    a = alert()
    if a:
        db.event("board_alert", **a)


def run(once=False):
    if not config.API_KEY:
        sys.exit("FIVEU_API_KEY is missing (.env). Run this on the runner machine.")
    while True:
        try:
            tick()
        except Exception as e:
            db.event("board_error", error=str(e))
        if once:
            return print(summary())
        time.sleep(POLL_S)


if __name__ == "__main__":
    run(once="--once" in sys.argv)
