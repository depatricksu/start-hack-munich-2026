"""Carrier reliability: which airline, trucker or rate desk keeps causing trouble. Owner: Patrick.

    python3 -m monitor.carriers            # scorecard, flagged carriers first, with the requests behind each issue
    python3 -m monitor.carriers --all      # also carriers with too few jobs to judge
    python3 -m monitor.carriers --save     # same, and write table carrier_flags (+ carrier_flagged events)
    python3 -m monitor.carriers --watch    # own Terminal on the runner: refresh carrier_flags every 10 min
    DB_PATH=examples/real/snapshot.db python3 -m monitor.carriers     # on the runner's real data

Read only for pricing: nothing here changes which carrier we quote. It tells the forwarder who to watch.

What counts as an issue (each one is kept with its request id, so the forwarder can open it):
  no_answer       a price request with no answer after NO_ANSWER_S (default 300 s)
  late_answer     an answer after LATE_S (default 90 s, our bid wait): it arrived too late to be used
  send_failed     our request mail to them bounced or failed
  price_above     the airline booked above the rate we quoted from (we had to ask the customer again)
  cancelled       the airline cancelled or refused a booking
  unconfirmed     a booking with no confirmation after UNCONFIRMED_S (default 1800 s)
  slow_confirm    confirmed, but after more than SLOW_CONFIRM_S (default 600 s)
Not issues: "we do not serve this lane" (normal coverage), answers our own reader could not use (counted apart as
`unreadable`: that is usually our parser, not the carrier).

Flag levels (only with at least MIN_JOBS jobs, default 5):
  red    issue rate >= RED_RATE (30%), or 2+ cancellations, or 2+ bookings above the quote
  amber  issue rate >= AMBER_RATE (15%), or 1 cancellation / booking above the quote
Where it shows:
  table `carrier_flags`   one row per carrier (level, reasons, example requests): for the control room
  event `carrier_flagged` when a carrier turns red or amber (and `carrier_cleared` when it recovers)
  session note            booking with a red carrier: booking/handlers.py adds "WATCH CARRIER ..." to the request
                          (and logs `carrier_watch` on it), so it shows on that shipment
"""
import json, os, sys, time
from collections import defaultdict

from core import db

NO_ANSWER_S = float(os.environ.get("CARRIER_NO_ANSWER_S", "300"))
LATE_S = float(os.environ.get("CARRIER_LATE_S", "90"))
UNCONFIRMED_S = float(os.environ.get("CARRIER_UNCONFIRMED_S", "1800"))
SLOW_CONFIRM_S = float(os.environ.get("CARRIER_SLOW_CONFIRM_S", "600"))
MIN_JOBS = int(os.environ.get("CARRIER_MIN_JOBS", "5"))
RED_RATE, AMBER_RATE = 0.30, 0.15
REFRESH_S = float(os.environ.get("CARRIER_REFRESH_S", "600"))
SERIOUS = ("cancelled", "price_above")
LABEL = {
    "no_answer": "no answer to our price request",
    "late_answer": "answered after our bid wait (too late to use)",
    "send_failed": "our request mail to them failed",
    "price_above": "booked above the quoted rate",
    "cancelled": "cancelled or refused a booking",
    "unconfirmed": "booking never confirmed",
    "slow_confirm": "slow booking confirmation",
}

SCHEMA = """CREATE TABLE IF NOT EXISTS carrier_flags(carrier TEXT PRIMARY KEY, role TEXT, level TEXT, jobs INTEGER,
  issues INTEGER, issue_rate REAL, reasons TEXT, examples TEXT, stats TEXT, updated_at REAL);"""
_last_refresh = 0.0


def con():
    c = db.con()
    c.executescript(SCHEMA)
    return c


def _tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _new():
    return {"role": None, "jobs": 0, "asked": 0, "answered": 0, "declined": 0, "unreadable": 0, "bookings": 0,
            "confirmed": 0, "answer_s": [], "issues": defaultdict(list)}


