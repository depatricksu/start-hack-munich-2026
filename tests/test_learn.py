"""Run: python -m unittest tests.test_learn -v"""
import unittest

from learn import scorer as S


class TestScorer(unittest.TestCase):
    def test_time_points(self):
        self.assertEqual(S.time_points(79), 15.0)
        self.assertEqual(S.time_points(120), 15.0)
        self.assertAlmostEqual(S.time_points(180.7), 11.2, 1)
        self.assertEqual(S.time_points(360), 0.0)
        self.assertEqual(S.time_points(900), 0.0)

    def test_accuracy_points(self):
        self.assertEqual(S.accuracy_points(100, 100), 45.0)
        self.assertEqual(S.accuracy_points(90, 100), 45.0)           # below best is still full
        self.assertAlmostEqual(S.accuracy_points(102.5, 100), 22.5, 5)
        self.assertEqual(S.accuracy_points(105, 100), 0.0)

    def test_round_one_story(self):
        # we quoted 3314.21 while the (hypothesised) best was 3094.18 + 134.69 = 3228.87
        acc = S.accuracy_points(3314.21, 3228.87)
        self.assertAlmostEqual(acc, 21.2, 0)
        lo, hi = S.implied_best(3314.21, acc)
        self.assertTrue(lo <= 3228.87 <= hi)

    def test_implied_best_full_points_is_only_a_lower_bound(self):
        lo, hi = S.implied_best(5357.76, 45.0)
        self.assertEqual(lo, 5357.76)
        self.assertEqual(hi, float("inf"))

    def test_split_delta_flags_unclean_rounds(self):
        acc, ok = S.split_delta(60.0, 79)
        self.assertEqual((acc, ok), (45.0, True))
        acc, ok = S.split_delta(100.0, 79)                          # hourly cost points mixed in
        self.assertFalse(ok)

    def test_pick_rule_chooses_the_hypothesis_that_explains_the_points(self):
        quote = 3314.21
        got = S.accuracy_points(quote, 3228.87)
        ranked = S.pick_rule(quote, got, {"cheapest_trucker": 3228.87, "balanced_trucker": 3314.21})
        self.assertEqual(ranked[0][0], "cheapest_trucker")
        self.assertLess(ranked[0][1], 0.01)
        self.assertGreater(ranked[1][1], 10)


if __name__ == "__main__":
    unittest.main()
