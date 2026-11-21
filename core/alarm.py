"""The runner tells the team when something goes wrong, by itself, with the evidence.

    python3 -m core.alarm            # runner: own Terminal window (the supervisor also starts it)
    python3 -m core.alarm --print    # anyone: show what it would post, post nothing

Every 20 s it reads the live DB (read only, it never touches the clerk) and posts ONE comment per problem into the
agent chat (GitHub issue #2), with the customer's mail, what the LLM read, the prices, the bids and the event log:
  not_answered   a request is still open 60 s after it arrived
  needs_human    the clerk gave up on a request (or it failed / crashed)
  rejected       5U rejected our quote, or we got no answer in (needs `python3 -m monitor.board` running)
  low_score      accepted, but fewer points than a clean quote
  clerk_silent   the clerk has not polled the mailbox for 45 s
  odd_attachment a customer sent a file we cannot read or have never seen (photo, new format)
So all four agents see the problem within minutes, without asking the runner's human for data.
"""
import json, shutil, subprocess, sys, threading, time
from . import config, db, safety

CHAT_ISSUE = "2"
OPEN_AFTER_S = 60          # a request open this long is worth a look (most quotes leave in under 20 s)
SILENT_AFTER_S = 45
LOW_SCORE = 55             # a clean quote is 60 (price 45 + time 15)
MAX_PER_HOUR = 20          # never flood the chat
_posted = []


def _con():
    c = db.con()
    c.execute("CREATE TABLE IF NOT EXISTS alarms(key TEXT PRIMARY KEY, ts REAL, kind TEXT, thread_id INTEGER)")
    return c


def _first_time(key, kind, tid):
    """True only once per problem, also across restarts and with two alarm processes running."""
    return _con().execute("INSERT OR IGNORE INTO alarms(key,ts,kind,thread_id) VALUES(?,?,?,?)",
                          (key, time.time(), kind, tid)).rowcount == 1


def _short(x, n):
    x = x if isinstance(x, str) else json.dumps(x, default=str)
    return x if len(x) <= n else x[:n] + " ..."


def report(tid):
    """Everything we know about one request, as text."""
    c, out = _con(), []
    s = c.execute("SELECT * FROM sessions WHERE thread_id=?", (tid,)).fetchone()
    m = c.execute("SELECT * FROM mails WHERE id=?", (tid,)).fetchone()
    if m:
        out += ["**Customer mail** (%s, %s)" % (m["sender"], time.strftime("%H:%M:%S", time.localtime(m["received_at"]))),
                "> Subject: " + (m["subject"] or ""), "> " + _short(m["body"] or "", 900).replace("\n", "\n> ")]
    if s:
        f = json.loads(s["fields"] or "{}")
        f.pop("reply", None)
        out += ["", "**Session** status `%s`, note: %s" % (s["status"], s["note"] or "-"),
                "LLM form: `%s`" % _short(f, 700), "Chosen: `%s`" % _short(s["chosen"] or "none", 600)]
        opts = json.loads(s["options"] or "[]")
        if opts:
            out.append("Options (%d): " % len(opts) + "; ".join(
                "%s %s %s (%s, %sd%s)" % (o.get("airline"), o.get("total"), o.get("currency"), o.get("source"),
                                          o.get("transit_days"), ", billed %s kg" % o["billed_kg"] if o.get("billed_kg") else "")
                for o in opts[:12]))
    cols = {r["name"] for r in c.execute("PRAGMA table_info(bids)")}
    if "status" in cols:
        bs = c.execute("SELECT * FROM bids WHERE thread_id=?", (tid,)).fetchall()
        if bs:
            out.append("Bids: " + "; ".join("%s %s %s EUR, %s h, %s%s" % (
                b["role"], b["carrier"], b["total_eur"], b["hours"] if "hours" in cols else "?", b["status"],
                "" if b["required"] else " (experiment)") for b in bs))
    out += ["", "**Events**", "```"]
    for e in c.execute("SELECT ts, kind, data FROM events WHERE thread_id=? ORDER BY id DESC LIMIT 30", (tid,)).fetchall()[::-1]:
        out.append("%s %-18s %s" % (time.strftime("%H:%M:%S", time.localtime(e["ts"])), e["kind"], _short(e["data"], 260)))
    return "\n".join(out + ["```"])


