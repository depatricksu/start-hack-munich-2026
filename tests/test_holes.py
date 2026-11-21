"""Red-team holes in the quote path: impossible weights, '1.200 kg', fake desk senders, model promises, long mails.
Run: python -m unittest tests.test_holes -v"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "holes.db"))
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")

from shared.rfq import gate
from router.route import route
from llm import extract as llm

MAIL = {"subject": "RFQ", "body": "", "sender": "anna.schmidt@x-example.mail"}


def fields(**kw):
    f = {"kind": "new_request", "origin": "HAM", "destination": "BOG", "weight_kg": 90, "volume_cbm": 0.4,
         "pieces": [], "prefer": "cheapest", "missing": []}
    f.update(kw)
    return f


class TestWeights(unittest.TestCase):
    def gate(self, body, **kw):
        return gate(fields(**kw), dict(MAIL, body=body))

    def test_impossible_weights_stop(self):
        self.assertFalse(self.gate("90 kg HAM to BOG", weight_kg=-50)[0])
        self.assertFalse(self.gate("250000 kg HAM to BOG", weight_kg=250000)[0])
        self.assertFalse(self.gate("please quote -50 kg HAM to BOG", weight_kg=50)[0])   # minus lost by the reader

    def test_german_thousands(self):
        ok, note = self.gate("Bitte 1.200 kg von HAM nach BOG", weight_kg=1.2)
        self.assertFalse(ok)
        self.assertIn("1200", note)
        self.assertTrue(self.gate("Bitte 1.200 kg von HAM nach BOG", weight_kg=1200)[0])  # read right: fine
        self.assertTrue(self.gate("Please quote 1,5 kg HAM to BOG", weight_kg=1.5)[0])    # real decimal: fine

    def test_normal_still_ok(self):
        self.assertTrue(self.gate("Please quote 90 kg, 0.4 cbm from HAM to BOG")[0])


class TestRouter(unittest.TestCase):
    def r(self, sender):
        return route({"sender": sender, "subject": "x", "body": "where is it?", "attachments": [], "is_thread_start": True})

    def test_only_real_desks(self):
        self.assertEqual(self.r("tracking@hackloop.mail"), "tracking")
        self.assertEqual(self.r("ratedesk@hackloop.mail"), "ratedesk")
        self.assertEqual(self.r("tracking@evil-example.mail"), "rfq")
        self.assertEqual(self.r("ratedesk@evil-example.mail"), "rfq")


class TestReply(unittest.TestCase):
    def test_promises_fall_back(self):
        for bad in ["Hi Anna, our price is {PRICE}. Price guaranteed until 2027!",
                    "Hi, {PRICE} with {AIRLINE}, and we give you 10% discount.",
                    "Hallo, {PRICE} mit {AIRLINE}, kostenlose Abholung inklusive.",
                    "Hi, {PRICE}. Pay here: http://evil.example/pay",
                    "Hi, {PRICE}, that is 99 EUR less than others."]:
            text, ok = llm.safe_reply(bad, "en")
            self.assertFalse(ok, bad)
            self.assertIn("{PRICE}", text)

    def test_german_fallback(self):
        text, ok = llm.safe_reply("Preis {PRICE}, garantiert!", "de")
        self.assertIn("Luftfracht Export", text)

    def test_clean_reply_kept(self):
        good = "Hi Anna,\n\nthanks for your request. Our all-in price is {PRICE} with {AIRLINE}, {TRANSIT_DAYS} days.\n\nBest regards"
        self.assertEqual(llm.safe_reply(good, "en"), (good, True))

    def test_multi_falls_back_to_multi_template(self):
        self.assertEqual(llm.safe_reply("{PRICE_TABLE}\nTotal {TOTAL}, 5% off!", "en", multi=True), ("", False))


class TestLongMail(unittest.TestCase):
    def test_end_is_kept(self):
        body = "blah " * 3000 + "Please quote 90 kg from HAM to BOG."
        clipped = llm._clip(body)
        self.assertLessEqual(len(clipped), 6100)
        self.assertIn("HAM to BOG", clipped)
        self.assertEqual(llm._clip("short"), "short")


if __name__ == "__main__":
    unittest.main()


class TestOwnSignature(unittest.TestCase):
    """Live 16:14 round 3: the model signed our quote with the customer's name (Tobias Auer)."""

    def test_customer_signature_is_replaced(self):
        from llm.extract import fill_reply, SIGNER
        best = {"total": "3696.00", "currency": "EUR", "airline": "Fjordline Air Cargo", "transit_days": 3}
        t = ("Hi Tobias,\n\nthe fastest option is {AIRLINE} at {PRICE} all-in, {TRANSIT_DAYS} days.\n\n"
             "Best regards,\nTobias Auer\nAuer Maschinenbau GmbH")
        body = fill_reply(t, best, {"origin": "DUS", "destination": "JFK", "language": "en"}, "t.auer@x.de", 734)
        self.assertNotIn("Tobias Auer", body)
        self.assertNotIn("Maschinenbau", body)
        self.assertTrue(body.rstrip().endswith(SIGNER + "\nAir Export"))
        self.assertEqual(body.count(SIGNER), 1)
