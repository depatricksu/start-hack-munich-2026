"""Learn from results: per request, where did the seconds go and what did 5U say?

    python3 -m monitor.timeline            # every customer request, newest first
    python3 -m monitor.timeline --last 5   # only the last 5
    python3 -m monitor.timeline --compare  # also the public board: when the top teams got their booking

Reads our own SQLite DB (read only) and, if monitor.board ran, its board_results. No network unless --compare.
Per request it prints: route, status, the step times (llm, options, bids, quote sent) in seconds after arrival,
the chosen option vs the cheapest we saw, the 5U verdict/points/reason, and a one-line lesson.
"""
import json, sys
from core import config, db

STEPS = ("llm", "gate", "options", "multi_options", "waiting_bids", "bid_wait_over", "needs_human",
         "chosen_from_human_reply", "quote_sent", "follow_up", "booking_call", "booking_confirmed")


def _events(tid):
    return [(r["ts"], r["kind"], json.loads(r["data"] or "{}")) for r in db.con().execute(
        "SELECT ts, kind, data FROM events WHERE thread_id=? ORDER BY ts", (tid,))]


def _board(tid):
    try:
        r = db.con().execute("SELECT * FROM board_results WHERE thread_id=?", (tid,)).fetchone()
        return dict(r) if r else None
    except Exception:
        return None                                   # monitor.board never ran


def lesson(s, steps, board):
    quoted = steps.get("quote_sent")
    if s["status"] in ("needs_human",) and not quoted:
        return "NOT QUOTED: %s" % (s["note"] or "needs_human")
    if "chosen_from_human_reply" in steps:
        return "a human answered (%.0f s): automate this case" % steps["chosen_from_human_reply"]
    if quoted is None:
        return "no quote sent (status %s)" % s["status"]
    if quoted > 120:
        slow = max(((k, v) for k, v in steps.items() if k != "quote_sent" and v <= quoted), key=lambda x: x[1],
                   default=("?", 0))
        return "SLOW: quote after %.0f s (>120 s loses time points), last step before it: %s at %.0f s" % (
            quoted, slow[0], slow[1])
    if board and (board.get("verdict") or "").lower() not in ("accepted", "ok", ""):
        return "REJECTED by 5U: %s" % (board.get("reason") or board.get("verdict"))
    return "ok (quote after %.0f s)" % quoted


def report(last=None):
    rows = db.con().execute("SELECT * FROM sessions ORDER BY received_at DESC").fetchall()
    rows = [dict(r) for r in rows][:last] if last else [dict(r) for r in rows]
    if not rows:
        print("no sessions in", config.DB_PATH)
        return
    for s in rows:
        t0, evs = s["received_at"], _events(s["thread_id"])
        steps = {}
        for ts, kind, _ in evs:
            if kind in STEPS and kind not in steps:
                steps[kind] = ts - t0
        chosen = json.loads(s["chosen"] or "{}")
        options = json.loads(s["options"] or "[]")
        cheapest = min(options, key=lambda o: float(o.get("total_eur") or o.get("total") or 1e12), default=None)
        f = json.loads(s["fields"] or "{}")
        board = _board(s["thread_id"])
        print("\n=== thread %s  %s  status=%s" % (s["thread_id"], (s["subject"] or "")[:60], s["status"]))
        print("  request: %s -> %s, %s kg, %s cbm, pickup %s, prefer %s, lang %s" % (
            f.get("origin"), f.get("destination"), f.get("weight_kg_total"), f.get("volume_cbm_total"),
            f.get("pickup_postcode"), f.get("prefer"), f.get("language")))
        print("  steps (s after arrival): " + ", ".join("%s %.0f" % (k, v) for k, v in sorted(steps.items(), key=lambda x: x[1])))
        if chosen:
            print("  quoted: %s %s %s (%s)" % (chosen.get("airline"), chosen.get("total"), chosen.get("currency"),
                                              chosen.get("source")))
        if cheapest:
            print("  cheapest seen: %s %s EUR (%s), %d options" % (cheapest.get("airline"),
                  cheapest.get("total_eur") or cheapest.get("total"), cheapest.get("source"), len(options)))
        if board:
            print("  5U: verdict=%s points=%s reason=%s" % (board.get("verdict"), board.get("points"), board.get("reason")))
        if s["note"]:
            print("  note:", s["note"][:200])
        print("  LESSON:", lesson(s, steps, board))


def compare():
    """Public board: how fast the best teams got a booking after each round started."""
    from core import mailbox
    status, d = mailbox.api("GET", "/v1/board")                # same HTTP client as the runner
    if status != 200:
        return print("board: HTTP %s" % status)
    import datetime as dt
    ts = lambda x: dt.datetime.fromisoformat(x.replace("Z", "+00:00")).timestamp()
    rounds = sorted(d.get("rounds", []), key=lambda r: r["round_no"])
    print("\n=== public board: seconds from round start to each team's booking")
    for rd in rounds:
        start, end = ts(rd["sent_at"]), ts(rd["expires_at"])
        bs = [b for b in d.get("bookings", []) if start <= ts(b["booked_at"]) <= end + 600]
        print("round %s (%s/%s accepted): " % (rd["round_no"], rd["accepted"], rd["answered"]) +
              ", ".join("%s %.0f s" % (b["team"], ts(b["booked_at"]) - start) for b in sorted(bs, key=lambda b: b["booked_at"])))
    print("ranking: " + ", ".join("%s %s" % (r["team"], r["total"]) for r in d.get("ranking", [])[:8]))


if __name__ == "__main__":
    args = sys.argv[1:]
    last = int(args[args.index("--last") + 1]) if "--last" in args else None
    report(last)
    if "--compare" in args:
        compare()