def find():
    """All problems visible in the DB right now: (key, kind, thread_id, headline)."""
    c, now, out = _con(), time.time(), []
    for s in c.execute("SELECT thread_id, status, note, received_at FROM sessions WHERE received_at > ?", (now - 3600,)):
        tid, age = s["thread_id"], now - s["received_at"]
        if s["status"] in ("new", "waiting_bids", "sending") and OPEN_AFTER_S < age < 360:
            out.append(("open-%s" % tid, "not_answered", tid,
                        "request %s is NOT answered %d s after it arrived (status `%s`). It expires at %s." % (
                            tid, age, s["status"], time.strftime("%H:%M:%S", time.localtime(s["received_at"] + 360)))))
        if s["status"] in ("needs_human", "failed"):
            out.append(("human-%s" % tid, "needs_human", tid, "request %s went to `%s`: %s" % (tid, s["status"], s["note"])))
    for e in c.execute("SELECT thread_id, mail_id, data FROM events WHERE kind='attachments' AND ts > ?", (now - 3600,)):
        odd = [f for f in json.loads(e["data"]).get("files", []) if not f.get("readable") or not f.get("known_type")]
        if odd:
            out.append(("att-%s" % e["mail_id"], "odd_attachment", e["thread_id"],
                        "a customer file we could not read or have never seen: " + "; ".join(
                            "%s (%s bytes, %s)" % (f["filename"], f["bytes"], "not downloaded" if not f.get("downloaded")
                                                   else "no text found" if not f.get("readable") else "new type")
                            for f in odd) + ". 5U may have hidden something in it: open it by hand."))
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "board_results" in tables:
        for b in c.execute("SELECT * FROM board_results WHERE updated_at > ?", (now - 3600,)):
            v = (b["verdict"] or "").lower()
            if v in ("rejected", "no answer", "no_answer", "expired"):
                out.append(("board-%s" % b["round"], "rejected", b["thread_id"],
                            "round %s: 5U says `%s`, reason `%s`, points %s" % (b["round"], v, b["reason"], b["points"])))
            elif v == "accepted" and b["points"] is not None and b["points"] < LOW_SCORE:
                out.append(("low-%s" % b["round"], "low_score", b["thread_id"],
                            "round %s: accepted but only %.1f points, reason `%s`" % (b["round"], b["points"], b["reason"])))
    beat = db.get_state("heartbeat")
    if beat and safety.is_locked() is False and now - float(beat) > SILENT_AFTER_S:
        out.append(("silent-%d" % (float(beat) // 300), "clerk_silent", None,
                    "the clerk is NOT running (no lock) and last polled the mailbox %d s ago" % (now - float(beat))))
    elif beat and now - float(beat) > SILENT_AFTER_S:
        out.append(("silent-%d" % (float(beat) // 300), "clerk_silent", None,
                    "the clerk runs but has not polled the mailbox for %d s (stuck in one request?)" % (now - float(beat))))
    return out


def post(text):
    r = subprocess.run(["gh", "issue", "comment", CHAT_ISSUE, "--body", text[:60000]], cwd=config.ROOT,
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])


def check(dry=False):
    """One pass. Returns the number of alarms posted (or printed)."""
    n = 0
    for key, kind, tid, headline in find():
        if not dry and not _first_time(key, kind, tid):
            continue
        text = "ALARM from the runner (automatic, core/alarm.py): **%s**. %s\n\n%s\n\nCommit on the runner: `%s`." % (
            kind, headline, report(tid) if tid else "", db.get_state("commit") or "?")
        if dry:
            print(text + "\n" + "=" * 80)
            n += 1
            continue
        _posted[:] = [t for t in _posted if t > time.time() - 3600]
        if len(_posted) >= MAX_PER_HOUR:
            db.event("alarm_skipped_rate_limit", tid, alarm=kind)
            continue
        try:
            post(text)
            _posted.append(time.time())
            n += 1
            db.event("alarm_posted", tid, alarm=kind, headline=headline)
        except Exception as e:                               # could not post: forget it so we try again next pass
            _con().execute("DELETE FROM alarms WHERE key=?", (key,))
            db.event("alarm_post_failed", tid, alarm=kind, error=str(e))
    return n


def loop():
    while True:
        try:
            check()
        except Exception as e:                               # an alarm bug must never take anything down
            try:
                db.event("alarm_error", error=str(e)[:300])
            except Exception:
                pass
        time.sleep(20)


def start_background():
    """Called by the supervisor on the runner."""
    if config.DRY_RUN or not shutil.which("gh"):
        return
    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    if "--print" in sys.argv:
        print("%d problem(s) visible right now." % check(dry=True))
    elif not safety.is_locked() and "--force" not in sys.argv:
        sys.exit("No clerk is running on this machine, so this is not the runner. Only the runner posts alarms.\n"
                 "To see what it would post from your DB: python3 -m core.alarm --print")
    else:
        print("Alarm watcher running. It posts problems to the agent chat (issue #%s). Ctrl+C to stop." % CHAT_ISSUE)
        try:
            loop()
        except KeyboardInterrupt:
            pass
