"""5U round 57 (21 Nov 21:40): the mail said 1210 kg, the attached packing list 1729 kg. We priced the mail and were
rejected too_low. The packing list is the shipping document: its gross weight / volume win.
Run: python -m unittest tests.test_packing_list_wins"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
import dg  # noqa: E402
from dg import facts  # noqa: E402

REAL = """Packing List
No. 55245
Date: 2026-11-23
Shipper: Consignee: Destination airport: EZE
Goods description: furniture samples
Auer Maschinenbau GmbH, Regensburg, Germany
Buenos Aires Imports Ltd., Buenos Aires, AR
Total pieces: 7
Total gross weight (kg): 1729
Total volume (cbm): 8.47
Dangerous goods: Not restricted
Gross weight (kg) Width (cm) Length (cm) Height (cm) Pieces
1729 80 140 108 7
"""


class TestPackingListWins(unittest.TestCase):
    def test_reads_the_real_round_57_packing_list(self):
        self.assertEqual(facts.packing_facts(REAL), {"gross_kg": 1729.0, "pieces": 7, "volume_cbm": 8.47})

    def test_reads_the_spreadsheet_layout(self):
        """Round 35 (thr 8862): xlsx cells arrive as 'label: | value'. Mail said 2644 kg, the list 1751 kg -> too_high."""
        xlsx = ("Packing Specification\nNo. 81971\n\nDate: | 2026-11-24\nDestination airport: | SGN\n\n"
                "Total pieces: | 19\nTotal gross weight (kg): | 1751\nTotal volume (cbm): | 11.97\n"
                "Dangerous goods: | Not restricted\n\nGross weight (kg) | Length (cm) | Height (cm) | Width (cm) | Pieces\n"
                "1751 | 100 | 63 | 100 | 19")
        self.assertEqual(facts.packing_facts(xlsx), {"gross_kg": 1751.0, "pieces": 19, "volume_cbm": 11.97})

    def test_a_smaller_volume_on_the_list_wins_too(self):
        """Round 33 (thr 8493): mail 2.78 cbm, list 1.92 cbm. We priced 464 kg chargeable instead of 321 -> too_high."""
        facts.remember(900002, "Total pieces: 5\nTotal gross weight (kg): 292\nTotal volume (cbm): 1.92")
        diff = dg.compare({"weight_kg_total": 292.0, "volume_cbm_total": 2.78}, {"id": 900002})
        self.assertEqual(diff, {"volume_cbm": {"mail": 2.78, "attachment": 1.92}})
        self.assertEqual(dg.winner(diff["volume_cbm"]), 1.92)
        out = dg.note({"language": "de", "attachment_used": diff}, "Guten Tag,\n\nPreis 900.00 EUR.\n\nMit freundlichen Grüßen\nLena")
        self.assertIn("1.92 cbm", out)

    def test_older_layouts_still_read(self):
        f = facts.packing_facts("Gross weight: 1,250 kg\nTotal pieces: 12\nVolume: 3.2 cbm")
        self.assertEqual((f["gross_kg"], f["pieces"], f["volume_cbm"]), (1250.0, 12, 3.2))

    def test_difference_is_found_and_the_attachment_wins(self):
        facts.remember(900001, REAL)
        diff = dg.compare({"weight_kg_total": 1210.0, "volume_cbm_total": 8.47}, {"id": 900001})
        self.assertEqual(diff, {"gross_kg": {"mail": 1210.0, "attachment": 1729.0}})   # volume agrees: not in the diff
        self.assertTrue(dg.override())                                                  # on by default now
        self.assertEqual(dg.winner(diff["gross_kg"]), 1729.0)

    def test_a_number_far_off_is_treated_as_a_misread(self):
        self.assertEqual(dg.winner({"mail": 1210.0, "attachment": 17290.0}), 1210.0)   # 14x: keep the mail's number
        self.assertEqual(dg.winner({"mail": 1210.0, "attachment": 120.0}), 1210.0)     # a tenth: keep the mail's number

    def test_the_quote_says_which_weight_was_priced(self):
        body = "Hi Tobias,\n\nThe cheapest option is 6100.00 EUR all-in.\n\nBest regards\nLena Hofmann"
        out = dg.note({"language": "en", "attachment_used": {"gross_kg": {"mail": 1210.0, "attachment": 1729.0}}}, body)
        self.assertIn("1729 kg", out); self.assertIn("1210 kg", out)
        self.assertLess(out.index("packing list"), out.index("Best regards"))           # before the sign-off
        self.assertEqual(dg.note({"language": "en"}, body), body)                       # nothing used: untouched


if __name__ == "__main__":
    unittest.main()
