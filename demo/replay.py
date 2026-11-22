"""Demo replay: play REAL recorded requests back into a separate database, in real time, so a second UI can show
Relay working: a request arrives, prices come in, the quote goes out, the customer says yes, the flight is booked
and confirmed, the customer asks where the shipment is. Nothing is sent, no key, no network, the clerk is not used.

    python3 -m demo.replay --list                          # good rounds to pick from, one line each
    python3 -m demo.replay                                 # the newest 3 quoted and booked requests, speed 4
    python3 -m demo.replay --threads 59295,59775 --speed 2 # chosen requests (thread = id of the first mail)
    python3 -m demo.replay --loop                          # start over (fresh history) when done

Then, in a second terminal, the line the replay prints at its start, for example
    cd ui && DB_PATH=/abs/path/data/demo.db npm run dev -- -p 3003

How it works
  source   a recorded database, opened read-only (file:...?mode=ro). Default: the live runner's data/forwarder.db
           when it exists on this machine, else examples/real/snapshot.db. --source PATH overrides.
  target   --db PATH, default data/demo.db in this checkout (git-ignored). Deleted and created fresh on every run.
           Refused: the source file itself, any file named forwarder.db, any file in the source's folder.
  history  everything older than the replayed rounds is copied in at once (about 200 requests), every timestamp
           shifted by ONE constant so that it ends 60 s before the first request arrives. The screens look like a
           business that has been running. Clerk noise (loop_error, restart, alarm_posted ...) is left out.
  rounds   one request after another (--gap seconds between), each one starting "now". Its rows are inserted in
           their original order with the original gaps divided by --speed (a gap is never longer than --max-gap
           after that, so the 13 minutes before a tracking question do not stall the video). Stored timestamps are
           the compressed ones, so "time to quote" on screen is the recorded time divided by --speed.
           Use --speed 1 for the true times. alarm_posted events of the replayed rounds are left out: they say
           "not answered after 75 s" and would be wrong on the compressed clock.
  session  the sessions row is built up the way the clerk built it, event by event (see Round.effect), and ends
           exactly equal to the recorded row (apart from the time columns). bids, bookings, invoices and actions
           are inserted when they happened and also end equal to the recorded rows.

Event to session change (clerk code: core/main.py, core/db.py, booking/handlers.py, llm/clarify.py)
  mail_in (first mail)   insert session: status new, deadline = arrival + bid wait
  llm                    fields as the model read them, llm_cost_usd
  gate                   fields as priced (weights added up), note (warnings)
  options                options
  waiting_bids           status waiting_bids          (bid rows: insert 'asked', update when the answer came)
  human_style/offer_file status sending               (the clerk claimed the thread, the mail is being written)
  quote_sent             status quoted, chosen, reply (the mail_out body), quoted_at
  requote                status new again, fields with the new weight, first round's bids move to -thread
  follow_up accept       status booking               decline: lost
  booking_call 2xx       status booked                (bookings row inserted)
  booking_confirmed      status confirmed             (bookings row completed)
  needs_human, clarify_asked, meeting_proposed, booking_cancelled ... their status, note
  last step              every column of the recorded rows is written once more, so the end state is exact.
"""
import argparse
import bisect
import json
import os
import shlex
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE_DB = Path("/Users/Erik/Work/starthack-5u/repo/data/forwarder.db")   # the live runner's file: READ ONLY, ever
SNAPSHOT_DB = ROOT / "examples" / "real" / "snapshot.db"
DEFAULT_DB = ROOT / "data" / "demo.db"

HISTORY_LEAD_S = 60          # history ends this long before the first replayed request arrives
NOISE = {"loop_error", "poll_rate_limited", "clerk_exit", "restart", "start", "alarm_posted", "thread_test_probe"}
SENDING = {"human_style", "humanize", "offer_file", "reply_gate"}   # logged after the clerk claimed the thread
TIME_COLS = {"mails": ("received_at",), "events": ("ts",), "sessions": ("received_at", "deadline", "quoted_at"),
             "bids": ("requested_at", "replied_at"), "bookings": ("created_at", "booked_at", "confirmed_at"),
             "invoices": ("issued_at", "due_at", "last_reminder_at", "paid_at"), "actions": ("created_at", "done_at"),
             "alarms": ("ts",), "carrier_flags": ("updated_at",)}
