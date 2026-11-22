"""5U, 22 Nov 01:07 (round 91, rejected too_low): cargo insurance must be INSIDE the all-in price when the customer
gives the terms; and a trucker's lead time is read by code from free wording (round 90: 31 hours read as 24)."""
import os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import main, offer_file  # noqa: E402
from pricing import insurance  # noqa: E402
from sourcing import bids  # noqa: E402

MAIL = ("Hi,\n\nCould you quote the fastest air freight option from DUS to MEX (Mexico City, MX) and confirm the transit time? "
        "Please include the all-in price in EUR.\n\nWe\u2019ll deliver to DUS ourselves. The shipment is ready on 2026-11-29: 1 piece of "
        "printed marketing material, 176 kg gross, 1.26 cbm.\n\nPlease include cargo insurance in the all-in price, on the terms of our "
        "frame agreement: goods value 22000 EUR, insured at 110 % of that value, premium rate 0.40 %.\n\nSara\nLindqvist Medtech")


class Insurance(unittest.TestCase):
    def test_the_real_request(self):
        ins = insurance.wanted(MAIL)
        self.assertEqual(ins, {"value": "22000", "pct": "110", "rate": "0.40", "premium": "96.80"})
        best = insurance.add({"airline": "Xenon Cargo Airlines", "total": "927.95", "total_eur": "927.95", "currency": "EUR"}, ins)
        self.assertEqual((best["total"], best["total_eur"], best["flight_total"]), ("1024.75", "1024.75", "927.95"))
        self.assertEqual(insurance.sentence(ins, "en"),
                         "This includes the cargo insurance you asked for: 96.80 EUR (110% of the goods value of 22000 EUR at a premium of 0.40%).")

    def test_other_ways_to_write_it(self):
        self.assertEqual(insurance.wanted("Please quote 300 kg FRA to JFK. Please add cargo insurance to your all-in price: goods value 8,500.50 EUR, "
                                          "insured at 110%, premium rate 0.35%.")["premium"], "32.73")
        self.assertEqual(insurance.wanted("Bitte inklusive Transportversicherung anbieten: Warenwert 22.000 EUR, versichert zu 110 %, Prämiensatz 0,40 %.")["premium"], "96.80")

    def test_round_92_wording(self):
        """Live 01:13 (thr 26767), missed and rejected too_low: no "include", no "value" before the amount."""
        said = ("Hi there,\n\nCould you send me an all-in price in EUR for the fastest air freight option to GRU?\n\nIt\u2019s 6 pieces, "
                "671 kg and 6.19 cbm.\n\nWe also need cargo insurance inside your all-in price: the goods are worth 81000 EUR, cover is "
                "110 % of the value and the premium rate is 0.30 % (our frame agreement).\n\nCheers,\nKlaus")
        self.assertEqual(insurance.wanted(said), {"value": "81000", "pct": "110", "rate": "0.30", "premium": "267.30"})
        for more, premium in (("Our cargo must be insured: 45000 EUR worth of goods, coverage 110 %, premium 0.25 %.", "123.75"),
                              ("Insurance please, as always: 12,500 EUR, 110 %, 0.5 %.", "68.75"),
                              ("Die Transportversicherung soll im Preis sein: Ware im Wert von 30.000 EUR, Deckung 110 %, Prämie 0,35 %.", "115.50")):
            self.assertEqual((insurance.wanted("Please quote 300 kg FRA to JFK.\n\n" + more) or {}).get("premium"), premium, more)

    def test_no_terms_or_no_wish_adds_nothing(self):
        self.assertIsNone(insurance.wanted("Please quote 300 kg FRA to JFK. Is cargo insurance available?"))
        self.assertIsNone(insurance.wanted("Please include cargo insurance in the all-in price."))                       # no value, no rate
        self.assertIsNone(insurance.wanted("We do not need cargo insurance. Goods value 22000 EUR, 110 %, 0.40 %."))
        self.assertIsNone(insurance.wanted("please quote 300 kg, 1 cbm FRA to JFK, cheapest"))

    def test_the_offer_sheet_shows_it(self):
        ins = insurance.wanted(MAIL)
        best = insurance.add({"airline": "Xenon Cargo Airlines", "origin": "DUS", "destination": "MEX", "total": "927.95",
                              "total_eur": "927.95", "currency": "EUR", "transit_days": 2}, ins)
        lines = offer_file.lines(1, {"customer": "sara@x.mail", "subject": "DUS to MEX"}, best, {"weight_kg_total": 176.0}, "Hi Sara")
        self.assertIn("Cargo insurance: 96.80 EUR, included (110% of 22000 EUR goods value at 0.40%)", lines)
        self.assertIn("ALL-IN PRICE: 1024.75 EUR", lines)

    def test_the_sentence_goes_into_the_price_paragraph(self):
        body = "Hi Sara,\n\nXenon Cargo Airlines: 1024.75 EUR all-in, about 2 days.\n\nShall I book it?\n\nKind regards\nLena"
        out = main.llm._add_expert_note(body, insurance.sentence(insurance.wanted(MAIL), "en"), "1024.75")
        self.assertIn("about 2 days. This includes the cargo insurance you asked for: 96.80 EUR", out)


class LeadTime(unittest.TestCase):
    def test_free_wording_of_plain_text_offers(self):
        for said, h in (("Our all-in price for pickup and delivery to Hamburg Airport is 189.26 EUR, valid until 22 Nov 2026 00:16 UTC. "
                         "Pickup is available within 31 hours, with direct delivery to the airport.", 31),      # the model said 24
                        ("Our all-in price for transport to HAM Airport is 106.37 EUR. The pickup lead time is 31 hours.", 31),
                        ("Our all-in price is 220.65 EUR, valid until 22 Nov 2026 00:16 UTC. Pickup within 11 hours.", 11),
                        ("We can pick up your freight within 10 hours and take it straight to HAM airport. The all-in price is 241.96 EUR.", 10),
                        ("Our all-in rate is 211.43 EUR. We\u2019ll deliver to the airport within 17 hours of pickup.", 17),
                        ("Transit time from pickup to airport delivery is 10 hours. The rate is valid until 21 Nov 2026 23:58 UTC.", 10)):
            self.assertEqual(bids.lead_hours(said), h, said)

    def test_two_different_hour_figures_are_not_guessed(self):
        self.assertIsNone(bids.lead_hours("Pickup within 12 hours, delivery to the airport 6 hours later."))


if __name__ == "__main__":
    unittest.main()
