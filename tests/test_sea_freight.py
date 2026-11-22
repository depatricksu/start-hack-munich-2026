"""5U, 22 Nov 09:50 (request 53351): the first SEA freight request, a 40 ft container Hamburg to Jebel Ali. We only do
air freight, so the right answer is an honest "we cannot quote this" (5U: accepted), not silence and never an air price.
Run: python -m unittest tests.test_sea_freight -v"""
import json, os, tempfile, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main, scope  # noqa: E402

CUSTOMER = "sea-desk@sea-test.mail"                            # its own address: one DB for the whole suite
REAL = ("Hi there,\n\nHope your week’s going well! Could you send me an all-in price in EUR for a port-to-port sea freight shipment "
        "from Hamburg (DEHAM) to Jebel Ali (AEJEA)?\n\nThe furniture samples will be ready on 2026-11-27. It’s an FCL shipment in "
        "1 x 40ft container, with 6 pieces, a gross weight of 9617 kg and a total volume of 43.5 cbm.\n\nThanks for taking a look!\n\n"
        "Cheers,\nKlaus Weidner\nWeidner Spielwaren GmbH, Nuremberg")


def fields(**more):
    f = {"origin": "HAM", "destination": "AEJEA", "pickup_postcode": None, "weight_kg": 9617, "volume_cbm": 43.5, "pieces": [],
         "prefer": "none", "kind": "new_request", "language": "en", "missing": [], "customer_first_name": "Klaus",
         "reply": "Hi Klaus,\n\n{PRICE} with {AIRLINE}, {TRANSIT_DAYS} days.\n\nLena"}
    f.update(more)
    return f


def run(tid, f, body=REAL, subject="Sea freight quote Hamburg to Jebel Ali"):
    m = main.mailbox.normalize({"id": tid, "from": CUSTOMER, "subject": subject, "body": body})
    with mock.patch.object(main.llm, "extract", return_value=(f, {"fake": True})), mock.patch("sourcing.portal.options", return_value=[]):
        main.process(m)
    return db.session(tid)


def sent(tid, kinds=("mail_out_dry_run", "mail_out")):
    rows = db.con().execute("SELECT kind, data FROM events WHERE thread_id=?", (tid,)).fetchall()
    return [json.loads(r["data"]) for r in rows if r["kind"] in kinds]


class Words(unittest.TestCase):
    def test_the_real_request_is_sea_freight(self):
        self.assertTrue(scope.sea({"subject": "Quote", "body": REAL}))
        for body in ("Please quote ocean freight Hamburg to Shanghai, LCL, 3 cbm.", "Bitte um ein Angebot Seefracht Hamburg nach Santos, 1 x 20ft Container.",
                     "We need 2 x 40' HC from Bremerhaven to New York, port to port."):
            self.assertTrue(scope.sea({"subject": "", "body": body}), body)

    def test_an_air_request_is_never_sea_freight(self):
        for body in ("We used to ship this by sea. Please quote air freight HAM to DXB, 300 kg, 1.2 cbm.",
                     "Air freight quote FRA to JFK: 4 pallets, 600 kg. Not a full container, so no sea freight please.",
                     "Please quote the fastest option from MUC to SIN, 120 kg, 0.6 cbm.",
                     "RE: FW: VIENNA AIRPORT - LOS / 46 PLT. Please quote DUS to MEX, 1133 kg.",
                     "Goods are packed in 6 crates on 2 pallets, ready at our site in 51341. Cheapest to SGN please."):
            self.assertFalse(scope.sea({"subject": "", "body": body}), body)
        self.assertFalse(scope.sea({"subject": "Air freight quote", "body": "FCL is too slow for us this time: 9617 kg HAM to DXB."}))


class Decline(unittest.TestCase):
    def test_the_customer_gets_an_honest_answer_and_no_price(self):
        s = run(950117, fields())
        self.assertEqual(s["status"], "lost")
        self.assertTrue(s["note"].startswith("sea_freight_declined"), s["note"])
        mails = sent(950117)
        self.assertEqual(len(mails), 1)
        body = mails[0]["body"]
        for text in ("Hi Klaus,", "this is a sea freight shipment", "we arrange air freight out of German airports", "I cannot give you a price"):
            self.assertIn(text, body)
        self.assertNotRegex(body, r"\d[\d.,]*\s*EUR")                              # never a price
        self.assertNotIn("{", body)
        self.assertEqual(sent(950117, ("bid_mail_out_dry_run", "bid_mail_out")), [])   # nobody is asked

    def test_also_when_the_lane_would_pass_as_an_air_lane(self):
        """HAM to DXB exists by air. A 40 ft container by sea must never get an air price."""
        body = REAL.replace("Jebel Ali (AEJEA)", "Dubai (DXB area, Jebel Ali)")
        s = run(950218, fields(destination="DXB"), body=body)
        self.assertEqual(s["status"], "lost")
        self.assertIn("sea freight shipment", sent(950218)[0]["body"])

    def test_in_german(self):
        run(950319, fields(language="de"), body="Guten Tag,\n\nbitte um ein Angebot Seefracht Hamburg nach Jebel Ali, FCL, 1 x 40ft Container, 9617 kg.\n\nKlaus Weidner",
            subject="Seefracht Angebot")
        self.assertIn("Das ist eine Seefracht-Sendung", sent(950319)[0]["body"])


if __name__ == "__main__":
    unittest.main()