PK = {"mails": "id", "events": "id", "sessions": "thread_id", "bids": "id", "bookings": "thread_id",
      "invoices": "thread_id", "actions": "id", "alarms": "key", "carrier_flags": "carrier", "state": "key"}
WON = ("booked", "confirmed")


# ---------------------------------------------------------------------------------------------- the recorded data

class Source:
    """The whole recorded database in memory, read in ONE read-only transaction (a consistent view of a live file)."""

    def __init__(self, path):
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        con.row_factory = sqlite3.Row
        con.execute("BEGIN")
        self.ddl = [r["sql"] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type='index', rowid")]
        names = [r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        self.tables = {n: [dict(r) for r in con.execute("SELECT * FROM %s" % n)] for n in names}
        con.close()
        t = self.tables.get
        self.sessions = {s["thread_id"]: s for s in t("sessions", [])}
        self.mail_by_id = {m["id"]: m for m in t("mails", [])}
        self.mails_by_thread, self.events_by_thread, self.events_by_mail = {}, {}, {}
        for m in t("mails", []):
            self.mails_by_thread.setdefault(m["thread_id"], []).append(m)
        for e in t("events", []):
            self.events_by_thread.setdefault(e["thread_id"], []).append(e)
            if e["mail_id"] is not None:
                self.events_by_mail.setdefault(e["mail_id"], []).append(e)
        self.by_thread = {n: {} for n in ("bids", "bookings", "invoices", "actions", "alarms")}
        for n, d in self.by_thread.items():
            for r in t(n, []):
                d.setdefault(abs(r["thread_id"]) if r["thread_id"] is not None else None, []).append(r)
        self.tracking = {}                                   # booking thread -> the threads of its tracking questions
        for e in t("events", []):
            if e["kind"] == "tracking_lookup":
                booking = (self.data(e).get("booking") or {}).get("thread_id")
                if booking is not None and e["thread_id"] not in self.tracking.setdefault(int(booking), []):
                    self.tracking[int(booking)].append(e["thread_id"])

    @staticmethod
    def data(e):
        try:
            return json.loads(e["data"]) if e["data"] else {}
        except ValueError:
            return {}

    def bundle(self, tid):
        """Every row that belongs to one request: its mails and events, the carrier answers and the airline's
        confirmation it used, its tracking questions, its bids, booking, invoice and actions."""
        ev = {e["id"]: e for e in self.events_by_thread.get(tid, [])}
        mail_ids = {m["id"] for m in self.mails_by_thread.get(tid, [])} | {e["mail_id"] for e in ev.values() if e["mail_id"]}
        for th in self.tracking.get(tid, []):
            ev.update({e["id"]: e for e in self.events_by_thread.get(th, [])})
            mail_ids |= {m["id"] for m in self.mails_by_thread.get(th, [])}
        for mid in mail_ids:
            ev.update({e["id"]: e for e in self.events_by_mail.get(mid, [])})
        get = lambda n: self.by_thread[n].get(tid, [])       # noqa: E731
        return {"mails": [self.mail_by_id[i] for i in sorted(mail_ids) if i in self.mail_by_id],
                "events": [ev[i] for i in sorted(ev) if ev[i]["kind"] not in NOISE],
                "bids": get("bids"), "bookings": get("bookings"), "invoices": get("invoices"),
                "actions": get("actions"), "alarms": get("alarms")}

    def candidates(self):
        """Quoted and booked requests, newest first."""
        out = []
        for s in sorted(self.sessions.values(), key=lambda x: -x["received_at"]):
            bk = self.by_thread["bookings"].get(s["thread_id"])
            if s["quoted_at"] and bk and bk[0]["status"] in WON:
                out.append(s)
        return out


def fields_of(s):
    try:
        return json.loads(s["fields"] or "{}") or {}
    except ValueError:
        return {}


# ---------------------------------------------------------------------------------------------- the target database

def check_target(source, target):
    """Refuse to write where the recorded data lives."""
    src, tgt = Path(source).resolve(), Path(target).resolve()
    if tgt == src or (tgt.exists() and src.exists() and os.path.samefile(tgt, src)):
        sys.exit("refused: the target is the source database")
    if tgt.name == "forwarder.db" or tgt.name.startswith("forwarder.db-"):
        sys.exit("refused: the target must not be named forwarder.db (that is the runner's database)")
    if tgt.parent == src.parent:
        sys.exit("refused: the target is in the source's folder (%s); use the default data/demo.db" % src.parent)


def create_target(path, ddl):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(str(path) + suffix)
        except FileNotFoundError:
            pass
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")                   # the UI reads while we write
    con.execute("PRAGMA synchronous=OFF")
    for sql in ddl:
        con.execute(sql)
    return con


def retime(table, row, f):
    out = dict(row)
    for c in TIME_COLS.get(table, ()):
        if out.get(c) is not None:
            out[c] = f(out[c])
    if table == "invoices" and row.get("due_at") is not None and row.get("issued_at") is not None:
        out["due_at"] = out["issued_at"] + (row["due_at"] - row["issued_at"])   # "30 days" stays 30 days
    return out


class Writer:
    def __init__(self, con):
        self.con = con

    def put(self, table, row):
        cols = list(row)
        self.con.execute("INSERT OR REPLACE INTO %s(%s) VALUES(%s)" % (table, ",".join(cols), ",".join("?" * len(cols))),
                         [row[c] for c in cols])

    def set(self, table, key, **cols):
        if cols:
            self.con.execute("UPDATE %s SET %s WHERE %s=?" % (table, ",".join(c + "=?" for c in cols), PK[table]),
                             list(cols.values()) + [key])


def write_history(src, w, chosen, cutoff, shift, end):
    """Everything older than the replayed rounds, shifted by one constant. A request that began before the cutoff is
    history as a whole; its later rows are clamped to `end` so nothing lies in the future."""
    f = lambda t: min(t + shift, end)                        # noqa: E731
    keep, drop = {}, {}
    for s in src.sessions.values():
        mine = s["received_at"] < cutoff and s["thread_id"] not in chosen
        b = src.bundle(s["thread_id"])
        for table, rows in b.items():
            pk = PK[table]
            (keep if mine else drop).setdefault(table, set()).update(r[pk] for r in rows)
    counts = {}
    w.con.execute("BEGIN")
    for table, rows in src.tables.items():
        first = (TIME_COLS.get(table) or (None,))[0]
        n = 0
        for r in rows:
            if table == "events" and r["kind"] in NOISE:
                continue
            pk = r.get(PK.get(table))
            if pk in keep.get(table, ()):
                pass
            elif pk in drop.get(table, ()) or (first and (r.get(first) or 0) >= cutoff):
                continue
            w.put(table, retime(table, r, f))
            n += 1
        counts[table] = n
    w.con.execute("COMMIT")
    return counts


# ---------------------------------------------------------------------------------------------- one replayed request

class Clock:
    """Maps a recorded time to the replay time: gaps divided by speed, no gap longer than max_gap."""

    def __init__(self, times, start, speed, max_gap):
        self.k = sorted(set(times))
        self.start, self.speed = start, speed
        self.off = [0.0]
        for a, b in zip(self.k, self.k[1:]):
            step = (b - a) / speed
            self.off.append(self.off[-1] + (min(step, max_gap) if max_gap else step))

    def __call__(self, t):
        k, off = self.k, self.off
        if t <= k[0]:
            return self.start + (t - k[0]) / self.speed
        if t >= k[-1]:
            return self.start + off[-1] + (t - k[-1]) / self.speed
        i = bisect.bisect_right(k, t) - 1
        return self.start + off[i] + (t - k[i]) / (k[i + 1] - k[i]) * (off[i + 1] - off[i])

    @property
    def end(self):
        return self.start + self.off[-1]


def money(x):
    try:
        return "%.2f" % float(x)
    except (TypeError, ValueError):
        return str(x)


class Round:
    """The steps of one request, each (recorded time, priority, key, function(writer, clock) -> log line or None)."""

    def __init__(self, src, tid):
        self.src, self.tid = src, tid
        self.s = src.sessions[tid]
        self.b = src.bundle(tid)
        self.final_fields = fields_of(self.s)
        self.status = "new"
        self.gates = 0
        evs = self.b["events"]
        self.quotes = [e["id"] for e in evs if e["kind"] == "quote_sent"]
        self.requote = next((e for e in evs if e["kind"] == "requote"), None)
        wait = next((src.data(e).get("wait_s") for e in evs if e["kind"] == "waiting_bids"), None) or 90.0
        self.first_deadline = self.s["received_at"] + wait
        lane = "%s to %s" % (self.final_fields.get("origin") or "?", self.final_fields.get("destination") or "?")
        self.lane = lane
        # fields of the first pricing round: with a requote, the weights the customer first gave
        ff = dict(self.final_fields)
        if self.requote:
            before = src.data(self.requote).get("before") or {}
            for k in ("weight_kg_total", "volume_cbm_total"):
                if before.get(k) is not None:
                    ff[k] = before[k]
            ff["weight_kg"], ff["volume_cbm"] = ff.get("weight_kg_total"), ff.get("volume_cbm_total")
            ff.pop("revised", None)
        self.first_fields = json.dumps(ff, default=str)

    # ---- the plan
    def steps(self):
        st, b, s = [], self.b, self.s
        add = lambda ts, prio, key, fn: st.append((ts, prio, key, fn))   # noqa: E731
        t0 = s["received_at"]
        for m in b["mails"]:
            add(m["received_at"], 0, m["id"], lambda w, tm, m=m: self.put_mail(w, tm, m))
        if not any(e["kind"] == "mail_in" and e["mail_id"] == self.tid for e in b["events"]):
            add(t0, 1, 0, lambda w, tm: self.create(w, tm))
        req = {self.src.data(e).get("bid_id"): self.src.data(e) for e in b["events"] if e["kind"] == "bid_requested"}
        got = {self.src.data(e).get("bid_id"): self.src.data(e) for e in b["events"] if e["kind"] == "bid_received"}
        for r in b["bids"]:
            add(r["requested_at"], 1, r["id"], lambda w, tm, r=r: self.ask(w, tm, r, req.get(r["id"])))
            if r["replied_at"] is not None:
                add(r["replied_at"], 2, r["id"], lambda w, tm, r=r: self.answer(w, tm, r, got.get(r["id"])))
        for e in b["events"]:
            add(e["ts"], 3, e["id"], lambda w, tm, e=e: self.event(w, tm, e))
        for r in b["bookings"]:
            first = dict(r, status="booked", confirmed_at=None) if r["status"] == "confirmed" else r
            add(r["created_at"] or t0, 4, 0, lambda w, tm, r=first: w.put("bookings", retime("bookings", r, tm)))
            if r["status"] == "confirmed" and r["confirmed_at"]:
                add(r["confirmed_at"], 4, 1, lambda w, tm, r=r: w.put("bookings", retime("bookings", r, tm)))
        for r in b["invoices"]:
            add(r["issued_at"], 4, 2, lambda w, tm, r=r: w.put("invoices", retime("invoices", r, tm)))
        for r in b["actions"]:
            add(r["created_at"], 4, 3, lambda w, tm, r=r: w.put("actions", retime("actions", dict(r, done_at=None, result=None), tm)))
            if r["done_at"] is not None:
                add(r["done_at"], 4, 4, lambda w, tm, r=r: w.put("actions", retime("actions", r, tm)))
        st.sort(key=lambda x: x[:3])
        last = st[-1][0]
        add(last, 9, 0, lambda w, tm: self.finish(w, tm))
        st.sort(key=lambda x: x[:3])
        return st

    def put_mail(self, w, tm, m):
        w.put("mails", retime("mails", dict(m, route=None), tm))
        if m["id"] == self.tid:
            f = self.final_fields
            return "request %d %s arrives (%s kg)" % (self.tid, self.lane, f.get("weight_kg_total") or f.get("weight_kg") or "?")

    def create(self, w, tm):
        s = self.s
        w.put("sessions", retime("sessions", {"thread_id": self.tid, "customer": s["customer"], "subject": s["subject"],
                                              "status": "new", "received_at": s["received_at"], "deadline": self.first_deadline}, tm))

    def ask(self, w, tm, r, ev):
        row = {"id": r["id"], "thread_id": self.tid, "carrier": (ev or {}).get("carrier") or r["carrier"], "kind": r["kind"],
               "email": r.get("email"), "role": r.get("role"), "required": int((ev or {}).get("required", r.get("required", 1))),
               "status": "asked", "requested_at": r["requested_at"]}
        w.put("bids", retime("bids", row, tm))

    def answer(self, w, tm, r, ev):
        row = dict(r, thread_id=self.tid)
        if r["thread_id"] < 0:                               # a first-round bid: the requote has not moved it yet
            row.update(status=(ev or {}).get("status") or r["status"], required=int((ev or {}).get("required", 1)))
        w.put("bids", retime("bids", row, tm))

    def finish(self, w, tm):
        """Write the recorded rows once more: the end state is exactly what the clerk had."""
        w.put("sessions", retime("sessions", self.s, tm))
        for table in ("bids", "bookings", "invoices", "actions"):
            for r in self.b[table]:
                w.put(table, retime(table, r, tm))

    # ---- events
    def event(self, w, tm, e):
        d = self.src.data(e)
        w.put("events", retime("events", e, tm))
        if e["kind"] == "mail_in" and e["mail_id"] is not None:
            w.set("mails", e["mail_id"], route=d.get("route"))
            if e["mail_id"] == self.tid:
                self.create(w, tm)
        cols = self.effect(e, d)
        if cols:
            if "status" in cols:
                self.status = cols["status"]
            w.set("sessions", self.tid, **retime("sessions", cols, tm))
        if e["kind"] == "requote":
            for r in self.b["bids"]:
                if r["thread_id"] < 0:
                    w.con.execute("UPDATE bids SET thread_id=?, status=?, required=? WHERE id=?",
                                  (r["thread_id"], r["status"], r["required"], r["id"]))
        return self.describe(e, d)

    def effect(self, e, d):
        """The sessions columns this event changed (recorded times; the caller maps them)."""
        k, s = e["kind"], self.s
        if k == "llm":
            return {"fields": json.dumps(d.get("fields") or {}, default=str), "llm_cost_usd": (d.get("usage") or {}).get("cost_usd")}
        if k == "gate":
            self.gates += 1
            cols = {"fields": self.first_fields if self.gates == 1 else s["fields"]}
            if d.get("note"):
                cols["note"] = d["note"]
            return cols
        if k == "options":
            return {"options": json.dumps(d.get("options") or [], default=str)}
        if k == "waiting_bids":
            return {"status": "waiting_bids"}
        if k in SENDING and self.status in ("new", "waiting_bids") and any(q > e["id"] for q in self.quotes):
            return {"status": "sending"}
        if k == "quote_sent":
            out = [x for x in self.b["events"] if x["kind"] == "mail_out" and x["id"] < e["id"]
                   and str(self.src.data(x).get("to", "")).lower() == (s["customer"] or "").lower()]
            cols = {"status": "quoted", "chosen": json.dumps(d.get("chosen"), default=str),
                    "quoted_at": s["received_at"] + d["seconds"] if d.get("seconds") is not None else e["ts"]}
            if out:
                cols["reply"] = self.src.data(out[-1]).get("body")
            return cols
        if k == "quote_failed":
            return {"status": "failed"}
        if k == "requote":
            return {"status": "new", "fields": s["fields"], "reply_template": "", "deadline": max(s["deadline"] or 0, e["ts"] + 90),
                    "note": "customer changed the shipment after the quote: new quote"}
        if k == "needs_human":
            return {"status": "needs_human", "note": d.get("why")}
        if k == "rfq_expired":
            return {"status": "expired"}
        if k == "clarify_asked":
            return {"status": "asked_customer", "note": "asked customer for: %s" % ", ".join(d.get("missing") or [])}
        if k == "clarify_answer":
            return {"status": "lost", "note": "customer declined after our question"} if d.get("verdict") == "decline" else {"status": "new"}
        if k == "meeting_proposed":
            return {"status": "meeting_proposed"}
        if k == "follow_up":
            if d.get("verdict") in ("accept", "sending_docs"):
                return {"status": "booking"}
            if d.get("verdict") == "decline":
                return {"status": "lost", "note": "customer declined"}
        if k in ("accept_after_call_offer", "price_confirmed_by_mail"):
            return {"status": "quoted"}
        if k == "booking_call" and int(d.get("status") or 0) in (200, 201):
            return {"status": "booked"}
        if k == "portal_booking_down_mail":
            return {"status": "booking_requested"}
        if k == "booking_confirmed":
            return {"status": "confirmed"}
        if k in ("booking_cancel_call", "booking_cancelled"):
            return {"status": "cancelled"}
        if k == "awaiting_docs":
            return {"status": "awaiting_docs"}
        return None

    def describe(self, e, d):
        k = e["kind"]
        f = self.final_fields
        if k == "llm":
            r = d.get("fields") or {}
            return "request %d read: %s to %s, %s kg" % (self.tid, r.get("origin") or "?", r.get("destination") or "?", r.get("weight_kg") or "?")
        if k == "options":
            return "request %d: %s price options from rate sheets and the portal" % (self.tid, d.get("count", len(d.get("options") or [])))
        if k == "waiting_bids":
            return "request %d: asked %s carriers and truckers for prices" % (self.tid, d.get("pending"))
        if k == "bid_received":
            price = (d.get("status") or "no price") if d.get("total") is None else "%s %s" % (money(d["total"]), d.get("currency"))
            return "request %d: %s %s: %s" % (self.tid, d.get("role"), d.get("carrier"), price)
        if k == "bid_picked":
            return "request %d: picked %s %s, %s EUR" % (self.tid, d.get("role"), d.get("carrier"), money(d.get("total_eur")))
        if k == "quote_sent":
            c = d.get("chosen") or {}
            return "request %d: quote sent %s %s, %s" % (self.tid, money(c.get("total")), c.get("currency"), c.get("airline"))
        if k == "requote":
            return "request %d: customer changed the shipment, new quote" % self.tid
        if k == "follow_up":
            return "request %d: customer replied (%s)" % (self.tid, d.get("verdict"))
        if k == "booking_call":
            return "request %d: flight booked, %s" % (self.tid, (d.get("response") or {}).get("booking_reference", "status %s" % d.get("status")))
        if k == "booking_confirmed":
            return "request %d: airline confirmed %s" % (self.tid, d.get("booking_reference"))
        if k == "customer_informed":
            return "request %d: customer told (%s)" % (self.tid, d.get("message"))
        if k == "invoice_issued":
            return "request %d: invoice %s %s %s" % (self.tid, d.get("number"), d.get("amount"), d.get("currency"))
        if k == "tracking_lookup":
            return "request %d: customer asks where the shipment is" % self.tid
        if k == "tracking_answered":
            return "request %d: status sent to the customer" % self.tid
        if k == "needs_human":
            return "request %d: handed to a person (%s)" % (self.tid, d.get("why"))
        return None


# ---------------------------------------------------------------------------------------------- the run

def play(src, db_path, tids, speed=4.0, gap=8.0, max_gap=15.0, delay=5.0, now=time.time, sleep=time.sleep,
         out=print, hook=None):
    """Build the target and replay `tids` one after another. `now` and `sleep` can be replaced (tests use a fake clock);
    `hook(con)` is called after every step with a read connection to the target. Returns the replay start time."""
    cutoff = min(src.sessions[t]["received_at"] for t in tids)
    start = now() + delay
    shift = (start - HISTORY_LEAD_S) - cutoff
    con = create_target(db_path, src.ddl)
    w = Writer(con)
    counts = write_history(src, w, set(tids), cutoff, shift, start - HISTORY_LEAD_S)
    out("history: %d requests, %d mails, %d events" % (counts.get("sessions", 0), counts.get("mails", 0), counts.get("events", 0)))
    stamp = lambda: time.strftime("%H:%M:%S", time.localtime(now()))   # noqa: E731
    first = start
    for n, tid in enumerate(tids):
        r = Round(src, tid)
        steps = r.steps()
        clock = Clock([x[0] for x in steps], start, speed, max_gap)
        for ts, _, _, fn in steps:
            wait = clock(ts) - now()
            if wait > 0:
                sleep(wait)
            con.execute("BEGIN")
            try:
                line = fn(w, clock)
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
            if line:
                out("%s %s" % (stamp(), line))
            if hook:
                hook(con)
        start = clock.end + gap
    con.close()
    return first


def describe_list(src, limit):
    print("%-7s %-13s %-9s %-10s %7s %-6s %-5s %-7s %-8s %s" % (
        "thread", "arrived", "lane", "status", "quote_s", "pickup", "bids", "replies", "tracking", "total"))
    for s in src.candidates()[:limit]:
        f, b = fields_of(s), src.bundle(s["thread_id"])
        bids = [x for x in b["bids"]]
        ok = sum(1 for x in bids if x["status"] in ("ok", "stale_weight") and x["total_eur"])
        replies = sum(1 for m in b["mails"] if m["route"] == "follow_up")
        try:
            total = "%s %s" % (money(json.loads(s["chosen"])["total"]), json.loads(s["chosen"]).get("currency", ""))
        except (TypeError, ValueError, KeyError):
            total = ""
        note = " requote" if any(e["kind"] == "requote" for e in b["events"]) else ""
        print("%-7d %-13s %-9s %-10s %7.0f %-6s %-5s %-7d %-8s %s%s" % (
            s["thread_id"], time.strftime("%d %b %H:%M", time.localtime(s["received_at"])),
            "%s-%s" % (f.get("origin") or "?", f.get("destination") or "?"), s["status"], s["quoted_at"] - s["received_at"],
            "yes" if f.get("pickup_postcode") else "no", "%d/%d" % (ok, len(bids)), replies,
            "yes" if src.tracking.get(s["thread_id"]) else "no", total, note))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m demo.replay", description="Replay recorded requests into a demo database.")
    ap.add_argument("--source", help="recorded database (read-only). Default: the runner's data/forwarder.db, else examples/real/snapshot.db")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="demo database to create (default data/demo.db)")
    ap.add_argument("--threads", help="comma separated thread ids to replay")
    ap.add_argument("--rounds", type=int, default=3, help="else: the newest N quoted and booked requests (default 3)")
    ap.add_argument("--speed", type=float, default=4.0, help="recorded gaps are divided by this (default 4)")
    ap.add_argument("--gap", type=float, default=8.0, help="seconds between two replayed requests (default 8)")
    ap.add_argument("--max-gap", type=float, default=15.0, help="longest pause inside one request, seconds (0 = no limit)")
    ap.add_argument("--delay", type=float, default=5.0, help="seconds before the first request arrives (default 5)")
    ap.add_argument("--loop", action="store_true", help="start over when done")
    ap.add_argument("--list", action="store_true", help="print good requests to pick from and exit")
    ap.add_argument("--limit", type=int, default=30, help="rows for --list")
    ap.add_argument("--port", type=int, default=3003, help="port in the UI command that is printed")
    a = ap.parse_args(argv)

    source = Path(a.source) if a.source else (LIVE_DB if LIVE_DB.exists() else SNAPSHOT_DB)
    if not source.exists():
        sys.exit("no source database at %s (use --source PATH)" % source)
    if a.speed <= 0:
        sys.exit("--speed must be above 0")
    src = Source(source)
    if a.list:
        return describe_list(src, a.limit)
    check_target(source, a.db)
    if a.threads:
        tids = [int(x) for x in a.threads.split(",") if x.strip()]
        missing = [t for t in tids if t not in src.sessions]
        if missing:
            sys.exit("not in the source database: %s" % ", ".join(map(str, missing)))
    else:
        tids = [s["thread_id"] for s in src.candidates()[:a.rounds]][::-1]       # oldest of the chosen first
        if not tids:
            sys.exit("no quoted and booked request in the source database")
    target = Path(a.db).resolve()
    print("source  %s (read only)" % source)
    print("target  %s (created fresh)" % target)
    print("show it with:  cd %s && DB_PATH=%s npm run dev -- -p %d" % (shlex.quote(str(ROOT / "ui")), shlex.quote(str(target)), a.port))
    print("rounds  %s   speed %g   first request in %g s" % (", ".join(map(str, tids)), a.speed, a.delay))
    while True:
        play(src, target, tids, a.speed, a.gap, a.max_gap, a.delay)
        print("%s done" % time.strftime("%H:%M:%S"))
        if not a.loop:
            break
        time.sleep(a.gap)


if __name__ == "__main__":
    main()
