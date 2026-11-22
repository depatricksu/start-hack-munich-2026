"""demo/replay.py: a recorded request is played back into a separate database, step by step, with a fake clock.
No core.db, no network. Run: python -m unittest tests.test_demo_replay"""
import contextlib, hashlib, io, json, os, pathlib, shutil, sqlite3, tempfile, unittest

from demo import replay

SCHEMA = """
CREATE TABLE mails(id INTEGER PRIMARY KEY, sender TEXT, subject TEXT, body TEXT, thread_id INTEGER, route TEXT, received_at REAL, raw TEXT);
CREATE TABLE sessions(thread_id INTEGER PRIMARY KEY, customer TEXT, subject TEXT, status TEXT, fields TEXT, reply_template TEXT,
  options TEXT, chosen TEXT, reply TEXT, note TEXT, received_at REAL, deadline REAL, quoted_at REAL, llm_cost_usd REAL);
CREATE TABLE bids(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, carrier TEXT, kind TEXT, requested_at REAL, replied_at REAL,
  total TEXT, currency TEXT, transit_days INTEGER, raw TEXT, email TEXT, role TEXT, required INTEGER DEFAULT 1, status TEXT, total_eur TEXT, note TEXT, hours REAL);
CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, thread_id INTEGER, mail_id INTEGER, kind TEXT, data TEXT);
CREATE TABLE state(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE bookings(thread_id INTEGER PRIMARY KEY, team_reference TEXT UNIQUE, customer TEXT, subject TEXT, last_customer_mail_id INTEGER,
  rate_id TEXT, booking_reference TEXT, airline TEXT, airline_code TEXT, origin TEXT, destination TEXT, weight_kg REAL, volume_cbm REAL,
  transit_days INTEGER, price TEXT, currency TEXT, source TEXT, status TEXT, language TEXT, created_at REAL, booked_at REAL, confirmed_at REAL, raw TEXT);
CREATE TABLE invoices(thread_id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer TEXT, subject TEXT, amount TEXT, currency TEXT, lines TEXT,
  language TEXT, issued_at REAL, due_at REAL, status TEXT, sent INTEGER DEFAULT 0, reminders INTEGER DEFAULT 0, last_reminder_at REAL, paid_at REAL, body TEXT, note TEXT);
CREATE TABLE actions(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, kind TEXT, body TEXT, created_at REAL, done_at REAL, result TEXT);
CREATE TABLE alarms(key TEXT PRIMARY KEY, ts REAL, kind TEXT, thread_id INTEGER);
"""
CUSTOMER = "anna@customer.mail"
CHOSEN = {"airline": "Juniper Cargo Lines", "total": "2261.20", "total_eur": "2261.20", "currency": "EUR", "transit_days": 1, "source": "portal"}
FIELDS = {"origin": "MUC", "destination": "RUH", "weight_kg": 900.0, "weight_kg_total": 900.0, "pickup_postcode": "86208", "language": "en"}


