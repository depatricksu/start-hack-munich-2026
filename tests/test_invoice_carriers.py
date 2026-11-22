"""Extra features: invoices + payment reminders (booking/invoice.py) and the carrier reliability flags
(monitor/carriers.py). Run: python -m unittest tests.test_invoice_carriers"""
import json, os, tempfile, time, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from core import db, mailbox  # noqa: E402
from booking import crm, handlers, invoice  # noqa: E402
from monitor import carriers  # noqa: E402
from sourcing import bids  # noqa: E402

CUST = "sara.lind@lindqvist-medtech.mail"


def mails_out(tid):
    """Customer mails about the invoice (DRY_RUN logs them as mail_out_dry_run)."""
    rows = [json.loads(r[0]) for r in db.con().execute(
        "SELECT data FROM events WHERE thread_id=? AND kind IN ('mail_out','mail_out_dry_run')", (tid,))]
    return [r for r in rows if "INV-" in r["body"]]


class Invoices(unittest.TestCase):
    n = 9880000

    def _confirmed(self, lang="en", truck=True):
        Invoices.n += 10
        tid = Invoices.n
        m = mailbox.normalize({"id": tid, "from": CUST, "subject": "Air freight FRA-ORD", "body": "cheapest FRA to ORD"})
        db.save_mail(m); db.new_session(m)
        chosen = {"airline": "Meridian Freightways", "origin": "FRA", "destination": "ORD", "currency": "EUR",
                  "total": "1921.60", "total_eur": "1921.60"}
        if truck:
            chosen.update(flight_total="1728.00", flight_currency="EUR", trucker="Neckarstrom Kurier",
                          trucker_total="193.60", trucker_currency="EUR")
        db.update_session(tid, status="booked", customer=CUST, chosen=chosen)
        crm.upsert(tid, customer=CUST, subject="Air freight FRA-ORD", last_customer_mail_id=tid, airline="Meridian Freightways",
                   origin="FRA", destination="ORD", status="booked", language=lang, price="1921.60", currency="EUR",
                   booking_reference="BK-IV%06d" % (tid % 1000000), booked_at=time.time())
        return tid

    def _airline_confirms(self, tid):
        ref = crm.get(tid)["booking_reference"]
        handlers.handle_booking_confirmation(mailbox.normalize({
            "id": tid + 5, "from": "meridian-freightways@hackloop.mail", "subject": "Booking %s confirmed" % ref,
            "body": "your booking %s is confirmed.\nYour reference: GOOGLE-%s" % (ref, tid)}))

    def _reply(self, tid, body, i=1):
        handlers.handle_follow_up(mailbox.normalize({"id": tid + i, "from": CUST, "subject": "Re: Air freight FRA-ORD",
                                                     "body": body, "in_reply_to": tid, "references": [tid]}))

    def test_confirmation_creates_the_invoice_with_flight_and_truck_lines(self):
        tid = self._confirmed()
        self._airline_confirms(tid)
        inv = invoice.get(tid)
        self.assertEqual((inv["number"], inv["amount"], inv["status"]), ("INV-%s" % tid, "1921.60", "open"))
        lines = json.loads(inv["lines"])
        self.assertEqual([v for _, v in lines], ["1728.00", "193.60"])
        self.assertIn("Neckarstrom Kurier", inv["body"])
        self.assertIn("GOOGLE-%s" % tid, inv["body"])
        self.assertEqual(mails_out(tid), [])                    # INVOICE_MAIL=0: a draft, nothing mailed
        self.assertAlmostEqual(inv["due_at"] - inv["issued_at"], invoice.TERMS_DAYS * invoice.DAY, delta=1)

    def test_invoice_is_mailed_with_a_pdf_when_switched_on(self):
        tid = self._confirmed(lang="de", truck=False)
        invoice.INVOICE_MAIL = True
        try:
            self._airline_confirms(tid)
        finally:
            invoice.INVOICE_MAIL = False
        out = mails_out(tid)
        self.assertEqual(len(out), 1)
        self.assertIn("Rechnung INV-%s" % tid, out[0]["body"])
        self.assertEqual(out[0]["attachments"][0]["filename"], "INV-%s.pdf" % tid)
        self.assertEqual(invoice.get(tid)["sent"], 1)

    def test_reminders_then_a_person(self):
        tid = self._confirmed()
        inv = invoice.issue(tid)
        due = inv["due_at"]
        mine = lambda now: [x for x in invoice.tick(now=now) if x[0] == inv["number"]]
        self.assertEqual(mine(due - 60), [])                    # not due yet
        self.assertEqual(mine(due + 60), [(inv["number"], "reminder 1")])
        self.assertEqual(mine(due + 120), [])                   # not again the same week
        week = invoice.REMINDER_EVERY_DAYS * invoice.DAY
        self.assertEqual(mine(due + 60 + week), [(inv["number"], "reminder 2")])
        self.assertEqual(mine(due + 60 + 2 * week), [(inv["number"], "overdue_human")])
        self.assertEqual(invoice.get(tid)["status"], "overdue_human")
        r = invoice.receivables(now=due + 60 + 2 * week)
        self.assertIn(inv["number"], [x["number"] for x in r["overdue"]])

    def test_customer_says_paid_stops_reminders(self):
        for body in ("Hi Lena, we have paid the invoice today. Regards, Sara",
                     "Payment has been made, see attached proof.",
                     "Hallo, der Betrag wurde heute überwiesen."):
            tid = self._confirmed()
            inv = invoice.issue(tid)
            self._reply(tid, body)
            self.assertEqual(invoice.get(tid)["status"], "paid_reported", body)
            self.assertNotEqual(db.session(tid)["status"], "needs_human", body)
            self.assertEqual(len(mails_out(tid)), 1, body)            # the short thank-you
            self.assertNotIn(inv["number"], [x[0] for x in invoice.tick(now=inv["due_at"] + 60)], body)

    def test_not_paid_yet_is_not_paid(self):
        for body in ("We have not paid yet, will do once the goods arrive.", "We will transfer the amount next week.",
                     "Sobald die Ware da ist, wird bezahlt."):
            tid = self._confirmed()
            invoice.issue(tid)
            self._reply(tid, body)
            self.assertEqual(invoice.get(tid)["status"], "open", body)

    def test_send_invoice_again_is_answered_and_a_dispute_goes_to_a_person(self):
        tid = self._confirmed()
        invoice.issue(tid)
        self._reply(tid, "Could you please send me the invoice again? I can't find it.")
        self.assertEqual(len(mails_out(tid)), 1)
        self.assertNotEqual(db.session(tid)["status"], "needs_human")
        tid = self._confirmed()
        invoice.issue(tid)
        self._reply(tid, "The invoice is wrong, the amount is too high compared to your offer.")
        self.assertEqual(mails_out(tid), [])
        self.assertEqual(db.session(tid)["status"], "needs_human")

    def test_no_invoice_yet_keeps_the_old_path(self):
        tid = self._confirmed()                                  # booked, the airline has not confirmed
        self._reply(tid, "Please send the invoice.")
        self.assertIsNone(invoice.get(tid))
        self.assertEqual(db.session(tid)["status"], "needs_human")

    def test_cancellation_cancels_the_invoice(self):
        tid = self._confirmed()
        invoice.issue(tid)
        invoice.cancel(tid, "customer cancelled")
        self.assertEqual(invoice.get(tid)["status"], "cancelled")
        self.assertNotIn("INV-%s" % tid, [x[0] for x in invoice.tick(now=time.time() + 400 * invoice.DAY)])

    def test_forwarder_marks_paid(self):
        tid = self._confirmed()
        invoice.issue(tid)
        self.assertEqual(invoice.mark_paid("INV-%s" % tid)["status"], "paid")


