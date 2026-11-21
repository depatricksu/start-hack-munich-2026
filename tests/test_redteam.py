"""Fixes from the 5U-style red-team run (21 Nov ~19:00). Run: python -m unittest tests.test_redteam"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from llm import extract as llm  # noqa: E402
from core import main  # noqa: E402
from humanize.polish import signed_name  # noqa: E402

US = {"subject": "Air quote FRA to ORD",
      "body": "Hi,\n\ncheapest FRA to ORD please. 4 crates, 48 x 40 x 50 in each, total 2,200 lbs.\n\nThanks,\nMegan Cole"}


class TestUnits(unittest.TestCase):
    def test_pounds_and_inches_copied_by_the_model_are_converted(self):
        f = {"weight_kg": 2200, "pieces": [{"count": 4, "l_cm": 48, "w_cm": 40, "h_cm": 50, "kg_each": None}]}
        llm.fix_units(f, US)
        self.assertAlmostEqual(f["weight_kg"], 997.9, places=1)
        self.assertEqual((f["pieces"][0]["l_cm"], f["pieces"][0]["w_cm"], f["pieces"][0]["h_cm"]), (121.9, 101.6, 127.0))

    def test_already_converted_values_stay(self):
        f = {"weight_kg": 998, "pieces": [{"count": 4, "l_cm": 122, "w_cm": 102, "h_cm": 127, "kg_each": None}]}
        self.assertEqual(llm.fix_units(f, US), [])
        self.assertEqual(f["weight_kg"], 998)

    def test_metric_mail_untouched(self):
        f = {"weight_kg": 640, "pieces": [{"count": 2, "l_cm": 120, "w_cm": 80, "h_cm": 110, "kg_each": 320}]}
        mail = {"subject": "x", "body": "2 pallets 120 x 80 x 110 cm, 640 kg, ready in 2 days"}
        self.assertEqual(llm.fix_units(f, mail), [])

    def test_per_piece_pounds(self):
        f = {"weight_kg": None, "pieces": [{"count": 3, "l_cm": None, "w_cm": None, "h_cm": None, "kg_each": 550}]}
        llm.fix_units(f, {"subject": "", "body": "3 drums, each 550 lb"})
        self.assertAlmostEqual(f["pieces"][0]["kg_each"], 249.5, places=1)


class TestDeadline(unittest.TestCase):
    def test_must_arrive_by(self):
        t = "cheapest MUC to SIN, but it MUST arrive by 2026-11-27 at the latest. Ready at MUC on 2026-11-24."
        self.assertEqual(main.max_transit_days(t), 3)

    def test_german_deadline(self):
        self.assertEqual(main.max_transit_days("Ware ist am 2026-11-24 abholbereit und muss spätestens am 2026-11-28 in Dubai sein."), 4)

    def test_drop_off_date_is_not_a_deadline(self):
        self.assertIsNone(main.max_transit_days("ready on 2026-11-25, we deliver to FRA on 2026-11-26"))
        self.assertIsNone(main.max_transit_days("ready on 2026-11-25, pickup on 2026-11-26 at the latest."))
        self.assertIsNone(main.max_transit_days("ready for pickup on 2026-11-25. Please confirm the earliest available arrival."))


class TestSignedName(unittest.TestCase):
    def test_gruss_is_a_closing_not_a_name(self):
        self.assertEqual(signed_name("Hallo,\n\nMUC nach ORD bitte.\n\nGruß\nOliver Krause"), "Oliver")
        self.assertEqual(signed_name("Hallo,\n\nbitte.\n\nGruss\nOliver"), "Oliver")

    def test_unknown_language_closing_is_not_a_name(self):
        mail = "Dzień dobry,\n\nproszę o ofertę.\n\nPozdrawiam\nKatarzyna Nowak\nBaltic Meble, Gdańsk"
        self.assertEqual(signed_name(mail), "Katarzyna")
        self.assertEqual(signed_name("Hej,\n\noffert tack.\n\nMvh\nSven Berg"), "Sven")


class TestForeignLanguage(unittest.TestCase):
    def test_language_without_own_texts_gets_one_clean_english_mail(self):
        best = {"airline": "Fjordline Air Cargo", "total": "1767.33", "currency": "EUR", "transit_days": 4}
        fields = {"origin": "HAM", "destination": "JFK", "weight_kg_total": 690, "language": "pl"}
        tpl = ("Dzień dobry,\n\ndziękujemy za zapytanie. Dla przesyłki {ROUTE} oferujemy {PRICE} all-in z {AIRLINE}, "
               "czas tranzytu ok. {TRANSIT_DAYS} dni.\n\nPozdrawiamy\nAir Export Team")
        body, _ = llm.final_reply(tpl, best, fields, "k.nowak@baltic-meble.mail", 4242)
        self.assertNotIn("Dzień", body)
        self.assertNotIn("Pozdrawiamy", body)
        self.assertIn("1767.33", body)
        self.assertEqual(body.count(llm.SIGNER), 1)              # one signature, not two


if __name__ == "__main__":
    unittest.main()
