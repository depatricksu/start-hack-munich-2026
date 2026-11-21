"""Weight-break flag. Run: python -m unittest tests.test_weight_break -v"""
import unittest
from decimal import Decimal

from pricing import price

YT_MUC_LAX = next(r for r in price._load() if r["airline"] == "Yellowtail Air Freight"
                  and r["origin"] == "MUC" and r["destination"] == "LAX")


class TestWeightBreak(unittest.TestCase):
    def test_on_by_default(self):
        self.assertTrue(price.WEIGHT_BREAK)

    def test_off(self):
        o = price.price_lane(YT_MUC_LAX, 230, weight_break=False)
        self.assertEqual(o["total"], "699.20")            # 230 x 1.73 + 230 x 1.31
        self.assertEqual(o["billed_kg"], "230")

    def test_on_bills_next_break_when_cheaper(self):
        o = price.price_lane(YT_MUC_LAX, 230, weight_break=True)
        self.assertEqual(o["total"], "677.50")            # 250 x 1.40 + 250 x 1.31
        self.assertEqual(o["billed_kg"], "250")

    def test_on_never_more_expensive(self):
        for kg in (10, 44, 45, 99, 120, 240, 260, 480, 999, 1500, 2500):
            off = Decimal(price.price_lane(YT_MUC_LAX, kg, weight_break=False)["total"])
            on = Decimal(price.price_lane(YT_MUC_LAX, kg, weight_break=True)["total"])
            self.assertLessEqual(on, off, kg)


if __name__ == "__main__":
    unittest.main()