class Carriers(unittest.TestCase):
    n = 9890000

    def setUp(self):
        bids.ensure()
        crm.con()

    def _bid(self, carrier, replied_after=None, status="ok", role="airline", ago=3600):
        Carriers.n += 1
        now = time.time()
        db.con().execute("INSERT INTO bids(thread_id,carrier,role,status,requested_at,replied_at) VALUES(?,?,?,?,?,?)",
                         (Carriers.n, carrier, role, status, now - ago,
                          None if replied_after is None else now - ago + replied_after))

    def test_flags(self):
        for i in range(10):                                      # answers fast, sometimes "we don't fly there"
            self._bid("Good Air", 40, "declined" if i % 2 else "ok")
        for i in range(10):                                      # 4 of 10 never answer
            self._bid("Silent Air", None if i < 4 else 40)
        for i in range(10):                                      # 2 of 10 answer after the bid wait
            self._bid("Slowpoke Trucks", 200 if i < 2 else 30, role="trucker")
        self._bid("New Air", None)
        self._bid("Pending Air", None, ago=30)                   # still within its time
        cards = {r["carrier"]: r for r in carriers.refresh()}
        self.assertEqual(cards["Good Air"]["level"], "ok")
        self.assertEqual(cards["Good Air"]["stats"]["declined_lane"], 5)
        self.assertEqual(cards["Silent Air"]["level"], "red")
        self.assertIn("no answer to our price request x4", cards["Silent Air"]["reasons"])
        self.assertEqual(len(cards["Silent Air"]["examples"]["no_answer"]), 4)
        self.assertEqual(cards["Slowpoke Trucks"]["level"], "amber")
        self.assertEqual(cards["New Air"]["level"], "unknown")   # one job is not enough to judge
        self.assertEqual(cards["Pending Air"]["jobs"], 0)
        kinds = [json.loads(r[0])["carrier"] for r in db.con().execute("SELECT data FROM events WHERE kind='carrier_flagged'")]
        self.assertIn("Silent Air", kinds)
        self.assertEqual(carriers.flag("silent air")["level"], "red")
        self.assertIn("WATCH CARRIER Silent Air", carriers.watch_note("Silent Air", "Good Air"))
        self.assertEqual(carriers.watch_note("Good Air", None), "")

    def test_two_cancellations_are_red_even_with_few_jobs(self):
        for i in range(2):
            Carriers.n += 1
            crm.upsert(Carriers.n, airline="Flaky Wings", status="cancelled_by_airline", booked_at=time.time() - 100)
        card = {r["carrier"]: r for r in carriers.scorecard()}["Flaky Wings"]
        self.assertEqual(card["level"], "red")
        self.assertIn("cancelled or refused a booking x2", card["reasons"])


if __name__ == "__main__":
    unittest.main()
