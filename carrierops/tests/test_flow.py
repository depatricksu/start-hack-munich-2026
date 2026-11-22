"""End-to-end on a small fake clerk DB (temp file): matching, state machine, customer told, invoice only after
delivery, reminders, tracking answer, idempotency, read-only clerk tables, no network imports."""
import ast, contextlib, io, json, os, shutil, sqlite3, tempfile, unittest

from carrierops import invoice, match, run, state, tracking

T0 = 1795330000.0          # 2026-11-22 ~05:26 UTC
H, DAY = 3600.0, 86400.0
YT = "yellowtail-air-freight@hackloop.mail"
CUST = "markus@brandt.example"

CLERK_SCHEMA = """
CREATE TABLE mails(id INTEGER PRIMARY KEY, sender TEXT, subject TEXT, body TEXT, thread_id INTEGER, route TEXT, received_at REAL, raw TEXT);
CREATE TABLE sessions(thread_id INTEGER PRIMARY KEY, customer TEXT, subject TEXT, status TEXT, fields TEXT, reply_template TEXT,
  options TEXT, chosen TEXT, reply TEXT, note TEXT, received_at REAL, deadline REAL, quoted_at REAL, llm_cost_usd REAL);
CREATE TABLE bids(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, carrier TEXT, kind TEXT, requested_at REAL, replied_at REAL,
  total TEXT, currency TEXT, transit_days INTEGER, raw TEXT, email TEXT, role TEXT, required INTEGER, status TEXT, total_eur TEXT,
  note TEXT, hours REAL);
CREATE TABLE bookings(thread_id INTEGER PRIMARY KEY, team_reference TEXT UNIQUE, customer TEXT, subject TEXT, last_customer_mail_id INTEGER,
  rate_id TEXT, booking_reference TEXT, airline TEXT, airline_code TEXT, origin TEXT, destination TEXT, weight_kg REAL, volume_cbm REAL,
  transit_days INTEGER, price TEXT, currency TEXT, source TEXT, status TEXT, language TEXT, created_at REAL, booked_at REAL,
  confirmed_at REAL, raw TEXT);
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="carrierops-test-")
        self.db = os.path.join(self.dir, "clerk.db")
        c = sqlite3.connect(self.db)
        c.execute("PRAGMA journal_mode=WAL")                 # like the real clerk (core/db.py)
        c.executescript(CLERK_SCHEMA)
        c.commit()
        c.close()
        self.mid = 1000
        run.PARTNERS.clear()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def clerk(self, sql, args=()):
        c = sqlite3.connect(self.db)
        c.execute(sql, args)
        c.commit()
        c.close()

    def booking(self, tid=41001, bk="BK-7Q2M9XKD", lang="en", flight_total="1036.00", origin="FRA", dest="ORD",
                airline="Yellowtail Air Freight", confirmed=True):
        fields = {"language": lang, "customer_first_name": "Markus", "pickup_postcode": "63067",
                  "customer_lines": ["Best regards", "Markus Brandt", "Brandt Maschinenbau GmbH"]}
        chosen = {"airline": airline, "total": "1246.00", "flight_total": flight_total, "currency": "EUR",
                  "trucker": "Westfalenroute", "trucker_total": "210.00", "transit_days": 4, "origin": origin, "destination": dest}
        self.clerk("INSERT INTO mails VALUES(?,?,?,?,?,?,?,?)", (tid, CUST, "Quote request %s-%s" % (origin, dest),
                   "Pickup at our warehouse: 63067 Offenbach, Hafenstrasse 12.\n3 pallets, 400 kg, 2.1 cbm.\nReady from Monday.",
                   tid, "rfq", T0 - 600, "{}"))
        self.clerk("INSERT INTO sessions(thread_id,customer,subject,status,fields,chosen,deadline) VALUES(?,?,?,?,?,?,?)",
                   (tid, CUST, "Quote request %s-%s" % (origin, dest), "confirmed", json.dumps(fields), json.dumps(chosen), T0 - 500))
        for name, mail, role, replied in (("Westfalenroute", "westfalenroute@hackloop.mail", "trucker", T0 - 550),
                                          ("Domblick Kurierdienst", "domblick-kurierdienst@hackloop.mail", "trucker", T0 - 400),
                                          ("Orion Cargo Air", "orion-cargo-air@hackloop.mail", "airline", None)):
            self.clerk("INSERT INTO bids(thread_id,carrier,kind,requested_at,replied_at,email,role,required,status) VALUES(?,?,?,?,?,?,?,?,?)",
                       (tid, name, role, T0 - 590, replied, mail, role, 1 if role == "trucker" else 0, "ok" if replied else "asked"))
        self.clerk("INSERT INTO bookings(thread_id,team_reference,customer,subject,booking_reference,airline,origin,destination,weight_kg,"
                   "volume_cbm,transit_days,price,currency,status,language,created_at,confirmed_at,last_customer_mail_id) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (tid, "GOOGLE-%d" % tid, CUST, "Quote request %s-%s" % (origin, dest), bk, airline, origin, dest, 400, 2.1, 4,
                    "1246.00", "EUR", "confirmed" if confirmed else "requested", lang, T0 - 300, T0 if confirmed else None, tid + 1))

    def mail(self, sender, subject, body, at, thread=None, refs=None):
        self.mid += 1
        raw = {"id": self.mid}
        if refs:
            raw["references"] = refs
            raw["in_reply_to"] = refs[-1]
        self.clerk("INSERT INTO mails VALUES(?,?,?,?,?,?,?,?)",
                   (self.mid, sender, subject, body, thread or (refs[0] if refs else self.mid), "x", at, json.dumps(raw)))
        return self.mid

    def go(self, now):
        con = state.connect(self.db)
        res = run.run_once(con, now)
        con.close()
        return res

    def con(self):
        return state.connect(self.db)

    def outbox(self, **where):
        con = self.con()
        q = "SELECT * FROM outbox" + (" WHERE " + " AND ".join("%s=?" % k for k in where) if where else "") + " ORDER BY id"
        r = state.rows(con, q, tuple(where.values()))
        con.close()
        return r

    def ship(self, tid=41001):
        con = self.con()
        s = state.shipment(con, tid)
        con.close()
        return s


class Step6(Base):
    def test_everyone_informed_once(self):
        self.booking()
        self.go(T0 + 60)
        parties = sorted(r["party"] for r in self.outbox())
        self.assertEqual(parties, ["airline", "bidder", "customer", "partner", "trucker"])
        tr = self.outbox(party="trucker")[0]
        self.assertEqual(tr["to_addr"], "westfalenroute@hackloop.mail")
        self.assertIn("63067 Offenbach", tr["body"])
        self.assertEqual(self.outbox(party="bidder")[0]["to_addr"], "domblick-kurierdienst@hackloop.mail")
        self.assertTrue(all(r["status"] == "draft" and r["thread_id"] == 41001 for r in self.outbox()))
        self.go(T0 + 120)                                  # idempotent
        self.assertEqual(len(self.outbox()), 5)
        con = self.con()
        kinds = {r["kind"] for r in state.rows(con, "SELECT kind FROM carrier_log")}
        self.assertIn("no_answer", kinds)                  # Orion never answered our price request
        self.assertIn("late_answer", kinds)                # Domblick answered after the bid wait

    def test_customer_cancel_tells_trucker_and_partner(self):
        self.booking()
        self.go(T0 + 60)
        self.clerk("UPDATE bookings SET status='cancelled' WHERE thread_id=41001")
        self.go(T0 + 120)
        self.assertEqual(self.ship()["status"], "cancelled")
        self.assertEqual(len(self.outbox(reason="customer cancelled")), 2)          # trucker + partner
        self.go(T0 + 180)
        self.assertEqual(len(self.outbox(reason="customer cancelled")), 2)

    def test_already_cancelled_when_first_seen_drafts_nothing(self):
        self.booking()
        self.clerk("UPDATE bookings SET status='cancelled' WHERE thread_id=41001")
        self.go(T0 + 60)
        self.assertEqual(self.ship()["status"], "cancelled")
        self.assertEqual(self.outbox(), [])

    def test_not_confirmed_no_shipment(self):
        self.booking(confirmed=False)
        self.go(T0)
        self.assertIsNone(self.ship())


class Step7(Base):
    def test_delay_reaches_customer_with_new_eta(self):
        self.booking()
        self.go(T0 + 60)
        self.mail(YT, "Booking BK-7Q2M9XKD - DELAYED", "Due to an aircraft change your shipment was moved from YT 880 to YT 4412. "
                  "New ETA ORD 28 Nov 2026 09:15 (was 25 Nov).", T0 + 5 * H)
        self.go(T0 + 5 * H + 60)
        s = self.ship()
        self.assertEqual((s["status"], s["eta_current"], s["flight"]), ("delayed", "2026-11-28 09:15", "YT 4412"))
        c = [r for r in self.outbox(party="customer") if r["reason"] == "carrier update: delayed"]
        self.assertEqual(len(c), 1)
        self.assertIn("28 Nov 2026, 09:15", c[0]["body"])
        self.assertIn("YT 4412", c[0]["body"])
        self.assertIn("an aircraft change", c[0]["body"])
        self.assertTrue(self.outbox(reason="carrier update: delayed", party="partner"))
        con = self.con()
        log = state.rows(con, "SELECT * FROM carrier_log WHERE kind='delay'")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["carrier"], "Yellowtail Air Freight")
        self.assertEqual(log[0]["delay_hours"], 48.0)        # planned 26 Nov (confirm + 4 days) -> 28 Nov

    def test_german_delay_only_our_ref_and_repeat_not_resent(self):
        self.booking(tid=42001, bk="BK-4HN8T2WQ", lang="de")
        self.go(T0 + 60)
        self.mail(YT, "Verspätung Ihrer Sendung GOOGLE-42001", "Ihre Sendung GOOGLE-42001 konnte wegen eines Fluggerätewechsels nicht "
                  "mit YT 880 abfliegen. Neuer Flug YT 4412, neue Ankunft in Chicago am 28.11.2026 gegen 09:15 Uhr.", T0 + H)
        m2 = self.mail(YT, "AW: Booking BK-4HN8T2WQ confirmed", "Nachtrag: neuer Flug YT 4412, Ankunft ORD 28.11.2026 09:15.", T0 + 2 * H)
        self.go(T0 + 3 * H)
        c = [r for r in self.outbox(party="customer") if "delayed" in r["reason"]]
        self.assertEqual(len(c), 1)                          # the same news twice is told once
        self.assertIn("28.11.2026, 09:15 Uhr", c[0]["body"])
        self.assertIn("Hallo Markus", c[0]["body"])
        con = self.con()
        u = state.one(con, "SELECT match FROM shipment_updates WHERE source='carrier' AND type='delayed' ORDER BY id LIMIT 1")
        self.assertEqual(u["match"], "our_ref")
        self.assertIsNotNone(state.one(con, "SELECT 1 FROM shipment_updates WHERE mail_id=?", (m2,)))

    def test_later_eta_hidden_in_a_confirmation_reply_is_a_delay(self):
        self.booking()
        conf = self.mail(YT, "Booking BK-7Q2M9XKD confirmed", "your booking BK-7Q2M9XKD is confirmed.", T0)
        self.go(T0 + 60)
        self.mail(YT, "AW: Booking BK-7Q2M9XKD confirmed", "Nachtrag: neuer Flug YT 4412, Ankunft ORD 29.11.2026.", T0 + H,
                  refs=[conf])
        self.go(T0 + 2 * H)
        s = self.ship()
        self.assertEqual((s["status"], s["eta_current"]), ("delayed", "2026-11-29"))
        self.assertEqual(len(self.outbox(reason="carrier update: delayed", party="customer")), 1)

    def test_rebook_is_not_a_cancellation(self):
        self.booking()
        self.go(T0 + 60)
        self.mail(YT, "Booking BK-7Q2M9XKD - flight change", "flight YT 880 of 25 Nov has been cancelled for technical reasons. "
                  "Your shipment is rebooked on YT 884 on 26 Nov 2026, ETA ORD 27 Nov 2026. No action needed.", T0 + H)
        self.go(T0 + 2 * H)
        s = self.ship()
        self.assertEqual((s["status"], s["flight"], s["eta_current"]), ("rebooked", "YT 884", "2026-11-27"))
        self.assertTrue(any("YT 884" in r["body"] for r in self.outbox(party="customer")))
        self.assertFalse(self.outbox(party="trucker", reason="airline cancelled"))

    def test_cancellation_offers_rebook_and_yes_requests_it(self):
        self.booking()
        self.go(T0 + 60)
        self.mail(YT, "Booking BK-7Q2M9XKD cancelled", "we regret that booking BK-7Q2M9XKD is cancelled: no capacity. "
                  "We can offer YT 890 on 28 Nov 2026 at the same rate.", T0 + H)
        self.go(T0 + 2 * H)
        s = self.ship()
        self.assertEqual(s["status"], "cancelled_by_airline")
        offer = [r for r in self.outbox(party="customer") if r["reason"] == "carrier update: cancelled"][0]
        self.assertIn("YT 890", offer["body"])
        self.assertIn("Shall we rebook", offer["body"])
        self.assertTrue(self.outbox(party="trucker", reason="airline cancelled"))
        self.assertTrue(self.outbox(party="forwarder", reason="airline cancelled the booking"))
        self.assertEqual(tracking.status(self.con(), 41001)["status"], "cancelled_by_airline")
        self.assertNotIn("Arrival", tracking.answer_text(self.con(), 41001))     # no ETA for a cancelled booking
        self.mail(CUST, "Re: Quote request FRA-ORD", "Yes, please rebook on that flight.", T0 + 3 * H, thread=41001)
        self.go(T0 + 4 * H)
        self.assertEqual(self.ship()["status"], "rebook_requested")
        self.assertTrue(any("YT 890" in r["body"] for r in self.outbox(party="airline", reason="customer accepted rebook offer")))
        self.mail(YT, "Booking BK-7Q2M9XKD confirmed", "your booking BK-7Q2M9XKD is confirmed on flight YT 890, ETA ORD 29 Nov 2026.", T0 + 5 * H)
        self.go(T0 + 6 * H)
        s = self.ship()
        self.assertEqual((s["status"], s["flight"], s["eta_current"]), ("confirmed", "YT 890", "2026-11-29"))
        self.assertTrue(self.outbox(reason="carrier update: rebook_confirmed", party="customer"))

    def test_price_above_quote_alerts_forwarder_only(self):
        self.booking()
        self.mail(YT, "Booking BK-7Q2M9XKD confirmed", "your booking BK-7Q2M9XKD is confirmed.\nPrice: 1191.40 EUR", T0)
        self.go(T0 + 60)
        f = self.outbox(party="forwarder", reason="airline price above our quote")
        self.assertEqual(len(f), 1)
        self.assertIn("+15.0%", f[0]["body"])
        self.assertFalse([r for r in self.outbox(party="customer") if "price" in (r["reason"] or "")])
        con = self.con()
        self.assertEqual(state.one(con, "SELECT kind FROM carrier_log WHERE kind='price_increase'")["kind"], "price_increase")

    def test_no_reference_matched_by_airline_and_lane(self):
        self.booking()
        self.booking(tid=41500, bk="BK-OTHERLANE", origin="MUC", dest="JFK")
        self.go(T0 + 60)
        self.mail(YT, "Flight YT 880 FRA-ORD 25 Nov delayed", "flight YT 880 FRA-ORD of 25 Nov is delayed by 24 hours due to a "
                  "technical issue. All shipments on board will arrive one day later.", T0 + H)
        self.mail("orion-cargo-air@hackloop.mail", "Flight OC 12 FRA-ORD delayed", "OC 12 FRA-ORD is delayed by 5 hours.", T0 + H)
        self.go(T0 + 2 * H)
        s = self.ship()
        self.assertEqual((s["status"], s["eta_current"]), ("delayed", "2026-11-27"))   # 26 Nov + 24 h
        self.assertEqual(self.ship(41500)["status"], "confirmed")
        con = self.con()
        self.assertEqual(state.one(con, "SELECT match FROM shipment_updates WHERE thread_id=41001 AND type='delayed'")["match"], "lane")
        self.assertEqual(state.one(con, "SELECT match FROM shipment_updates WHERE thread_id IS NULL")["match"], "no_match")

    def test_ambiguous_lane_is_not_guessed(self):
        self.booking()
        self.booking(tid=41600, bk="BK-SECONDFRA")
        self.go(T0 + 60)
        self.mail(YT, "Flight YT 880 FRA-ORD delayed", "flight FRA-ORD is delayed by 24 hours.", T0 + H)
        self.go(T0 + 2 * H)
        self.assertEqual(self.ship()["status"], "confirmed")
        self.assertEqual(self.ship(41600)["status"], "confirmed")
        self.assertTrue(self.outbox(party="forwarder", reason="unmatched carrier news"))

    def test_late_old_milestone_never_moves_back(self):
        con = self.con()
        self.assertEqual(state.next_status("arrived", "arrived", "departed"), ("arrived", "arrived"))
        self.assertEqual(state.next_status("delivered", "delivered", "delayed"), ("delivered", "delivered"))
        self.assertEqual(state.next_status("departed", "departed", "delayed"), ("delayed", "departed"))
        self.assertEqual(state.next_status("delayed", "departed", "arrived"), ("arrived", "arrived"))
        self.assertEqual(state.next_status("cancelled_by_airline", "confirmed", "confirmed"), ("confirmed", "confirmed"))
        con.close()


class DueWork(Base):
    def test_no_airline_news_after_eta_is_logged_once(self):
        self.booking()
        self.go(T0 + 60)
        self.go(T0 + 6 * DAY)                                # planned ETA 26 Nov passed by > 24 h, no arrival
        self.go(T0 + 7 * DAY)
        self.assertEqual(len(self.outbox(reason="no status after ETA")), 1)
        con = self.con()
        self.assertEqual(state.one(con, "SELECT COUNT(*) AS n FROM carrier_log WHERE kind='no_status_after_eta'")["n"], 1)

    def test_partner_address_from_partners_file(self):
        self.booking()
        p = os.path.join(self.dir, "partners.json")
        with open(p, "w") as f:
            json.dump({"ORD": "agent@ord-partner.example"}, f)
        with contextlib.redirect_stdout(io.StringIO()):
            run.main(["--db", self.db, "--once", "--now", str(T0 + 60), "--partners", p])
        run.PARTNERS.clear()
        self.assertEqual(self.outbox(party="partner")[0]["to_addr"], "agent@ord-partner.example")


class Invoice(Base):
    def deliver(self):
        self.booking()
        self.go(T0 + 60)
        self.assertFalse(self.outbox(reason="invoice after delivery"))          # not at airline confirmation
        con = self.con()
        self.assertIsNone(invoice.get(con, 41001))
        con.close()
        self.mail(YT, "Booking BK-7Q2M9XKD - arrived ORD", "Shipment arrived ORD 26 Nov 2026 09:40.", T0 + 3 * DAY)
        self.go(T0 + 3 * DAY + 60)
        self.assertFalse(self.outbox(reason="invoice after delivery"))          # not at arrival either
        self.mail(YT, "Booking BK-7Q2M9XKD - delivered, POD attached", "Shipment delivered to consignee 26 Nov 2026 15:10, POD attached.",
                  T0 + 4 * DAY)
        self.go(T0 + 4 * DAY + 60)

    def test_invoice_only_after_delivery_then_paid(self):
        self.deliver()
        inv = self.outbox(reason="invoice after delivery")
        self.assertEqual(len(inv), 1)
        self.assertIn("1246.00 EUR", inv[0]["body"])
        self.mail(CUST, "Re: Quote request FRA-ORD", "we have paid the invoice today by bank transfer.", T0 + 10 * DAY, thread=41001)
        self.go(T0 + 10 * DAY + 60)
        con = self.con()
        self.assertEqual(invoice.get(con, 41001)["status"], "paid_reported")
        with state.tx(con):
            invoice.mark_paid(con, "INV-41001", T0 + 12 * DAY)
        self.assertEqual(invoice.get(con, 41001)["status"], "paid")

    def test_issue_refuses_before_delivery(self):
        self.booking()
        self.go(T0 + 60)
        con = self.con()
        with self.assertRaises(ValueError):
            invoice.issue(con, state.shipment(con, 41001), T0)

    def test_reminders_then_forwarder(self):
        self.deliver()
        con = self.con()
        due = invoice.get(con, 41001)["due_at"]
        con.close()
        self.go(due - DAY)
        self.assertFalse(self.outbox(reason="payment reminder 1"))
        self.go(due + DAY + 1)
        self.go(due + DAY + 2)                               # same day again: no second reminder
        self.assertEqual(len(self.outbox(reason="payment reminder 1")), 1)
        self.go(due + 3 * DAY)
        self.assertFalse(self.outbox(reason="payment reminder 2"))
        self.go(due + 9 * DAY)
        self.assertEqual(len(self.outbox(reason="payment reminder 2")), 1)
        self.go(due + 17 * DAY)
        self.assertEqual(len(self.outbox(reason="invoice overdue after reminders")), 1)
        con = self.con()
        self.assertEqual(invoice.get(con, 41001)["status"], "overdue_human")


class Tracking(Base):
    def test_answer_repeats_carrier_report(self):
        self.booking()
        self.go(T0 + 60)
        before = tracking.answer_text(self.con(), 41001)
        self.assertIn("has not reported any movement yet", before)
        self.assertIn("planned", before.lower())
        self.mail(YT, "Booking BK-7Q2M9XKD - departed", "Shipment departed on flight YT 880, AWB 160-12345675. "
                  "Track it at https://track.yellowtail.example/160-12345675", T0 + DAY)
        self.mail(YT, "Booking BK-7Q2M9XKD - DELAYED", "moved from YT 880 to YT 4412, new ETA ORD 28 Nov 2026 09:15.", T0 + DAY + H)
        self.mail(CUST, "Re: Quote request FRA-ORD", "Hi, where is our shipment now?", T0 + DAY + 2 * H, thread=41001)
        self.go(T0 + DAY + 3 * H)
        ans = [r for r in self.outbox(party="customer") if r["reason"] == "tracking answer (customer asked)"]
        self.assertEqual(len(ans), 1)
        for want in ("28 Nov 2026, 09:15", "160-12345675", "YT 4412", "https://track.yellowtail.example/160-12345675", "delayed"):
            self.assertIn(want, ans[0]["body"])
        self.assertIn("as reported by the airline", ans[0]["body"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(run.main(["--db", self.db, "--where", "BK-7Q2M9XKD"]), 0)
        self.assertIn("28 Nov 2026, 09:15", buf.getvalue())             # the CLI answers from the same state


class Safety(Base):
    def test_cursor_mail_processed_once(self):
        self.booking()
        self.mail(YT, "Booking BK-7Q2M9XKD - DELAYED", "new ETA ORD 28 Nov 2026.", T0 + H)
        self.go(T0 + 2 * H)
        n = len(self.outbox())
        con = self.con()
        nu = state.one(con, "SELECT COUNT(*) AS n FROM shipment_updates")["n"]
        con.execute("DELETE FROM carrierops_cursor")                 # even without cursor and seen list nothing is doubled
        con.execute("DELETE FROM carrierops_seen")
        con.close()
        self.go(T0 + 3 * H)
        self.assertEqual(len(self.outbox()), n)
        con = self.con()
        self.assertEqual(state.one(con, "SELECT COUNT(*) AS n FROM shipment_updates")["n"], nu)

    def test_clerk_tables_read_only(self):
        self.booking()
        con = self.con()
        with self.assertRaises(sqlite3.OperationalError):
            con.execute("UPDATE clerk.bookings SET status='x'")

    def test_separate_ops_db(self):
        self.booking()
        ops = os.path.join(self.dir, "ops.db")
        con = state.connect(self.db, ops)
        run.run_once(con, T0 + 60)
        con.close()
        c = sqlite3.connect(self.db)
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(names & set(state.OWN_TABLES))
        c = sqlite3.connect(ops)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 5)

    def test_same_file_needs_wal(self):
        p = os.path.join(self.dir, "plain.db")
        sqlite3.connect(p).execute("CREATE TABLE mails(id INTEGER)").connection.commit()
        with self.assertRaises(SystemExit):
            state.connect(p)
        state.connect(p, os.path.join(self.dir, "ops2.db")).close()      # a separate ops DB works on any clerk DB

    def test_baseline_drafts_nothing(self):
        self.booking()
        self.mail(YT, "Booking BK-7Q2M9XKD - DELAYED", "new ETA ORD 28 Nov 2026.", T0 + H)
        con = self.con()
        run.baseline(con, T0 + 2 * H)
        run.run_once(con, T0 + 2 * H)
        self.assertEqual(len(self.outbox()), 0)

    def test_no_network_imports(self):
        bad = {"socket", "urllib", "http", "smtplib", "requests", "ssl", "ftplib", "imaplib", "poplib", "asyncio",
               "subprocess", "core", "booking", "sourcing", "router", "llm"}
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for root, _, files in os.walk(here):
            for f in files:
                if not f.endswith(".py"):
                    continue
                with open(os.path.join(root, f)) as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                        [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
                    for n in names:
                        self.assertNotIn(n.split(".")[0], bad, "%s imports %s" % (f, n))


if __name__ == "__main__":
    unittest.main()
