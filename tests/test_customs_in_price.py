"""Built ahead (22 Nov): a customs clearance fee the customer wants INSIDE the all-in price, like the cargo insurance
of rounds 91/92. Strict: one sentence, one flat EUR fee, asked for inside the price. Everything else adds nothing."""
import os, tempfile, unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")
os.environ.setdefault("FIVEU_API_KEY", "")

from core import main, offer_file  # noqa: E402
from pricing import customs, insurance  # noqa: E402

RFQ = "Hi,\n\nPlease quote 300 kg, 1.2 cbm FRA to JFK, all-in price in EUR.\n\n%s\n\nSara\nLindqvist Medtech"
BEST = {"airline": "Xenon Cargo Airlines", "origin": "FRA", "destination": "JFK", "total": "927.95", "total_eur": "927.95",
        "currency": "EUR", "transit_days": 2}


class Customs(unittest.TestCase):
    def test_fee_goes_into_the_price(self):
        cus = customs.wanted(RFQ % "Please include export customs clearance in the all-in price: our broker charges 45 EUR per declaration.")
        self.assertEqual(cus, {"fee": "45.00"})
        best = customs.add(BEST, cus)
        self.assertEqual((best["total"], best["total_eur"], best["flight_total"]), ("972.95", "972.95", "927.95"))
        self.assertEqual(customs.sentence(cus, "en"), "This includes the customs clearance you asked for: 45.00 EUR.")

    def test_other_ways_to_write_it(self):
        for said, fee in (("We also need customs clearance inside your all-in price, a flat fee of 60 EUR as per our frame agreement.", "60.00"),
                          ("Bitte die Zollabfertigung im Preis einschließen: pauschal 55,50 EUR pro Sendung.", "55.50"),
                          ("Merci d'inclure le dédouanement export dans le prix : 40 EUR par déclaration.", "40.00"),
                          ("Add the export clearance to the all-in price please.\nThe clearance fee is EUR-based: 35 EUR.", "35.00")):
            self.assertEqual((customs.wanted(RFQ % said) or {}).get("fee"), fee, said)

    def test_anything_unclear_adds_nothing(self):
        for said in ("Is customs clearance available?",
                     "Please include customs clearance in the all-in price.",                                   # no fee given
                     "We handle customs clearance ourselves, our broker charges 45 EUR.",                       # not ours
                     "No customs clearance needed, it would be 45 EUR anyway.",
                     "Goods value for customs is 500 EUR, please include that in the papers.",                  # a value, not a fee
                     "Please include customs clearance: 15 EUR per tariff line, 4 lines.",                      # not one flat fee
                     "Please include customs clearance at 0.5 % of the goods value of 900 EUR.",
                     "Please include customs clearance, 45 EUR export and 60 EUR import.",                      # two amounts
                     "Please include customs clearance for 22000 EUR."):                                        # too big to be a fee
            self.assertIsNone(customs.wanted(RFQ % said), said)
        self.assertIsNone(customs.wanted("please quote 300 kg, 1 cbm FRA to JFK, cheapest"))

    def test_an_eur_fee_is_never_added_to_a_usd_price(self):
        usd = dict(BEST, currency="USD")
        self.assertIs(customs.add(usd, {"fee": "45.00"}), usd)

    def test_together_with_insurance(self):
        mail = RFQ % ("Please include cargo insurance in the all-in price: goods value 22000 EUR, insured at 110 % of that value, "
                      "premium rate 0.40 %.\n\nPlease also include customs clearance in the all-in price, 45 EUR per declaration.")
        best = customs.add(insurance.add(BEST, insurance.wanted(mail)), customs.wanted(mail))
        self.assertEqual((best["total"], best["flight_total"]), ("1069.75", "927.95"))                         # 927.95 + 96.80 + 45
        lines = offer_file.lines(1, {"customer": "sara@x.mail", "subject": "FRA to JFK"}, best, {"weight_kg_total": 300.0}, "Hi Sara")
        self.assertIn("Customs clearance: 45.00 EUR, included", lines)
        self.assertIn("ALL-IN PRICE: 1069.75 EUR", lines)

    def test_polish_does_not_say_not_included(self):
        mail = RFQ % "Please include export customs clearance in the all-in price: our broker charges 45 EUR per declaration."
        body = "Hi Sara,\n\nXenon Cargo Airlines: 972.95 EUR all-in, about 2 days.\n\nShall I book it?\n\nKind regards\nLena"
        body = main.llm._add_expert_note(body, customs.sentence(customs.wanted(mail), "en"), "972.95")
        self.assertIn("about 2 days. This includes the customs clearance you asked for: 45.00 EUR.", body)
        out, _ = main.humanize.polish(body, {"language": "en"}, customs.add(BEST, {"fee": "45.00"}), mail)
        self.assertNotIn("isn't included", out)

    def test_no_real_mail_so_far_triggers_it(self):
        import sqlite3
        db = os.path.join(os.path.dirname(__file__), "..", "examples", "real", "snapshot.db")
        if not os.path.exists(db):
            self.skipTest("no snapshot")
        hits = [i for i, b in sqlite3.connect(db).execute("SELECT id, body FROM mails") if customs.wanted(b or "")]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
