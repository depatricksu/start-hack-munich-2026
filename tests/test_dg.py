"""dg/: dangerous goods in the quote (owner Riky). Pure functions, no network."""
import os
import unittest

import dg

BODY = "Hi Anna,\n\nMUC to JFK, 120 kg: 1234.50 EUR all-in with Lumen, 3 days.\n\nBest regards,\nLena Hofmann\nAir Export"
BEST = {"airline": "Lumen", "total": "1234.50", "total_eur": "1234.50", "currency": "EUR", "billed_kg": "120"}


class ReadDeclaration(unittest.TestCase):
    def test_packing_list_from_round_10(self):
        info = dg.read_declaration("Dangerous goods: UN1133, Class 3, Adhesives")
        self.assertEqual(info["un"], "UN1133")
        self.assertEqual(info["class"], "3")
        self.assertEqual(info["name"], "Adhesives")

    def test_sli_from_round_11(self):
        info = dg.read_declaration("Dangerous goods: UN1950, Class 2.1, Aerosols, flammable")
        self.assertEqual((info["un"], info["class"]), ("UN1950", "2.1"))
        self.assertTrue(info["name"].startswith("Aerosols"))

    def test_mail_that_says_non_dangerous_is_not_dg(self):
        self.assertIsNone(dg.read_declaration("Industrial adhesives, general cargo, non-dangerous."))
        self.assertIsNone(dg.read_declaration("Dangerous goods: no"))
        self.assertIsNone(dg.read_declaration(""))

    def test_un_number_wins_over_a_non_dangerous_claim(self):
        self.assertEqual(dg.read_declaration("non-dangerous ... UN 3480 lithium")["un"], "UN3480")


class Apply(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ("DG_MODE", "DG_SURCHARGE_EUR_PER_KG", "DG_SURCHARGE_MIN_EUR")}

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_no_dg_changes_nothing(self):
        self.assertEqual(dg.apply(BEST, {}, BODY), (BEST, BODY, None))

    def test_docs_mode_adds_paragraph_before_signature(self):
        os.environ.pop("DG_MODE", None)
        fields = {"dg": {"un": "UN1133", "class": "3", "name": "Adhesives"}, "language": "en"}
        best, body, human = dg.apply(BEST, fields, BODY)
        self.assertIsNone(human)
        self.assertEqual(best, BEST)
        self.assertIn("UN1133, class 3 (Adhesives)", body)
        self.assertIn("Shipper's Declaration for Dangerous Goods", body)
        self.assertLess(body.index("Shipper's Declaration"), body.index("Best regards"))
        self.assertIn("1234.50 EUR", body)

    def test_german_paragraph(self):
        _, body, _ = dg.apply(BEST, {"dg": True, "language": "de"}, "Guten Tag,\n\nPreis 1234.50 EUR.\n\nMit freundlichen Grüßen\nLena")
        self.assertIn("Gefahrgut", body)

    def test_human_mode(self):
        os.environ["DG_MODE"] = "human"
        _, _, human = dg.apply(BEST, {"dg": {"un": "UN1950"}}, BODY)
        self.assertIn("UN1950", human)

    def test_surcharge_mode_adds_to_total_and_text(self):
        os.environ["DG_MODE"] = "surcharge"
        os.environ["DG_SURCHARGE_EUR_PER_KG"] = "0.50"
        os.environ["DG_SURCHARGE_MIN_EUR"] = "75"
        best, body, _ = dg.apply(BEST, {"dg": {"un": "UN1133"}}, BODY)
        self.assertEqual(best["total_eur"], "1309.50")          # 120 kg x 0.50 = 60 < 75 minimum
        self.assertIn("1309.50 EUR", body)
        self.assertNotIn("1234.50", body)


if __name__ == "__main__":
    unittest.main()
