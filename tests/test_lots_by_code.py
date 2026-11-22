"""5U, 22 Nov 10:27 (request 55122): three lots listed line by line. The model gave all three as pieces AND a stray
1,014 kg total, the clerk added both (2,912 instead of 1,898 kg) and the quote was rejected as too high. The lot lines
are exact, so core/lots.py adds them up by code. Run: python -m unittest tests.test_lots_by_code -v"""
import json, os, tempfile, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, lots, main  # noqa: E402

CUSTOMER = "lots-desk@lots-test.mail"                          # its own address: one DB for the whole suite
REAL = ("Hi,\n\nCould you quote one all-in price in EUR for the fastest air freight option to YYZ (Toronto, CA)? We deliver to HAM "
        "ourselves on 2026-12-05.\n\n"
        "Lot 1: 2 cartons, each 474 kg gross (445 kg net), each 120 x 80 x 119 cm\n"
        "Lot 2: 7 drums, each 32 kg gross (28 kg net), each 110 x 110 x 103 cm\n"
        "Lot 3: 2 pallets, together 726 kg gross (646 kg net), together 4.33 cbm\n\n"
        "Please ship all lots together as a single consignment under one air waybill.\n\nMira Petersen\nNordlicht Audio\n\n\n"
        "-----Original Message-----\nSent: 2026-10-08\nSubject: VIENNA AIRPORT - ATL / 208 CTN 5,200 KGS\n\nDear team,\n\n"
        "pls quote air freight ex VIENNA AIRPORT to ATL:\n208 CTN / 5,200 KGS / 4 CBM, machine parts\nLot 1: 208 cartons, together 5200 kg gross, together 4 cbm\n")


class Reading(unittest.TestCase):
    def test_the_real_request(self):
        self.assertEqual(lots.totals(REAL), (1898.0, 15.3389))

    def test_the_three_earlier_ones(self):
        """Rounds 158, 62 and 9: 2,587 / 1,587 / 730 kg were priced; the text says 1,797 / 1,122 / 1,952."""
        r158 = ("Lot 1: 8 crates, each 105 kg gross (97 kg net), each 60 x 40 x 87 cm\nLot 2: 1 drum, together 675 kg gross (594 kg net), together 4.46 cbm\n"
                "Lot 3: 6 cases, each 47 kg gross (40 kg net), each 110 x 110 x 126 cm")
        r62 = ("Lot 1: 1 carton, together 465 kg gross (404 kg net), together 3.87 cbm\nLot 2: 3 pallets, each 160 kg gross (142 kg net), each 100 x 60 x 46 cm\n"
               "Lot 3: 3 drums, each 59 kg gross (55 kg net), each 110 x 110 x 128 cm")
        self.assertEqual(lots.totals(r158), (1797.0, 15.278))
        self.assertEqual(lots.totals(r62), (1122.0, 9.3444))

    def test_gross_not_net_and_number_forms(self):
        self.assertEqual(lots.one("2 cartons, each 474 kg gross (445 kg net), each 120 x 80 x 119 cm"), (948.0, 2.2848))
        self.assertEqual(lots.one("1 pallet, 1,200 kg gross, 2,5 cbm"), (1200.0, 2.5))            # thousands and a decimal comma
        self.assertEqual(lots.one("3 Kisten, je 40 kg brutto (35 kg netto), je 50 x 40 x 30 cm"), (120.0, 0.18))

    def test_anything_unclear_leaves_the_models_reading(self):
        for text in ("Lot 1: 2 cartons, each 474 kg gross, each 120 x 80 x 119 cm",                       # one lot only
                     "Lot 1: 2 cartons, 474 kg gross, each 120 x 80 x 119 cm\nLot 2: 1 drum, 30 kg gross, 0.2 cbm",   # each or together?
                     "Lot 1: 2 cartons, each 200 lb gross, each 40 x 30 x 30 in\nLot 2: 1 drum, 30 kg gross, 0.2 cbm",  # pounds, inches
                     "Lot 1: 2 cartons, each 474 kg gross\nLot 2: 1 drum, 30 kg gross, 0.2 cbm",          # a lot without a size
                     "Lot 1: 2 cartons, each 120 x 80 x 119 cm\nLot 2: 1 drum, 30 kg gross, 0.2 cbm",     # a lot without a weight
                     "Please quote 300 kg, 1.2 cbm from HAM to JFK."):
            self.assertIsNone(lots.totals(text), text)

    def test_a_forwarded_old_message_is_not_read(self):
        old_only = "Please quote as below.\n\n-----Original Message-----\nLot 1: 2 cartons, each 474 kg gross, each 120 x 80 x 119 cm\nLot 2: 1 drum, together 30 kg gross, together 0.2 cbm"
        self.assertIsNone(lots.totals(old_only))


class Priced(unittest.TestCase):
    def test_the_clerk_prices_what_the_text_adds_up_to(self):
        """What the model returned live: all three lots as pieces and a stray weight_kg of 1014."""
        f = {"origin": "HAM", "destination": "YYZ", "pickup_postcode": None, "weight_kg": 1014, "volume_cbm": 4.33,
             "pieces": [{"count": 2, "l_cm": 120, "w_cm": 80, "h_cm": 119, "kg_each": 474}, {"count": 7, "l_cm": 110, "w_cm": 110, "h_cm": 103, "kg_each": 32},
                        {"count": 2, "l_cm": None, "w_cm": None, "h_cm": None, "kg_each": 363}],
             "prefer": "fastest", "kind": "new_request", "language": "en", "missing": [], "shipments": [],
             "reply": "Hi Mira,\n\n{PRICE} with {AIRLINE}, {TRANSIT_DAYS} days.\n\nLena"}
        self.assertEqual(main.shipment(f)[0], 2912.0)                              # the old sum, still what shipment() says
        m = main.mailbox.normalize({"id": 960117, "from": CUSTOMER, "subject": "RE: FW: VIENNA AIRPORT - ATL / 208 CTN 5,200 KGS", "body": REAL})
        seen = {}

        def portal(o, d, w, v, *a, **k):
            seen["asked"] = (o, d, w, v)
            return []
        with mock.patch.object(main.llm, "extract", return_value=(f, {"fake": True})), mock.patch("sourcing.portal.options", side_effect=portal):
            main.process(m)
        got = json.loads(db.session(960117)["fields"])
        self.assertEqual((got["weight_kg_total"], got["volume_cbm_total"]), (1898.0, 15.3389))
        self.assertIn("2912 -> 1898 kg", got["lots_fix"])
        e = json.loads(db.con().execute("SELECT data FROM events WHERE thread_id=960117 AND kind='lots_fix'").fetchone()["data"])
        self.assertEqual(e["after"], [1898.0, 15.3389])
        if seen:                                                                   # the portal is asked with the corrected totals
            self.assertEqual(seen["asked"][2:], (1898.0, 15.3389))


if __name__ == "__main__":
    unittest.main()
