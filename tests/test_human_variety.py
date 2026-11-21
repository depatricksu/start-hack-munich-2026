"""The jury reads our mails round after round: the same personal line twice in a row reads as a template.

Real case (21 Nov): 4 of our last 25 quotes opened with "All good here, thanks, I hope your week is going well too."
and our human wins stopped after round 38. human.fresh() never repeats a line within RECENT_N quotes.
"""
import unittest

from llm import human

BODY = "Hi Klaus,\n\nThe price is 100.00 EUR with Test Air.\n\nShall I book it?\n\nCheers\nLena Hofmann\nAir Export"


class Variety(unittest.TestCase):
    def setUp(self):
        human._recent.clear()

    def test_well_answer_never_repeats_within_window(self):
        firsts = []
        for tid in range(8):                                  # 8 customers in a row all write "hope your week..."
            out = human.mirror(BODY, {"well": "week"}, "en", thread_id=tid)
            firsts.append(out.split("\n")[2].split(". ")[0])
        self.assertEqual(len(firsts), len(set(firsts)), firsts)

    def test_all_used_takes_the_oldest(self):
        opts = ("a", "b", "c")
        got = [human.fresh(opts, 7, "t") for _ in range(6)]
        self.assertEqual(len(set(got[:3])), 3, got)
        self.assertEqual(got[3:], got[:3], got)               # round robin, never the line just used

    def test_touch_lines_rotate_and_available_has_no_side_effect(self):
        f = {"destination": "ORD", "origin": "MUC"}
        human.available(f, "en")                              # only probes the styles
        self.assertEqual(human._recent, [])
        lines = {human.apply(BODY, "destination", f, "en", thread_id=1).split("\n")[-5] for _ in range(3)}
        self.assertEqual(len(lines), 3, lines)
        self.assertTrue(all(l[:1].isupper() for l in lines), lines)

    def test_window_is_bounded(self):
        for i in range(human.RECENT_N + 5):
            human.fresh(("x%d" % i,), 0, "t")
        self.assertEqual(len(human._recent), human.RECENT_N)


if __name__ == "__main__":
    unittest.main()
