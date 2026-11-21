"""Two holes from Patrick's red-team run (21 Nov 23:29) in core/dg and router."""
import os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

import base64, json, time  # noqa: E402
from core import db, main  # noqa: E402
import dg  # noqa: E402
from router.route import route  # noqa: E402
from sourcing import bids  # noqa: E402


class OutdatedPackingList(unittest.TestCase):
    def test_sentences_that_disown_the_file(self):
        for said in ("The attached packing list is OUTDATED, the correct weight is 820 kg.",
                     "Please ignore the attachment, it is from the last shipment.",
                     "The packing list attached is an old version and no longer valid.",
                     "Die Packliste im Anhang ist veraltet, das richtige Gewicht ist 820 kg.",
                     "La liste de colisage jointe est périmée.",
                     "La distinta allegata non è aggiornata."):
            self.assertTrue(dg.mail_disowns_attachment(said), said)

    def test_a_normal_mail_with_a_packing_list_does_not(self):
        for said in ("Please find the packing list attached. 12 cartons, 540 kg.",
                     "Details are in the attached file. We need the cheapest option.",
                     "FW: old mail below. The packing list is attached.",
                     "Our old forwarder was too slow. Packing list attached, please quote."):
            self.assertFalse(dg.mail_disowns_attachment(said), said)

    def test_the_mail_wins_when_it_says_the_file_is_outdated(self):
        pl = base64.b64encode(b"Packing list\nGross weight (kg): 540\nVolume (cbm): 2.1\n").decode()
        def run(i, body):
            m = main.mailbox.normalize({"id": i, "from": "buyer%d@acme.mail" % i, "subject": "Quote", "body": body,
                                        "attachments": [{"id": "PL.txt", "filename": "PL.txt", "content_base64": pl}]})
            main.process(m)
            return json.loads(db.session(i)["fields"])
        f = run(8840001, "please quote 820 kg, 2.1 cbm HAM to BOG, machine parts. The attached packing list is outdated, the correct weight is 820 kg.")
        self.assertEqual(f["weight_kg_total"], 820)
        self.assertNotIn("attachment_used", f)
        f = run(8840002, "please quote 820 kg, 2.1 cbm HAM to BOG, machine parts. Packing list attached.")
        self.assertEqual(f["weight_kg_total"], 540)                 # unchanged rule: the packing list beats the mail


class Bounce(unittest.TestCase):
    def mail(self, sender, subject, body="x"):
        return {"sender": sender, "subject": subject, "body": body, "attachments": [], "is_thread_start": True}

    def test_a_bounce_is_never_a_request(self):
        self.assertEqual(route(self.mail("mailer-daemon@hackloop.mail", "Undelivered Mail Returned to Sender")), "bounce")
        self.assertEqual(route(self.mail("postmaster@acme.mail", "Delivery Status Notification (Failure)")), "bounce")
        self.assertEqual(route(self.mail("it@acme.mail", "Mail delivery failed: returning message to sender")), "bounce")
        self.assertEqual(route(self.mail("buyer@acme.mail", "Quote 300 kg FRA to JFK", "please quote 300 kg, 1 cbm")), "rfq")

    def test_the_bid_is_closed_so_the_quote_does_not_wait(self):
        bids.ensure()
        cur = db.con().execute("INSERT INTO bids(thread_id, carrier, kind, requested_at, email, role, required, status) "
                               "VALUES(8840009, 'Nordlicht Haulage', 'trucker', ?, 'nordlicht@hackloop.mail', 'trucker', 1, 'asked')", (time.time(),))
        bid = cur.lastrowid
        bids.on_bounce({"id": 99, "thread_id": 99, "sender": "mailer-daemon@hackloop.mail",
                        "subject": "Undelivered Mail Returned to Sender", "body": "... Pickup 20103 to HAM airport [BID-%d] ..." % bid})
        r = db.con().execute("SELECT status, replied_at FROM bids WHERE id=?", (bid,)).fetchone()
        self.assertEqual(r["status"], "send_failed")
        self.assertIsNotNone(r["replied_at"])


if __name__ == "__main__":
    unittest.main()
