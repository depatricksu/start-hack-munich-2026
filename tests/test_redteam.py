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


class TestRound2(unittest.TestCase):
    """Red-team round 2 (21 Nov ~19:20): more raw units, EXW, customer replies."""
    def test_tonnes(self):
        f = {"weight_kg": 2.4}
        llm.fix_units(f, {"subject": "", "body": "6 crates, total 2.4 t, 9.8 cbm"})
        self.assertEqual(f["weight_kg"], 2400)

    def test_millimetres(self):
        f = {"weight_kg": 780, "pieces": [{"count": 3, "l_cm": 1200, "w_cm": 800, "h_cm": 1100, "kg_each": None}]}
        llm.fix_units(f, {"subject": "", "body": "3 Paletten, je 1200 x 800 x 1100 mm, gesamt 780 kg"})
        self.assertEqual((f["pieces"][0]["l_cm"], f["pieces"][0]["w_cm"], f["pieces"][0]["h_cm"]), (120, 80, 110))

    def test_net_becomes_gross(self):
        f = {"weight_kg": 640}
        llm.fix_units(f, {"subject": "", "body": "8 drums, net weight 640 kg, gross weight 712 kg, 2.1 cbm"})
        self.assertEqual(f["weight_kg"], 712)
        f = {"weight_kg": 712}
        self.assertEqual(llm.fix_units(f, {"subject": "", "body": "net weight 640 kg, gross weight 712 kg"}), [])

    def test_exw_means_door_pickup(self):
        mail = {"subject": "Quotation EXW Stuttgart - ORD", "body": "Incoterm EXW Brandt GmbH, Industriestr. 12, 70565 Stuttgart, "
                "to ORD. Tel +49 711 12345."}
        f = {"origin": "STR"}
        self.assertEqual(llm.fix_incoterm(f, mail), "70565")
        self.assertEqual(f["pickup_postcode"], "70565")
        self.assertIsNone(llm.fix_incoterm({"origin": "FRA"}, {"subject": "", "body": "FCA Frankfurt airport, 60549"}))

    def test_customer_replies(self):
        from booking.handlers import classify
        for text in ("Perfect, thank you. Please proceed with the booking.", "OK for us. Please arrange.",
                     "Yes, that works for us.", "Alles klar, machen wir so.", "Va bene, procedete pure."):
            self.assertEqual(classify(text), "accept", text)
        self.assertEqual(classify("Can you do any better on the price?"), "better_price")
        self.assertEqual(classify("Thanks, but we won't proceed."), "decline")
        self.assertEqual(classify("Please book, but only after we confirm the pickup date on Monday."), "unclear")
        self.assertEqual(classify("Yes, but please send the invoice in USD."), "unclear")


class TestPriceOutliers(unittest.TestCase):
    """A misread bid must never win the quote (core/main.py drop_price_outliers)."""
    def opts(self, *totals):
        return [{"airline": "A%d" % i, "total_eur": str(t), "transit_days": 3, "source": "bid"} for i, t in enumerate(totals)]

    def test_per_kg_rate_read_as_total_is_dropped(self):
        kept = main.drop_price_outliers(1, self.opts(2.85, 2400, 2550, 2610))
        self.assertEqual(sorted(x["total_eur"] for x in kept), ["2400", "2550", "2610"])

    def test_thousand_times_too_high_is_dropped(self):
        kept = main.drop_price_outliers(1, self.opts(2400, 2550, 2610000))
        self.assertEqual(len(kept), 2)

    def test_real_spread_is_kept(self):           # 3630 on 21 Nov: cheapest 0.51x the median, accepted
        o = self.opts(1000, 1800, 1960, 2000, 2400, 3600)
        self.assertEqual(main.drop_price_outliers(1, o), o)

    def test_too_few_options_untouched(self):
        o = self.opts(3, 2400)
        self.assertEqual(main.drop_price_outliers(1, o), o)


if __name__ == "__main__":
    unittest.main()
