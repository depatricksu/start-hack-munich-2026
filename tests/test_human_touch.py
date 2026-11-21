"""Personal touch in quote mails (llm/human.py): passes the quality gate, and learns from the board's human count."""
import os, tempfile, unittest
from unittest import mock
from llm import extract as llm, human, quality

BEST = {"total": "1500.00", "currency": "EUR", "airline": "Meridian Freightways", "transit_days": 2}
TPL = "{HELLO}\n\n{ROUTE} for your {WEIGHT}: {AIRLINE} at {PRICE} all-in, about {TRANSIT_DAYS} days.\n\nJust reply and I'll book it."
TPL_DE = "{HELLO}\n\n{ROUTE} für Ihre {WEIGHT}: {AIRLINE} mit {PRICE} all-in, rund {TRANSIT_DAYS} Tage.\n\nEine kurze Antwort genügt und ich buche."


class TestTouch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.p = mock.patch.object(human, "STATE", os.path.join(self.tmp, "h.json"))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def body(self, style, fields, tpl=TPL, customer="tom.becker@x.mail"):
        with mock.patch.object(human, "HUMAN_STYLE", style):
            return llm.final_reply(tpl, BEST, fields, customer, 7)

    def test_every_style_every_city_passes_gate(self):
        for city in list(human.CITY_LINE) + ["Darmstadt", None]:
            for lang, tpl in (("en", TPL), ("de", TPL_DE)):
                for st in human.STYLES:
                    f = {"origin": "CGN", "destination": "ORD", "weight_kg": 300, "language": lang, "customer_city": city}
                    body, why = self.body(st, f, tpl)
                    self.assertEqual(why, [], body)
                    self.assertEqual(quality.check(body, lang, BEST, f, "", llm.SIGNER), [], body)
                    if st != "control" and f["human_style"] == "control":
                        self.fail("touch dropped for %s/%s/%s:\n%s" % (st, lang, city, body))

    def test_city_from_postcode_and_airport(self):
        self.assertEqual(human.customer_city({"pickup_postcode": "50667"}), "Cologne")
        self.assertEqual(human.customer_city({"origin": "HAM"}), "Hamburg")
        self.assertEqual(human.customer_city({"customer_city": "München"}), "Munich")

    def test_lines_land_where_they_should(self):
        body, _ = self.body("city", {"origin": "CGN", "destination": "ORD", "weight_kg": 300, "language": "de"}, TPL_DE)
        self.assertIn("bleibt der Dom stehen", body)
        self.assertTrue(body.rstrip().endswith(llm.SIGNER + "\nLuftfracht Export"))
        body, _ = self.body("local", {"origin": "MUC", "destination": "JFK", "weight_kg": 300, "language": "de"}, TPL_DE)
        self.assertTrue(body.startswith("Servus Tom,"), body)
        body, _ = self.body("destination", {"origin": "MUC", "destination": "ORD", "weight_kg": 300, "language": "en"})
        self.assertIn("the Windy City", body)

    def test_moment(self):
        sat_evening = 1795280400  # 2026-11-21 18:00 Berlin
        self.assertIn("Saturday evening", human.moment_line(sat_evening, "en"))

    def test_learning_credits_rise_and_times_out(self):
        with mock.patch.object(human.config, "DRY_RUN", False), mock.patch.object(human, "_ensure_watcher"):
            human.learn(0, now=1000)
            human.record(1, "city", now=1000)
            human.record(2, "moment", now=1000)
            s = human.learn(1, now=1100)
            self.assertAlmostEqual(s["arms"]["city"]["wins"], 0.5)
            human.record(3, "destination", now=1200)
            s = human.learn(1, now=1200 + human.LEARN_WINDOW_S + 1)
            self.assertEqual(s["arms"]["destination"]["losses"], 1)

    def test_dry_run_records_nothing(self):
        human.record(1, "city")
        self.assertEqual(human._load()["arms"]["city"]["sent"], 0)


if __name__ == "__main__":
    unittest.main()
