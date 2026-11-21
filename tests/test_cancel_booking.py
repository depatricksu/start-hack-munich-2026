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


class CancelLive(CancelBooking):
    """Live, 22 Nov 00:51 (thr 25263, round 88): booked by mail with Wayzata, the customer cancelled 18 s later, before
    the airline had sent its booking reference; then asked twice more with 'Could you please cancel booking BK-...?'.
    Nothing was cancelled until it was done by hand."""

    def test_a_polite_question_is_a_cancel_request(self):
        for body in ("Could you please cancel booking BK-1J8EL0PB and let me know once it\u2019s done?",
                     "Thanks for the update! We had to cancel the shipment because our buyer withdrew the order, so could you please cancel booking BK-1J8EL0PB?",
                     "Our buyer has withdrawn the order, so we need to cancel the shipment. Please don\u2019t go ahead with the booking. If it\u2019s already booked, please cancel it."):
            tid = self._booked()
            self._reply(tid, body)
            self.assertEqual(db.session(tid)["status"], "cancelled", body)

    def test_inherited_questions_stay_with_a_person(self):
        for body in ("What are your cancellation fees?", "Can we still cancel if needed?", "Do we have to pay a fee if we cancel later?",
                     "Please don\u2019t cancel anything, just confirm the date."):
            self.assertFalse(handlers.wants_cancel(body), body)

    def _requested_by_mail(self):
        tid = self._booked()
        db.con().execute("UPDATE bookings SET booking_reference=NULL, status='requested', airline='Wayzata Air Cargo' WHERE thread_id=?", (tid,))
        db.con().commit()
        db.update_session(tid, status="booking_requested")
        return tid

    def test_cancel_before_the_airlines_reference_is_done_when_it_arrives(self):
        import json
        tid = self._requested_by_mail()
        self._reply(tid, "Our buyer has withdrawn the order, so we need to cancel the shipment. If it is already booked, please cancel it.")
        s = db.session(tid)
        self.assertEqual(json.loads(s["fields"] or "{}").get("cancel_wanted"), tid + 1)       # remembered, nothing to cancel yet
        self.assertEqual(crm.get(tid)["status"], "requested")
        handlers.handle_booking_confirmation(mailbox.normalize({
            "id": tid + 2, "from": "wayzata-air-cargo@hackloop.mail", "subject": "Booking BK-WZ000001 confirmed",
            "body": "your booking BK-WZ000001 is confirmed.\nYour reference: %s\nStatus: booked" % crm.team_reference(tid)}))
        self.assertEqual(crm.get(tid)["status"], "cancelled")
        self.assertEqual(db.session(tid)["status"], "cancelled")
        out = [json.loads(r[0])["body"] for r in db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind LIKE 'mail_out%' ORDER BY id", (tid,))]
        self.assertIn("I have cancelled booking BK-WZ000001", out[-1])
        self.assertFalse(any("Good news" in b or "has confirmed" in b for b in out), out)       # never "confirmed" to a customer who cancelled

    def test_asking_again_while_it_waits_for_a_person_cancels(self):
        tid = self._booked()
        db.update_session(tid, status="needs_human", note=handlers.CANCEL_NOTE + ": Hi there, our buyer has withdrawn the order")
        self._reply(tid, "Just to confirm, the shipment is no longer going ahead. Could you please cancel the booking and let me know once it is done?")
        self.assertEqual(db.session(tid)["status"], "cancelled")
        self.assertEqual(crm.get(tid)["status"], "cancelled")
