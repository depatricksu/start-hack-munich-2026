"""Run: python -m unittest tests.test_learn_analyze -v"""
import unittest

from learn import analyze as A
from learn import scorer as S


def sess(quote, flight, opts):
    return {"chosen": {"total_eur": str(quote), "total": str(quote)}, "options": opts, "fields": {}}


class TestClassify(unittest.TestCase):
    def test_perfect_round(self):
        c = A.classify_change(60.0, [(3, 13)], tracking_answered=False)
        self.assertEqual((c["kind"], c["accuracy"], c["tracking"]), ("round", 45.0, 0.0))

    def test_round_with_tracking_bonus(self):
        c = A.classify_change(70.0, [(5, 14)], tracking_answered=True)
        self.assertEqual((c["accuracy"], c["tracking"]), (45.0, 10.0))

    def test_round_four_the_real_numbers(self):
        c = A.classify_change(40.62, [(4, 66)], tracking_answered=False)
        self.assertEqual((c["kind"], c["time"], c["accuracy"]), ("round", 15.0, 25.62))
        self.assertEqual(c["alt"]["accuracy"], 15.62)                 # if a tracking bonus had been in there

    def test_a_lone_ten_is_the_tracking_bonus(self):
        self.assertEqual(A.classify_change(10.0, [], True)["kind"], "tracking_bonus")

    def test_hourly_cost_points_are_not_mistaken_for_a_round(self):
        self.assertEqual(A.classify_change(120.5, [], False)["kind"], "cost_points_or_mixed")

    def test_two_rounds_at_once_are_flagged(self):
        self.assertEqual(A.classify_change(100, [(1, 50), (2, 50)], False)["kind"], "mixed")


class TestExplain(unittest.TestCase):
    def test_trucker_rule_story_of_round_one(self):
        quote, best = 3314.21, 3228.87
        acc = S.accuracy_points(quote, best)
        s = sess(quote, 3094.18, [{"total_eur": "3314.21", "flight_total": "3094.18", "flight_currency": "EUR", "transit_days": 1},
                                  {"total_eur": "3228.87", "flight_total": "3094.18", "flight_currency": "EUR", "transit_days": 1}])
        e = A.explain(quote, acc, s)
        self.assertEqual(e["rule_errors"]["cheapest_any"], 0.0)       # the cheaper-trucker combination explains it
        self.assertGreater(e["rule_errors"]["what_we_quoted"], 10)    # "our quote was the best" does not
        self.assertIn("explained by: cheapest_any", A.verdict(e["rule_errors"]))

    def test_round_four_is_not_explained_by_anything_we_model(self):
        quote = 1599.41
        acc = 25.62
        s = sess(quote, 1483.43, [{"total_eur": "1599.41", "flight_total": "1483.43", "flight_currency": "EUR", "transit_days": 3},
                                  {"total_eur": "1844.31", "flight_total": "1728.33", "flight_currency": "EUR", "transit_days": 2}])
        e = A.explain(quote, acc, s)
        self.assertIn("NOT explained", A.verdict(e["rule_errors"], accuracy=acc))
        self.assertAlmostEqual(e["implied_best"][0], 1564.9, 0)

    def test_full_points_means_quote_at_or_below_best(self):
        s = sess(5357.76, 5238.75, [{"total_eur": "5357.76", "flight_total": "5238.75", "flight_currency": "EUR", "transit_days": 2}])
        e = A.explain(5357.76, 45.0, s)
        self.assertIn("full points", A.verdict(e["rule_errors"], accuracy=45.0))

    def test_odds_move_towards_the_rule_that_explains(self):
        odds = {r: 1 / 4 for r in A.RULES}
        for _ in range(3):
            odds = A.update_odds(odds, {"cheapest_any": 0.0, "what_we_quoted": 12.0, "without_trucker": 20.0, "fastest_any": 15.0})
        self.assertGreater(odds["cheapest_any"], 0.9)
        self.assertAlmostEqual(sum(odds.values()), 1.0, 2)


if __name__ == "__main__":
    unittest.main()
