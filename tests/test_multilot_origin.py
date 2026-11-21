"""Live bugs 21 Nov: multi-lot under-count (round 9 too_low) and the string 'NULL' origin (round 10).
Run: python -m unittest tests.test_multilot_origin -v"""
import os, tempfile, unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")
os.environ.setdefault("FIVEU_API_KEY", "")

from core import main  # noqa: E402


class TestShipmentWeight(unittest.TestCase):
    def test_single_shipment_total_only(self):
        self.assertEqual(main.shipment({"weight_kg": 230, "volume_cbm": 1.2, "pieces": []}), (230.0, 1.2))

    def test_pieces_with_dims_add_volume_not_weight(self):
        f = {"weight_kg": 230, "pieces": [{"count": 3, "l_cm": 120, "w_cm": 80, "h_cm": 100}]}  # 3 x 0.96 = 2.88 cbm
        w, v = main.shipment(f)
        self.assertEqual(w, 230.0)
        self.assertAlmostEqual(v, 2.88, 3)

    def test_the_round_9_mail_sums_all_three_lots(self):
        # Lot 1 -> weight_kg + volume_cbm; Lots 2 & 3 -> pieces with kg_each (the model split them)
        f = {"weight_kg": 730, "volume_cbm": 1.68,
             "pieces": [{"count": 4, "l_cm": 110, "w_cm": 110, "h_cm": 52, "kg_each": 48},
                        {"count": 5, "l_cm": 120, "w_cm": 100, "h_cm": 8, "kg_each": 206}]}
        w, v = main.shipment(f)
        self.assertEqual(w, 1952.0)                              # 730 + 192 + 1030, NOT 730
        self.assertAlmostEqual(v, 1.68 + 2.5168 + 0.48, 3)

    def test_all_in_pieces_no_total(self):
        f = {"weight_kg": None, "pieces": [{"count": 2, "kg_each": 100}, {"count": 1, "kg_each": 50}]}
        self.assertEqual(main.shipment(f)[0], 250.0)


class TestOriginSanitize(unittest.TestCase):
    def test_string_null_origin_is_treated_as_empty(self):
        self.assertIsNone(main._airport("NULL"))
        self.assertIsNone(main._airport("null"))
        self.assertIsNone(main._airport(None))
        self.assertIsNone(main._airport(""))
        self.assertEqual(main._airport("fra"), "FRA")

    def test_round_10_derives_fra_from_pickup_zone_despite_null_origin(self):
        fields = {"origin": "NULL", "destination": "GRU", "pickup_postcode": "61391", "weight_kg": 715, "volume_cbm": 2.65, "pieces": []}
        fields["origin"] = main._airport(fields.get("origin"))
        fields["destination"] = main._airport(fields.get("destination"))
        pc = str(fields.get("pickup_postcode") or "")
        if not fields.get("origin") and pc[:2] in main.ZONE_AIRPORT:
            fields["origin"] = main.ZONE_AIRPORT[pc[:2]]
        self.assertEqual(fields["origin"], "FRA")                # zone 61 -> FRA, not blocked by "NULL"
        self.assertEqual(fields["destination"], "GRU")


if __name__ == "__main__":
    unittest.main()
