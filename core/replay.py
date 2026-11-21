"""Replay: run every saved real request through the CURRENT code and compare with what we quoted live.

    python3 -m core.share --get      # fetch the runner's snapshot first
    python3 -m core.replay           # or: python3 -m core.replay path/to/snapshot.db

No key and no network. For each request it takes from the snapshot:
  the customer's mail, the form the LLM filled live, the portal prices we got live, the bid answers we got live
and lets today's code do everything else again: router, gate, sheet prices, weight break, bid pick, total, reply.
Then it prints old quote vs new quote vs the points 5U gave. Read it like this:
  same     today's code quotes the same price as live
  CHANGED  today's code quotes a different price. Good if that round lost points, bad if it scored full.
  LOST     live we quoted, today's code would send nothing. Look at it before going live.
  FIXED    live we sent nothing, today's code would quote.
Limits: portal prices are the recorded ones (so a new weight-break read is not replayed), and bids are only
the answers recorded live.
"""
import json, os, sqlite3, sys, tempfile, time

SNAP = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "replay.db")
os.environ.update(DRY_RUN="1", LLM_FAKE="1", FIVEU_API_KEY="", BID_EXPERIMENT="0", CLARIFY="0")

from . import config, db, main, mailbox  # noqa: E402
from sourcing import bids, portal        # noqa: E402

FULL = 60                                # price 45 + time 15: a round that scored this must not change


def _json(x, default):
    try:
        return json.loads(x) if x else default
    except ValueError:
        return default


def load(path):
    """Everything we recorded live, per request thread."""
    copy = os.path.join(tempfile.mkdtemp(), "snapshot.db")   # work on a copy: never touch the source (it may be live)
    src, c = sqlite3.connect(path), sqlite3.connect(copy)
    with c:
        src.backup(c)
    src.close()
    c.row_factory = sqlite3.Row
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    out = []
    for m in c.execute("SELECT * FROM mails WHERE route='rfq' ORDER BY id"):
        tid = m["thread_id"]
        s = c.execute("SELECT * FROM sessions WHERE thread_id=?", (tid,)).fetchone()
        llm = c.execute("SELECT data FROM events WHERE thread_id=? AND kind='llm' ORDER BY id LIMIT 1", (tid,)).fetchone()
        if not s or not llm:
            continue                                         # expired or crashed before the LLM: nothing to replay
        opts = [o for r in c.execute("SELECT data FROM events WHERE thread_id=? AND kind='options' ORDER BY id", (tid,))
                for o in _json(r["data"], {}).get("options", [])]
        board = (c.execute("SELECT round, verdict, reason, points FROM board_results WHERE thread_id=?", (tid,)).fetchone()
                 if "board_results" in tables else None)
        out.append({"mail": _json(m["raw"], {}), "tid": tid, "session": dict(s),
                    "fields": _json(llm["data"], {}).get("fields") or {},
                    "portal": [o for o in opts if o.get("source") == "portal"],
                    "bids": [dict(b) for b in c.execute("SELECT * FROM bids WHERE thread_id=?", (tid,))]
                    if "bids" in tables else [], "board": dict(board) if board else None})
    return out


def _price(session):
    ch = _json(session.get("chosen"), None)
    return (ch.get("total"), ch.get("currency"), ch.get("airline")) if ch else (None, None, None)


def replay_one(rec):
    """Push one recorded request through today's code. Returns the new session row."""
    mail = mailbox.normalize(rec["mail"])
    mail["received_at"] = time.time()                        # it is not expired: we replay it as if it just came in
    recorded_portal = rec["portal"]
    main.llm.extract = lambda m: (json.loads(json.dumps(rec["fields"])), {"replayed": True})
    portal.options = lambda *a, **k: [dict(o) for o in recorded_portal
                                      if "trucker" not in o]   # live options had the trucker leg added later
    main.process(mail)
    by_mail = {(b.get("email") or "").lower(): b for b in rec["bids"]}
    for row in bids.rows(rec["tid"]):                        # give every bid we asked for its live answer
        live = by_mail.get(row["email"])
        if live and live.get("replied_at"):
            db.con().execute("UPDATE bids SET replied_at=?, total=?, currency=?, transit_days=?, hours=?, total_eur=?, status=?, note=? WHERE id=?",
                             (time.time(), live.get("total"), live.get("currency"), live.get("transit_days"),
                              live.get("hours"), live.get("total_eur"), live.get("status") or "ok", live.get("note"), row["id"]))
    s = db.session(rec["tid"])
    if s and s["status"] == "waiting_bids":
        db.update_session(rec["tid"], deadline=time.time() - 1, received_at=time.time() - config.BID_MAX_WAIT_S - 1)
        main.tick()
    return db.session(rec["tid"]) or {}


def run(path, quiet=False):
    """Returns (rows, regressions). A regression = a round that scored full live and would now change or be lost."""
    rows, bad = [], 0
    real_event, db.event = db.event, (lambda *a, **k: None) if quiet else db.event
    try:
        for rec in load(path):
            try:
                new = replay_one(rec)
            except Exception as e:
                new = {"status": "error", "note": str(e)}
            old_total, cur, old_air = _price(rec["session"])
            new_total, _, new_air = _price(new)
            pts = rec["board"]["points"] if rec["board"] else None
            if old_total and not new_total:
                verdict = "LOST"
            elif new_total and not old_total:
                verdict = "FIXED"
            elif old_total == new_total:
                verdict = "same"
            else:
                verdict = "CHANGED"
            regress = verdict in ("LOST", "CHANGED") and pts is not None and pts >= FULL
            bad += regress
            rows.append({"thread": rec["tid"], "round": rec["board"]["round"] if rec["board"] else "?", "points": pts,
                         "old": "%s %s" % (old_total, old_air) if old_total else rec["session"].get("status"),
                         "new": "%s %s" % (new_total, new_air) if new_total else "%s (%s)" % (new.get("status"), (new.get("note") or "")[:60]),
                         "verdict": verdict + (" !! scored full live" if regress else "")})
    finally:
        db.event = real_event
    return rows, bad


def main_cli():
    path = SNAP or os.path.join(config.ROOT, "examples", "real", "snapshot.db")
    if not os.path.exists(path):
        sys.exit("No snapshot at %s. Fetch it first: python3 -m core.share --get" % path)
    rows, bad = run(path, quiet="-v" not in sys.argv)
    print("%-7s %-6s %-7s %-34s %-44s %s" % ("thread", "round", "points", "quoted live", "today's code", "result"))
    for r in rows:
        print("%-7s %-6s %-7s %-34s %-44s %s" % (r["thread"], r["round"], "-" if r["points"] is None else "%.1f" % r["points"],
                                                str(r["old"])[:34], str(r["new"])[:44], r["verdict"]))
    count = lambda v: sum(1 for r in rows if r["verdict"].startswith(v))   # noqa: E731
    print("\n%d requests: %d same, %d changed, %d lost, %d fixed. Rounds that scored full and would now change: %d" % (
        len(rows), count("same"), count("CHANGED"), count("LOST"), count("FIXED"), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main_cli()
