"""DG inferred from the commodity name (aerosols/spray cans etc.) with no UN number declared.
5U trick 21 Nov: lindqvist-medtech 'maintenance spray cans' quoted as general cargo -> declined. Run: python -m unittest tests.test_commodity_dg"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from dg import quote  # noqa: E402


class TestCommodityDG(unittest.TestCase):
    def test_spray_cans_detected(self):
        info = quote.read_declaration("Commodity: maintenance spray cans, 4 pieces. Gross weight 855 kg.")
        self.assertIsNotNone(info)
        self.assertEqual(info["un"], "UN1950")
        self.assertTrue(info.get("inferred"))

    def test_lithium_detected(self):
        info = quote.read_declaration("10 cartons of lithium-ion batteries for medical devices")
        self.assertEqual(info["class"], "9")

    def test_plain_cargo_not_flagged(self):
        for t in ["Commodity: machine parts, 4 pieces", "textile samples", "replacement gearboxes", "measuring instruments"]:
            self.assertIsNone(quote.read_declaration(t), t)

    def test_explicit_non_dangerous_blocks_inference(self):
        """Soft words still yield to a 'non-dangerous' claim..."""
        self.assertIsNone(quote.read_declaration("perfume samples, these are non-dangerous goods"))

    def test_inherent_dg_ignores_the_non_dangerous_claim(self):
        """...but aerosols / lithium do not: request 2533 said 'general cargo, non-dangerous' for spray cans and the
        customer declined because we did not ask for the DG documents (Riky)."""
        info = quote.read_declaration("Commodity: maintenance spray cans, 4 pieces. The goods are general cargo, non-dangerous")
        self.assertEqual(info["un"], "UN1950")
        self.assertEqual(quote.read_declaration("lithium-ion batteries, non-dangerous")["class"], "9")

    def test_apply_adds_dg_paragraph(self):
        os.environ["DG_MODE"] = "docs"
        best = {"airline": "X", "total_eur": "416.16", "total": "416.16", "currency": "EUR", "billed_kg": 855}
        fields = {"dg": quote.read_declaration("maintenance spray cans"), "language": "en"}
        _, body, human = quote.apply(best, fields, "Hi,\n\nHere is your quote: 416.16 EUR.\n\nBest regards")
        self.assertIsNone(human)                       # docs mode: still quote, just ask for the papers
        self.assertIn("dangerous goods documents", body)
        self.assertNotIn("shipping documents declare", body)   # accurate opener for inferred DG


class TestNoFalseDG(unittest.TestCase):
    """Kai's false positives on b4f7c3a: each would ask for DG papers on general cargo and cost the round."""
    def test_kai_cases_are_not_dg(self):
        for t in ("Commodity: no lithium batteries inside, just cables.",
                  "fragrance-free soap, 200 cartons",
                  "office chairs, 12 pieces\n\nKind regards\nTom Weber\nFireworks Media GmbH",
                  "perfume bottles (empty glass), 40 cartons",
                  "spare parts without lithium batteries"):
            self.assertIsNone(quote.read_declaration(t), t)

    def test_still_ok(self):
        for t in ("lithium-free grease", "non-flammable paint", "not dangerous goods"):
            self.assertIsNone(quote.read_declaration(t), t)
        self.assertEqual(quote.read_declaration("12 cartons of power banks")["class"], "9")


if __name__ == "__main__":
    unittest.main()


class TestReviewFindings(unittest.TestCase):
    """Fresh-eyes review 21 Nov 19:05: each of these would cost a round."""
    def test_not_dg(self):
        for t in ("Dangerous goods: | No", "Dangerous goods: Not restricted", "Dangerous goods: nil", "Hazmat: No",
                  "Gefahrgut: entfällt", "This is not DGR cargo", "contains no aerosols, paints, lithium batteries or dry ice",
                  "Keine Powerbanks", "ohne Li-Ion-Akkus", "lighter fixtures", "Demand flares up", "explosive growth",
                  "Anti-oxidizing coating", "Plastic caps for aerosol cans", "cases for power banks",
                  "Chargers for lithium batteries (no batteries)", "Empty perfume bottles"):
            self.assertIsNone(quote.read_declaration(t), t)

    def test_german_dg(self):
        for t, un in (("Spraydosen, 4 Kartons", "UN1950"), ("Lithium-Ionen-Akkus", "UN3481"), ("Trockeneis 20 kg", "UN1845")):
            self.assertEqual(quote.read_declaration(t)["un"], un, t)

    def test_table_cell_with_a_real_declaration(self):
        self.assertEqual(quote.read_declaration("Dangerous goods: | UN1950 aerosols")["un"], "UN1950")