def build_source(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    ev_id = [0]

    def mail(mid, tid, sender, route, t, subject="RE: RFQ MUC RUH", body="hello"):
        con.execute("INSERT INTO mails VALUES(?,?,?,?,?,?,?,?)", (mid, sender, subject, body, tid, route, t, "{}"))

    def ev(t, tid, kind, mail_id=None, **data):
        ev_id[0] += 1
        con.execute("INSERT INTO events VALUES(?,?,?,?,?,?)", (ev_id[0], t, tid, mail_id, kind, json.dumps(data)))

    # three old requests: the history
    for i, t in enumerate((1000.0, 1100.0, 1200.0)):
        tid = 100 + i
        mail(tid, tid, CUSTOMER, "rfq", t)
        ev(t + 3, tid, "mail_in", tid, route="rfq")
        con.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, CUSTOMER, "old", "lost", json.dumps(FIELDS), "", "[]", None, None, "customer declined", t, t + 90, t + 70, 0.002))
    ev(1250.0, None, "loop_error", error="boom")                       # clerk noise: not in the demo history

    def request(tid, t0, tracking):
        base = dict(thread_id=tid)
        mail(tid, tid, CUSTOMER, "rfq", t0)
        ev(t0 + 4, tid, "mail_in", tid, route="rfq", sender=CUSTOMER)
        ev(t0 + 6, tid, "llm", tid, fields=dict(FIELDS, weight_kg=800.0), usage={"cost_usd": 0.002})
        ev(t0 + 7, tid, "gate", tid, ok=True, note="llm_regex_mismatch: weight")
        options = [dict(CHOSEN, airline="Quetzal", total="2300.00", total_eur="2300.00"), CHOSEN]
        ev(t0 + 8, tid, "options", tid, count=2, options=options)
        for bid, (carrier, role) in enumerate((("Maintal", "trucker"), ("Aurelia", "airline")), start=tid * 10):
            con.execute("INSERT INTO bids(id,thread_id,carrier,kind,requested_at,replied_at,total,currency,transit_days,email,role,required,status,total_eur)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (bid, tid, carrier, role, t0 + 9, t0 + 30 + bid % 7, "140.44" if role == "trucker" else None, "EUR", None,
                         carrier + "@x.mail", role, 1, "ok" if role == "trucker" else "declined", "140.44" if role == "trucker" else None))
            ev(t0 + 9, tid, "bid_requested", None, bid_id=bid, carrier=carrier, role=role, required=True, sent=True)
        ev(t0 + 10, tid, "waiting_bids", tid, pending=2, wait_s=90.0)
        for k, bid in enumerate((tid * 10, tid * 10 + 1)):
            cm = tid + 100 + k
            mail(cm, cm, "carrier%d@x.mail" % k, "carrier_bid", t0 + 30 + bid % 7)
            ev(t0 + 31 + bid % 7, tid, "bid_received", cm, bid_id=bid, carrier="c", role="x", status="ok", total="140.44", currency="EUR")
            ev(t0 + 31 + bid % 7, cm, "mail_in", cm, route="carrier_bid")
        ev(t0 + 50, tid, "bid_wait_over", None, all_in=True)
        ev(t0 + 51, tid, "human_style", None, style="local")
        ev(t0 + 51.5, tid, "mail_out", None, to=CUSTOMER, subject="Re: x", body="Good news: 2261.20 EUR all-in")
        ev(t0 + 52, tid, "quote_sent", None, chosen=CHOSEN, seconds=52.0)
        yes = tid + 200
        mail(yes, tid, CUSTOMER, "follow_up", t0 + 70)
        ev(t0 + 72, tid, "mail_in", yes, route="follow_up")
        ev(t0 + 73, tid, "follow_up", yes, verdict="accept", status="quoted")
        ev(t0 + 74, tid, "booking_call", None, status=201, response={"booking_reference": "BK-%d" % tid})
        ev(t0 + 75, tid, "customer_informed", None, message="booked")
        conf = tid + 300
        mail(conf, conf, "juniper@x.mail", "booking_confirmation", t0 + 119)
        ev(t0 + 119.5, conf, "mail_in", conf, route="booking_confirmation")
        ev(t0 + 120, tid, "booking_confirmed", conf, booking_reference="BK-%d" % tid)
        ev(t0 + 121, tid, "invoice_issued", None, number="INV-%d" % tid, amount="2261.20", currency="EUR")
        ev(t0 + 60, tid, "alarm_posted", None, headline="not answered")
        con.execute("INSERT INTO bookings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, "GOOGLE-%d" % tid, CUSTOMER, "s", yes, "R-1", "BK-%d" % tid, "Juniper", "JP", "MUC", "RUH", 900, 3.2, 1, "2261.20", "EUR",
                     "portal", "confirmed", "en", t0 + 74, t0 + 74, t0 + 120, "{}"))
        con.execute("INSERT INTO invoices VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, "INV-%d" % tid, CUSTOMER, "s", "2261.20", "EUR", "[]", "en", t0 + 121, t0 + 121 + 30 * 86400, "open", 0, 0, None, None, "b", None))
        if tracking:
            tm_ = tid + 400
            mail(tm_, tm_, "tracking@x.mail", "tracking", t0 + 900)
            ev(t0 + 901, tm_, "mail_in", tm_, route="tracking")
            ev(t0 + 902, tm_, "tracking_lookup", tm_, matched=True, booking={"thread_id": tid})
            ev(t0 + 903, tm_, "tracking_answered", tm_, matched=True)
        con.execute("INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tid, CUSTOMER, "RE: RFQ MUC RUH", "confirmed", json.dumps(FIELDS), "", json.dumps(options), json.dumps(CHOSEN),
                     "Good news: 2261.20 EUR all-in", "llm_regex_mismatch: weight", t0, t0 + 90, t0 + 52, 0.002))

    request(5000, 2000.0, tracking=True)
    request(6000, 2400.0, tracking=False)
    con.commit()
    con.close()


