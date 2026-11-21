"""Fixes from the 21 Nov 20:20 review (Riky): each case lost or could lose a round."""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from shared.rfq import gate  # noqa: E402
from router.route import route  # noqa: E402

BASE = {"origin": "HAM", "destination": "YYZ", "weight_kg": 500, "weight_kg_total": 500, "volume_cbm": 2,
        "volume_cbm_total": 2, "prefer": "cheapest", "kind": "new_request", "pieces": [], "shipments": []}


def note(body):
    return gate(dict(BASE), {"id": 1, "subject": "RFQ", "body": "HAM to YYZ. " + body, "sender": "c@x"})[1]


class Hyphens(unittest.TestCase):
    def test_a_dash_with_a_space_is_not_a_negative_weight(self):
        for body in ("- 500 kg gross, 2 cbm", "2 pallets - 500 kg", "Lot 1 - 300 kg, Lot 2 - 200 kg", "500 - 600 kg"):
            self.assertNotIn("negative weight", note(body), body)

    def test_a_glued_minus_still_stops(self):
        for body in ("Weight: -500 kg", "weight -500kg"):
            self.assertIn("negative weight", note(body), body)


class TrackingRoute(unittest.TestCase):
    def mail(self, sender, subject):
        return {"sender": sender, "subject": subject, "body": "", "attachments": [], "is_thread_start": True}

    def test_tracking_question_naming_a_booking_is_tracking(self):
        self.assertEqual(route(self.mail("tracking@hackloop.mail", "Status of booking BK-XLWLOHNP")), "tracking")

    def test_carrier_confirmation_is_still_a_confirmation(self):
        self.assertEqual(route(self.mail("meridian-freightways@hackloop.mail", "Booking BK-ABC confirmed")),
                         "booking_confirmation")


if __name__ == "__main__":
    unittest.main()


class Weights(unittest.TestCase):
    def test_rounded_piece_weights_are_the_same_total(self):
        from core.main import shipment
        self.assertAlmostEqual(shipment({"weight_kg": 500, "pieces": [{"count": 4, "kg_each": 120}]})[0], 500)
        lots = {"weight_kg": 730, "pieces": [{"count": 4, "kg_each": 48}, {"count": 5, "kg_each": 206}]}
        self.assertAlmostEqual(shipment(lots)[0], 1952)                     # round 9: real lots still add up


class TransitText(unittest.TestCase):
    def test_text_transit_never_crashes(self):
        from sourcing.bids import bid_hours, _f
        self.assertEqual(_f("1-2"), 2.0)
        self.assertEqual(bid_hours({"hours": None, "transit_days": "1-2"}), 48.0)
        self.assertIsNone(bid_hours({"hours": None, "transit_days": "soon"}))
