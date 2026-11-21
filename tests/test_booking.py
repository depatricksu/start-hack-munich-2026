"""Task 04 end to end with fake mails, DRY_RUN, no network. Run: python -m unittest tests.test_booking -v"""
import json, os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main  # noqa: E402
from booking import crm, handlers  # noqa: E402

CUSTOMER = "anna.schmidt@customer-example.mail"


def mail(id, body, subject="Quote HAM to BOG", sender=CUSTOMER, refs=None):
    return {"id": id, "from": sender, "subject": subject, "body": body, "references": refs or [],
            "in_reply_to": refs[-1] if refs else None}


def sent(thread_id):
    rows = db.con().execute("SELECT data FROM events WHERE kind='mail_out_dry_run' AND thread_id=?", (thread_id,))
    return [json.loads(r["data"]) for r in rows]


def quote(tid, portal=False):
    main.process(main.mailbox.normalize(mail(tid, "Hi, please quote 90 kg, 0.4 cbm from HAM to BOG. Cheapest please.")))
    if portal:   # pretend the portal won: chosen option carries a rate_id
        s = db.session(tid)
        chosen = dict(json.loads(s["chosen"]), source="portal", rate_id="R-test12345678", airline="Riverbend Cargo")
        db.update_session(tid, chosen=chosen)
    return db.session(tid)


class TestClassify(unittest.TestCase):
    def test_words(self):
        self.assertEqual(handlers.classify("Great, please book it."), "accept")
        self.assertEqual(handlers.classify("Passt, bitte buchen."), "accept")
        self.assertEqual(handlers.classify("No thanks, too expensive."), "decline")
        self.assertEqual(handlers.classify("Could you do it faster?"), "unclear")
        self.assertEqual(handlers.classify("Yes please book.\n\n> Our all-in price is ... could you?"), "accept")


class TestFlow(unittest.TestCase):
    def test_portal_accept_book_confirm(self):
        tid = 1001
        self.assertEqual(quote(tid, portal=True)["status"], "quoted")
        main.process(main.mailbox.normalize(mail(1002, "Yes, please book it.", "Re: Quote HAM to BOG", refs=[tid])))
        b = crm.get(tid)
        self.assertEqual((b["status"], b["booking_reference"]), ("booked", "BK-DRYRUN01"))
        self.assertEqual(db.session(tid)["status"], "booked")
        self.assertIn("BK-DRYRUN01", sent(tid)[-1]["body"])
        main.process(main.mailbox.normalize(mail(1003, "Your booking is confirmed.", "Booking BK-DRYRUN01 confirmed",
                                                 sender="riverbend-cargo@hackloop.mail")))
        self.assertEqual(crm.get(tid)["status"], "confirmed")
        self.assertIn("confirmed", sent(tid)[-1]["body"])

    def test_sheet_airline_books_by_mail(self):
        tid = 2001
        s = quote(tid)
        self.assertEqual(json.loads(s["chosen"])["source"], "sheet")
        main.process(main.mailbox.normalize(mail(2002, "Go ahead.", "Re: Quote HAM to BOG", refs=[tid])))
        self.assertEqual(crm.get(tid)["status"], "requested")
        to = [m["to"] for m in sent(tid)]
        self.assertIn("cobalt-skylift@hackloop.mail", to)
        self.assertEqual(to[-1], CUSTOMER)
        main.process(main.mailbox.normalize(mail(2003, "Booked for GOOGLE-2001.", "Booking BK-ABC12345 confirmed",
                                                 sender="cobalt-skylift@hackloop.mail")))
        self.assertEqual((crm.get(tid)["status"], crm.get(tid)["booking_reference"]), ("confirmed", "BK-ABC12345"))

    def test_unclear_goes_to_human(self):
        tid = 3001
        quote(tid)
        main.process(main.mailbox.normalize(mail(3002, "Can you do it cheaper?", "Re: Quote HAM to BOG", refs=[tid])))
        self.assertEqual(db.session(tid)["status"], "needs_human")
        self.assertIsNone(crm.get(tid))

    def test_decline(self):
        tid = 4001
        quote(tid)
        main.process(main.mailbox.normalize(mail(4002, "No thanks, we found another option.", "Re: x", refs=[tid])))
        self.assertEqual(db.session(tid)["status"], "lost")


if __name__ == "__main__":
    unittest.main()
