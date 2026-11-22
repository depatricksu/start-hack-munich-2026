"""5U, 22 Nov 02:32: a mail from nordlicht.audio@hackloop.mail asks for 'your price for our shipment to Bangkok to this
address'. Our customer is nordlicht-audio@hackloop.mail. An address that imitates a known customer never gets a reply."""
import os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main  # noqa: E402
from router.route import lookalike, route  # noqa: E402

KNOWN = ["nordlicht-audio@hackloop.mail", "lindqvist-medtech@hackloop.mail", "kessler-feinmechanik@hackloop.mail"]
BODY = ("Hello,\n\nour usual mailbox has been down since this morning and I cannot open anything in it. Could you confirm your price for "
        "our shipment to Bangkok (BKK) to this address, so that I can pass it on today?\n\nMira Petersen\nNordlicht Audio")


def mail(sender, start=True, mid=940001, subject="Our mailbox is down: price for Bangkok (BKK)", body=BODY):
    return {"id": mid, "thread_id": mid, "sender": sender, "subject": subject, "body": body, "attachments": [], "is_thread_start": start,
            "received_at": 1.0, "raw": {}}


class Lookalike(unittest.TestCase):
    def test_the_real_case(self):
        self.assertEqual(lookalike("nordlicht.audio@hackloop.mail", KNOWN), "nordlicht-audio@hackloop.mail")
        self.assertEqual(route(mail("nordlicht.audio@hackloop.mail"), customers=KNOWN), "spam")

    def test_other_imitations(self):
        for fake in ("nordlicht_audio@hackloop.mail", "nordlichtaudio@hackloop.mail", "nordlicht-audi0@hackloop.mail", "nordlich-audio@hackloop.mail",
                     "nordlicht-audio@hackl00p.mail", "nordlicht-audio@hackloop.mall", "NORDLICHT.AUDIO@hackloop.mail", "lindqvist-rnedtech@hackloop.mail"):
            self.assertIsNotNone(lookalike(fake, KNOWN), fake)

    def test_the_name_with_something_added(self):
        """Live 03:03: kessler-feinmechanik.mail@ got through the first rule and the clerk asked it for the weight."""
        for fake in ("kessler-feinmechanik.mail@hackloop.mail", "kessler-feinmechanik-new@hackloop.mail", "office.kessler-feinmechanik@hackloop.mail",
                     "kessler-feinmech@hackloop.mail", "kessler-feinmechanik@gmail.com", "nordlicht-audio@outlook.com"):
            self.assertEqual(lookalike(fake, KNOWN), "kessler-feinmechanik@hackloop.mail" if "kessler" in fake else "nordlicht-audio@hackloop.mail", fake)
        said = ("Hello,\n\nwe are switching mail systems this week and my old mailbox is being closed. Please send your offer for our shipment to "
                "Lima (LIM) to this address instead, and use it for everything that follows.\n\nJonas Kessler\nKessler Feinmechanik GmbH, Ulm")
        self.assertEqual(route(mail("kessler-feinmechanik.mail@hackloop.mail", subject="New mail address: offer for Lima (LIM)", body=said), customers=KNOWN), "spam")

    def test_the_words_alone_are_enough_from_a_sender_we_never_quoted(self):
        said = "Hello,\n\nour usual mailbox has been down since this morning. Could you confirm your price for our shipment to Bangkok to this address?\n\nMira"
        self.assertEqual(route(mail("mira.p@some-other-firm.com", body=said), customers=KNOWN), "spam")
        self.assertEqual(route(mail("jonas@elsewhere.org", subject="New mail address", body="Please use this address from now on and send the offer here."), customers=KNOWN), "spam")
        # a real request that mentions an address is still a request
        real = "Hello, please quote 300 kg, 1.2 cbm from FRA to JFK and send the offer to this address. Thanks"
        self.assertEqual(route(mail("buyer@brand-new.com", subject="Quote", body=real), customers=KNOWN), "rfq")
        # the customer we know may write whatever they like
        self.assertEqual(route(mail("nordlicht-audio@hackloop.mail", subject="New mail address", body="Our new address is x@y.z, please use it from now on."),
                               customers=KNOWN), "rfq")

    def test_real_and_new_customers_are_not_imitations(self):
        for real in KNOWN + ["nordlicht-audio@HACKLOOP.mail".lower(), "new-customer@hackloop.mail", "nordpol-studio@hackloop.mail", "audio-nordlicht@hackloop.mail",
                             "kessler@other-company.com"]:
            self.assertIsNone(lookalike(real, KNOWN), real)
        self.assertIsNone(lookalike("buyer2@acme.mail", ["buyer1@acme.mail"]))        # numbered mailboxes of one company
        self.assertIsNone(lookalike("export-team2@firma.de", ["export-team1@firma.de"]))
        self.assertIsNone(lookalike("a@b.mail", ["a@x.mail"]))                        # too short to say anything
        self.assertEqual(route(mail("nordlicht-audio@hackloop.mail", subject="Air freight quote to BKK",
                                    body="Please quote 468 kg, 3.98 cbm to BKK, cheapest."), customers=KNOWN), "rfq")
        self.assertEqual(route(mail("new-customer@hackloop.mail", subject="Air freight quote to BKK", body="Please quote 468 kg to BKK."), customers=KNOWN), "rfq")
        self.assertEqual(route(mail("nordlicht.audio@hackloop.mail"), customers=None), "rfq")              # nobody known yet: nothing to imitate

    def test_the_clerk_sends_nothing_and_opens_no_request(self):
        real = mail("nordlicht-audio@hackloop.mail", mid=940010, subject="Air freight quote", body="x")
        db.save_mail(real)
        db.new_session(real)
        fake = mail("nordlicht.audio@hackloop.mail", mid=940011)
        main.process(fake)
        self.assertIsNone(db.session(940011))                                  # no request, nothing for a person to chase
        kinds = [e["kind"] for e in db.con().execute("SELECT kind FROM events WHERE thread_id=940011").fetchall()]
        self.assertIn("lookalike_sender", kinds)
        self.assertFalse([k for k in kinds if k.startswith("mail_out") or k == "llm"])   # no reply and no gateway call


if __name__ == "__main__":
    unittest.main()
