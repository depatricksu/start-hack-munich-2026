"""The self-improvement loop: watch our leaderboard total, explain every change, update the odds of each pricing rule.

    python3 -m learn.loop            # run next to the clerk (read-only: it never sends mail, never writes to the clerk DB)

Every ~15 s: GET /v1/board/me. A change of our total is classified (round / tracking bonus / hourly cost points), a round
is explained against the options and bids we stored for it, and the odds of each candidate rule are updated (learn/analyze.py).
Output: one line per event on screen and in data/learning.jsonl; odds in data/learn_odds.json.
"""
import json, os, sqlite3, sys, time, urllib.request
from datetime import datetime

from core import config
from . import analyze as A
from . import scorer as S

OUT = os.path.join(config.ROOT, "data", "learning.jsonl")
ODDS = os.path.join(config.ROOT, "data", "learn_odds.json")


def api(path):
    req = urllib.request.Request(config.BASE_URL + path, headers={"X-API-Key": config.API_KEY})
    return json.load(urllib.request.urlopen(req, timeout=15))


def epoch(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def db():
    return sqlite3.connect("file:%s?mode=ro" % config.DB_PATH, uri=True, timeout=5)


def session_for(sent_iso):
    """The request we received at this round's send time (they match to the millisecond)."""
    c = db(); c.row_factory = sqlite3.Row
    r = c.execute("SELECT * FROM sessions WHERE abs(received_at - ?) < 10", (epoch(sent_iso),)).fetchone()
    if not r:
        return None
    j = lambda x: json.loads(x) if x else None
    return {"thread_id": r["thread_id"], "fields": j(r["fields"]) or {}, "options": j(r["options"]) or [], "chosen": j(r["chosen"])}


def tracking_answers_since(ts):
    c = db()
    n = c.execute("SELECT COUNT(*) FROM events WHERE kind='tracking_lookup' AND ts>? AND data LIKE '%\"matched\": true%'", (ts,)).fetchone()[0]
    return n > 0


def load_odds():
    try:
        return json.load(open(ODDS))
    except Exception:
        return {r: 1 / len(A.RULES) for r in A.RULES}


def log(rec):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    rec["at"] = time.strftime("%H:%M:%S")
    open(OUT, "a").write(json.dumps(rec, default=str) + "\n")
    print(json.dumps(rec, default=str), flush=True)


def step(state):
    me = api("/v1/board/me")
    total = float(me["total"])
    mine = {r["round_no"]: r for r in me["requests"]}
    answered = []
    for rn, r in mine.items():
        was = state["verdicts"].get(rn, "open")
        if was == "open" and r["verdict"] != "open" and r.get("answered_at"):
            answered.append((rn, S.seconds_between(r["sent_at"], r["answered_at"])))
    delta = round(total - state["total"], 2)
    if abs(delta) > 0.005 or answered:
        c = A.classify_change(delta, answered, tracking_answers_since(state["ts"]))
        rec = {"delta": delta, "total": total, "rank": me.get("rank"), **c}
        if c["kind"] == "round":
            s = session_for(mine[c["round"]]["sent_at"])
            if s and s["chosen"]:
                quote = float(s["chosen"].get("total_eur") or s["chosen"]["total"])
                ex = A.explain(quote, c["accuracy"], s)
                state["odds"] = A.update_odds(state["odds"], ex["rule_errors"])
                rec.update(thread=s["thread_id"], quote=quote, verdict=A.verdict(ex["rule_errors"], c["accuracy"]), odds=state["odds"], **ex)
                os.makedirs(os.path.dirname(ODDS), exist_ok=True)
                json.dump(state["odds"], open(ODDS, "w"))
        log(rec)
    state["total"], state["ts"] = total, time.time()
    state["verdicts"] = {rn: r["verdict"] for rn, r in mine.items()}


def main(every=15, forever=True):
    if not config.API_KEY:
        sys.exit("FIVEU_API_KEY is missing (.env)")
    me = api("/v1/board/me")
    state = {"total": float(me["total"]), "ts": time.time(), "odds": load_odds(),
             "verdicts": {r["round_no"]: r["verdict"] for r in me["requests"]}}
    print("learn.loop started: total %.2f, rounds seen %s" % (state["total"], sorted(state["verdicts"])), flush=True)
    while forever:
        try:
            step(state)
        except Exception as e:
            print("learn.loop error:", e, flush=True)
        time.sleep(every)


if __name__ == "__main__":
    main()