class DemoReplay(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.source = os.path.join(self.dir, "recorded", "forwarder.db")
        os.makedirs(os.path.dirname(self.source))
        build_source(self.source)
        self.target = os.path.join(self.dir, "demo", "demo.db")

    def run_play(self, tids=(5000, 6000), speed=10.0, gap=5.0, delay=3.0, max_gap=15.0):
        clock = [1_800_000_000.0]
        seen = []                                            # (session thread, status, clock) after every step

        def hook(con):
            for tid, status in con.execute("SELECT thread_id, status FROM sessions WHERE thread_id IN (5000, 6000)"):
                seen.append((tid, status, clock[0], con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]))

        def sleep(dt):
            clock[0] += dt
        start = replay.play(replay.Source(self.source), self.target, list(tids), speed, gap, max_gap, delay,
                            now=lambda: clock[0], sleep=sleep, out=lambda s: None, hook=hook)
        return start, seen

    def rows(self, path, sql, *args):
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    def test_source_untouched(self):
        digest = lambda: hashlib.sha256(pathlib.Path(self.source).read_bytes()).hexdigest()   # noqa: E731
        before = digest()
        self.run_play()
        self.assertEqual(before, digest())

    def test_final_rows_equal_the_recorded_ones(self):
        self.run_play()
        timecols = {"sessions": {"received_at", "deadline", "quoted_at"}, "bookings": {"created_at", "booked_at", "confirmed_at"},
                    "invoices": {"issued_at", "due_at"}, "bids": {"requested_at", "replied_at"}}
        for table, key in (("sessions", "thread_id"), ("bookings", "thread_id"), ("invoices", "thread_id"), ("bids", "id")):
            want = {r[key]: r for r in self.rows(self.source, "SELECT * FROM %s WHERE thread_id IN (5000,6000)" % table)}
            got = {r[key]: r for r in self.rows(self.target, "SELECT * FROM %s WHERE thread_id IN (5000,6000)" % table)}
            self.assertEqual(sorted(want), sorted(got), table)
            for k, row in want.items():
                for col, val in row.items():
                    if col not in timecols[table]:
                        self.assertEqual(val, got[k][col], "%s %s %s" % (table, k, col))
        # the mails and events of the rounds are all there (the alarm of the round and the clerk noise are not)
        n = lambda path, sql: self.rows(path, sql)[0]["n"]   # noqa: E731
        self.assertEqual(n(self.source, "SELECT COUNT(*) n FROM mails"), n(self.target, "SELECT COUNT(*) n FROM mails"))
        self.assertEqual(n(self.source, "SELECT COUNT(*) n FROM events WHERE kind NOT IN ('alarm_posted','loop_error')"),
                         n(self.target, "SELECT COUNT(*) n FROM events"))
        routes = {r["route"] for r in self.rows(self.target, "SELECT route FROM mails")}
        self.assertTrue({"rfq", "carrier_bid", "follow_up", "booking_confirmation", "tracking"} <= routes)

    def test_the_session_moves_through_its_steps(self):
        _, seen = self.run_play()
        order = []
        for tid, status, _, _ in seen:
            if tid == 5000 and (not order or order[-1] != status):
                order.append(status)
        self.assertEqual(order, ["new", "waiting_bids", "sending", "quoted", "booking", "booked", "confirmed"])

    def test_a_request_appears_only_when_its_turn_comes(self):
        _, seen = self.run_play()
        first_6000 = next(x for x in seen if x[0] == 6000)
        first_5000 = next(x for x in seen if x[0] == 5000)
        self.assertEqual(first_5000[3], 3 + 1)               # three old requests and the first one
        self.assertEqual(first_6000[3], 3 + 2)
        self.assertGreater(first_6000[2], first_5000[2] + 100 / 10)   # after the first one had run its course

    def test_timestamps_land_around_now(self):
        start, _ = self.run_play(speed=10.0, delay=3.0)
        self.assertEqual(start, 1_800_000_003.0)
        s = {r["thread_id"]: r for r in self.rows(self.target, "SELECT * FROM sessions")}
        self.assertEqual(s[5000]["received_at"], start)
        self.assertAlmostEqual(s[5000]["quoted_at"] - s[5000]["received_at"], 52 / 10, places=6)
        self.assertAlmostEqual(s[5000]["deadline"] - s[5000]["received_at"], 90 / 10, places=6)
        history_end = max(r["received_at"] for r in self.rows(self.target, "SELECT * FROM sessions WHERE thread_id < 1000"))
        self.assertLess(history_end, start)
        self.assertAlmostEqual(history_end, start - replay.HISTORY_LEAD_S - (2000 - 1200), places=6)   # one constant shift
        ev = self.rows(self.target, "SELECT MAX(ts) t FROM events WHERE thread_id < 1000 OR thread_id IS NULL")[0]["t"]
        self.assertLessEqual(ev, start - replay.HISTORY_LEAD_S + 1e-6)
        last = self.rows(self.target, "SELECT MAX(ts) t FROM events")[0]["t"]
        self.assertLess(last, start + 2 * (121 / 10 + 15 + 5) + 15)   # the 15 minute wait before tracking is capped
        inv = self.rows(self.target, "SELECT issued_at, due_at FROM invoices WHERE thread_id=5000")[0]
        self.assertEqual(inv["due_at"] - inv["issued_at"], 30 * 86400)
        self.assertEqual(self.rows(self.target, "SELECT COUNT(*) n FROM events WHERE kind='alarm_posted'")[0]["n"], 0)

    def test_refusals(self):
        other = os.path.join(self.dir, "elsewhere")
        for target in (self.source,                                              # the source itself
                       os.path.join(other, "forwarder.db"),                      # named like the runner's file
                       os.path.join(os.path.dirname(self.source), "demo.db")):   # in the source's folder
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                replay.main(["--source", self.source, "--db", target, "--threads", "5000"])
        self.assertFalse(os.path.exists(os.path.join(other, "forwarder.db")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.source), "demo.db")))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            replay.main(["--source", self.source, "--db", self.target, "--threads", "424242"])

    def test_list_shows_the_good_rounds(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            replay.main(["--source", self.source, "--list"])
        text = out.getvalue()
        self.assertIn("5000", text)
        self.assertIn("MUC-RUH", text)
        self.assertNotIn(" 100 ", text)                      # lost requests are no candidates


if __name__ == "__main__":
    unittest.main()