def scorecard(c=None, now=None):
    """-> list of dicts, one per carrier, worst first. Pure read of bids, bookings and events."""
    c, now = c or db.con(), now or time.time()
    tables, cards = _tables(c), defaultdict(_new)
    bid_cols = {r[1] for r in c.execute("PRAGMA table_info(bids)")} if "bids" in tables else set()
    if {"role", "status"} <= bid_cols:
        for b in c.execute("SELECT thread_id, carrier, role, status, requested_at, replied_at FROM bids "
                           "WHERE carrier IS NOT NULL AND requested_at IS NOT NULL"):
            k = cards[b["carrier"]]
            k["role"] = k["role"] or b["role"]
            k["jobs"] += 1
            k["asked"] += 1
            if b["status"] == "send_failed":
                k["issues"]["send_failed"].append(b["thread_id"])
            elif b["replied_at"] is None:
                if now - b["requested_at"] > NO_ANSWER_S:
                    k["issues"]["no_answer"].append(b["thread_id"])
                else:
                    k["jobs"] -= 1                                   # still within its time: not judged yet
            else:
                k["answered"] += 1
                secs = b["replied_at"] - b["requested_at"]
                k["answer_s"].append(secs)
                if secs > LATE_S:
                    k["issues"]["late_answer"].append(b["thread_id"])
                if b["status"] == "declined":
                    k["declined"] += 1
                elif b["status"] == "unclear":
                    k["unreadable"] += 1
    if "bookings" in tables:
        for b in c.execute("SELECT thread_id, airline, status, booked_at, confirmed_at, created_at FROM bookings "
                           "WHERE airline IS NOT NULL"):
            k = cards[b["airline"]]
            k["role"] = k["role"] or "airline"
            k["jobs"] += 1
            k["bookings"] += 1
            start = b["booked_at"] or b["created_at"]
            if b["status"] == "cancelled_by_airline":
                k["issues"]["cancelled"].append(b["thread_id"])
            elif b["confirmed_at"]:
                k["confirmed"] += 1
                if start and b["confirmed_at"] - start > SLOW_CONFIRM_S:
                    k["issues"]["slow_confirm"].append(b["thread_id"])
            elif b["status"] in ("booked", "requested") and start and now - start > UNCONFIRMED_S:
                k["issues"]["unconfirmed"].append(b["thread_id"])
        airline_of = {r[0]: r[1] for r in c.execute("SELECT thread_id, airline FROM bookings")}
        for e in c.execute("SELECT thread_id FROM events WHERE kind='booking_price_changed'"):
            a = airline_of.get(e["thread_id"])
            if a:
                cards[a]["issues"]["price_above"].append(e["thread_id"])
    out = []
    for name, k in cards.items():
        n_issues = sum(len(v) for v in k["issues"].values())
        rate = n_issues / k["jobs"] if k["jobs"] else 0.0
        serious = {s: len(k["issues"][s]) for s in SERIOUS if k["issues"].get(s)}
        if k["jobs"] < MIN_JOBS and not serious:
            level = "unknown"
        elif rate >= RED_RATE or any(v >= 2 for v in serious.values()):
            level = "red"
        elif rate >= AMBER_RATE or serious:
            level = "amber"
        else:
            level = "ok"
        times = sorted(k["answer_s"])
        out.append({
            "carrier": name, "role": k["role"] or "?", "level": level, "jobs": k["jobs"], "issues": n_issues,
            "issue_rate": round(rate, 3),
            "reasons": ["%s x%d" % (LABEL[i], len(v)) for i, v in sorted(k["issues"].items(), key=lambda x: -len(x[1])) if v],
            "examples": {i: sorted(set(v))[-5:] for i, v in k["issues"].items() if v},
            "stats": {"asked": k["asked"], "answered": k["answered"], "declined_lane": k["declined"],
                      "unreadable": k["unreadable"], "bookings": k["bookings"], "confirmed": k["confirmed"],
                      "median_answer_s": round(times[len(times) // 2], 1) if times else None},
        })
    order = {"red": 0, "amber": 1, "ok": 2, "unknown": 3}
    return sorted(out, key=lambda r: (order[r["level"]], -r["issue_rate"], -r["jobs"]))


def refresh(now=None):
    """Write the scorecard to `carrier_flags`; log `carrier_flagged` / `carrier_cleared` when a level changes."""
    c = con()
    old = {r["carrier"]: r["level"] for r in c.execute("SELECT carrier, level FROM carrier_flags")}
    cards = scorecard(c, now)
    for r in cards:
        c.execute("INSERT OR REPLACE INTO carrier_flags(carrier,role,level,jobs,issues,issue_rate,reasons,examples,stats,"
                  "updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (r["carrier"], r["role"], r["level"], r["jobs"], r["issues"], r["issue_rate"],
                   json.dumps(r["reasons"]), json.dumps(r["examples"]), json.dumps(r["stats"]), time.time()))
        was = old.get(r["carrier"], "unknown")
        if r["level"] in ("red", "amber") and was != r["level"]:
            db.event("carrier_flagged", carrier=r["carrier"], role=r["role"], level=r["level"], was=was,
                     reasons=r["reasons"], examples=r["examples"])
        elif r["level"] == "ok" and was in ("red", "amber"):
            db.event("carrier_cleared", carrier=r["carrier"], role=r["role"], was=was)
    return cards


def flag(carrier):
    """The stored flag for one carrier: {"level", "reasons"} or None. Cheap: one row from `carrier_flags`."""
    if not carrier:
        return None
    try:
        r = con().execute("SELECT level, reasons FROM carrier_flags WHERE lower(carrier)=lower(?)", (carrier,)).fetchone()
    except Exception:
        return None
    return {"level": r["level"], "reasons": json.loads(r["reasons"] or "[]")} if r else None


def watch_note(*carriers):
    """'WATCH CARRIER Kestrel Airways (red): no answer ... x9' for every red carrier among these, or ''.
    Refreshes the flags first when they are older than REFRESH_S (the scorecard is a fast read)."""
    tick()
    notes = []
    for name in carriers:
        f = flag(name)
        if f and f["level"] == "red":
            notes.append("WATCH CARRIER %s (red): %s" % (name, "; ".join(f["reasons"][:3])))
    return " | ".join(notes)


def tick():
    """Refreshes the flags every REFRESH_S (also from another process: the newest row's time decides).
    Never raises: callers are the booking flow and `--watch`."""
    global _last_refresh
    if time.time() - _last_refresh < REFRESH_S:
        return
    try:
        newest = con().execute("SELECT max(updated_at) FROM carrier_flags").fetchone()[0]
        if newest and time.time() - newest < REFRESH_S:
            _last_refresh = newest
            return
    except Exception:
        pass
    _last_refresh = time.time()
    try:
        refresh()
    except Exception as e:
        db.event("carrier_refresh_error", error=str(e))


def main(argv):
    if "--watch" in argv:                                        # own Terminal: keep carrier_flags fresh for the UI
        while True:
            for r in refresh():
                pass
            time.sleep(REFRESH_S)
    cards = refresh() if "--save" in argv else scorecard()
    shown = [r for r in cards if "--all" in argv or r["level"] != "unknown"]
    mark = {"red": "RED  ", "amber": "AMBER", "ok": "ok   ", "unknown": "?    "}
    print("%-5s %-28s %-9s %5s %6s %6s %8s  %s" % ("flag", "carrier", "role", "jobs", "issues", "rate", "answer", "reasons"))
    for r in shown:
        s = r["stats"]
        print("%-5s %-28s %-9s %5d %6d %5.0f%% %7ss  %s" % (
            mark[r["level"]], r["carrier"][:28], r["role"][:9], r["jobs"], r["issues"], 100 * r["issue_rate"],
            s["median_answer_s"] if s["median_answer_s"] is not None else "-", "; ".join(r["reasons"]) or "-"))
    flagged = [r for r in cards if r["level"] in ("red", "amber")]
    if flagged:
        print("\nRequests behind the flags (open them in the control room):")
        for r in flagged:
            print("  %s: %s" % (r["carrier"], "; ".join("%s %s" % (i, ", ".join(map(str, t))) for i, t in r["examples"].items())))
    unread = [r for r in cards if r["stats"]["unreadable"]]
    if unread:
        print("\nAnswers our reader could not use (likely our parser, not the carrier): " +
              ", ".join("%s %d" % (r["carrier"], r["stats"]["unreadable"]) for r in unread))


if __name__ == "__main__":
    main(sys.argv[1:])
