"""5U 00:13: DELETE /v1/portal/bookings/{ref}. A clear 'please cancel' after the booking is cancelled at 5U and
confirmed; questions, negations and failed calls still go to a human. Run: python -m unittest tests.test_cancel_booking"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from core import config, db, mailbox  # noqa: E402
from booking import crm, handlers  # noqa: E402


class CancelBooking(unittest.TestCase):
    n = 9970000

    def _booked(self, lang="en"):
        CancelBooking.n += 10
        tid = CancelBooking.n
        m = mailbox.normalize({"id": tid, "from": "sara@lindqvist-medtech.mail", "subject": "Air freight FRA-ORD",
                               "body": "cheapest FRA to ORD, 540 kg"})
        db.save_mail(m); db.new_session(m)
        db.update_session(tid, status="booked", customer="sara@lindqvist-medtech.mail")
        crm.upsert(tid, customer="sara@lindqvist-medtech.mail", subject="Air freight FRA-ORD", last_customer_mail_id=tid,
                   airline="Meridian Freightways", origin="FRA", destination="ORD", status="booked", language=lang,
                   booking_reference="BK-CX%06d" % (tid % 1000000))
        return tid

    def _reply(self, tid, body):
        handlers.handle_follow_up(mailbox.normalize({"id": tid + 1, "from": "sara@lindqvist-medtech.mail",
                                                     "subject": "Re: Air freight FRA-ORD", "body": body,
                                                     "in_reply_to": tid, "references": [tid]}))

    def test_clear_cancel_is_cancelled_and_confirmed(self):
        for body, lang in (("Please cancel the booking, our customer cancelled the order.", "en"),
                           ("Bitte stornieren Sie die Buchung, die Sendung wird nicht mehr benötigt.", "de")):
            tid = self._booked(lang)
            self._reply(tid, body)
            self.assertEqual(db.session(tid)["status"], "cancelled")
            self.assertEqual(crm.get(tid)["status"], "cancelled")
            out = [r[0] for r in db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind LIKE 'mail_out%'", (tid,))]
            self.assertEqual(len(out), 1)
            self.assertIn("BK-CX", out[0])

    def test_question_or_negation_goes_to_a_human(self):
        for body in ("What are your cancellation fees?", "Please don't cancel anything, just confirm the date.",
                     "Can we still cancel if needed?"):
            tid = self._booked()
            self._reply(tid, body)
            self.assertNotEqual(db.session(tid)["status"], "cancelled", body)

    def test_failed_cancel_call_goes_to_a_human(self):
        tid = self._booked()
        config.DRY_RUN, orig = False, mailbox.api
        mailbox.api = lambda *a, **k: (404, {"detail": "unknown booking_reference"})
        try:
            self._reply(tid, "Please cancel the booking.")
        finally:
            config.DRY_RUN, mailbox.api = True, orig
        self.assertEqual(db.session(tid)["status"], "needs_human")


if __name__ == "__main__":
    unittest.main()
