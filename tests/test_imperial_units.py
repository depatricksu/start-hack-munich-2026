"""5U, 22 Nov 00:12 (round 82): "a gross weight of 1413.17 lb and a total volume of 95.00 cubic feet".

The model converted by itself: 641.52 kg and 2.68 cbm. The customer's numbers are 641.0 kg and 2.69 cbm (5U wrote the
pounds from 641 kg). Accepted that time, but every accuracy point depends on the model's arithmetic.
"""
import os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from llm import extract  # noqa: E402

MAIL = {"subject": "Air freight quote: HAM to SGN",
        "body": "The shipment consists of 3 pieces of printed marketing material, with a gross weight of 1413.17 lb and a "
                "total volume of 95.00 cubic feet."}


class Imperial(unittest.TestCase):
    def fix(self, weight, volume, mail=MAIL):
        f = {"weight_kg": weight, "volume_cbm": volume, "pieces": []}
        return extract.fix_units(f, mail), f

    def test_the_models_own_conversion_is_made_exact(self):
        fixed, f = self.fix(641.52, 2.68)
        self.assertEqual((f["weight_kg"], f["volume_cbm"]), (641.0, 2.69))
        self.assertEqual(len(fixed), 2)

    def test_numbers_copied_unchanged_are_converted(self):
        _, f = self.fix(1413.17, 95.0)
        self.assertEqual((f["weight_kg"], f["volume_cbm"]), (641.0, 2.69))

    def test_an_exact_conversion_is_left_alone(self):
        fixed, f = self.fix(641.0, 2.69)
        self.assertEqual(fixed, [])

    def test_values_that_are_no_conversion_stay(self):
        fixed, f = self.fix(900, 4.0)
        self.assertEqual((fixed, f["weight_kg"], f["volume_cbm"]), ([], 900, 4.0))

    def test_other_spellings_of_cubic_feet(self):
        for said in ("volume 95 cu ft", "volume: 95 cft", "95 ft3 in total", "95.00 cubic foot"):
            _, f = self.fix(641.0, 95, {"subject": "", "body": "gross weight 1413.17 lbs, " + said})
            self.assertEqual(f["volume_cbm"], 2.69, said)

    def test_a_metric_mail_is_untouched(self):
        fixed, f = self.fix(641.5, 2.68, {"subject": "", "body": "gross weight 641.5 kg, volume 2.68 cbm"})
        self.assertEqual((fixed, f["weight_kg"], f["volume_cbm"]), ([], 641.5, 2.68))


if __name__ == "__main__":
    unittest.main()
