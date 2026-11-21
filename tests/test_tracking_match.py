"""Tracking mails name the pickup POSTCODE, our bookings store the airport. Run: python -m unittest tests.test_tracking_match -v

These are the real texts of the two tracking questions of 21 Nov 16:14 and 16:18 that scored nothing.
"""
import os, tempfile, time, unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")
os.environ.setdefault("FIVEU_API_KEY", "")

from booking import crm, tracking  # noqa: E402

Q1 = ("Status of our shipment 51447 to ORD, 676 kg",
      "Hi,\n\nCould you confirm where the shipment below is now and share its current status?\n\nLindqvist Medtech GmbH | 51447 to ORD | 676 kg | Ready date: 2026-11-25\n\nThanks.\nSara Lindqvist Medtech")
Q2 = ("Status of our shipment 61018 to JFK, 1233 kg",
      "Dear Sir or Madam,\n\nCould you please confirm the current location and status of the shipment we booked with you for Sonnberg Kaffeeroesterei GmbH, from 61018 to JFK, with a gross weight of 1233 kg and a ready date of 2026-11-25?\n\nKind regards\nAnna Sonnberg")


class TestTrackingMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = time.time()
        crm.upsert(98001, customer="lindqvist-medtech@hackloop.mail", origin="CGN", destination="ORD", airline="Meridian Freightways",
                   weight_kg=676, volume_cbm=5.79, transit_days=1, status="confirmed", booking_reference="BK-XLWLOHNP",
                   booked_at=now - 300, confirmed_at=now - 250)
        crm.upsert(98002, customer="sonnberg-roesterei@hackloop.mail", origin="FRA", destination="JFK", airline="Solace Air Cargo",
                   weight_kg=1233, volume_cbm=10.78, transit_days=2, status="confirmed", booking_reference="BK-4WSWKLL7",
                   booked_at=now - 200, confirmed_at=now - 150)
        crm.upsert(98003, customer="rheintal-elektronik@hackloop.mail", origin="CGN", destination="ORD", airline="Aurelia Air Cargo",
                   weight_kg=679, volume_cbm=4.19, transit_days=2, status="booked", booking_reference="BK-DECOY001", booked_at=now - 10)

    def test_postcode_zone_matches_the_airport(self):
        b, how = tracking.find_booking(Q2[0] + "\n" + Q2[1])
        self.assertEqual((b["booking_reference"], how), ("BK-4WSWKLL7", "route"))

    def test_two_bookings_on_the_same_lane_are_told_apart_by_weight_and_company(self):
        b, how = tracking.find_booking(Q1[0] + "\n" + Q1[1])          # 676 kg is within 2% of both 676 and 679
        self.assertEqual(b["booking_reference"], "BK-XLWLOHNP")

    def test_company_name_breaks_a_weight_tie(self):
        b, _ = tracking.find_booking("Where is the Rheintal Elektronik shipment 51896 to ORD, 678 kg?")
        self.assertEqual(b["booking_reference"], "BK-DECOY001")

    def test_reference_still_wins(self):
        b, how = tracking.find_booking("Where is BK-4WSWKLL7?")
        self.assertEqual((b["thread_id"], how), (98002, "reference"))

    def test_unknown_destination_and_weight_is_still_no_match(self):
        self.assertEqual(tracking.find_booking("Where is my parcel to SYD, 5 kg?"), (None, "no match"))

    def test_answer_has_what_a_tracking_check_needs(self):
        b, _ = tracking.find_booking(Q1[0] + "\n" + Q1[1])
        txt = tracking.answer_text(b)
        for needle in ("BK-XLWLOHNP", "CGN to ORD", "Meridian Freightways", "676", "confirmed"):
            self.assertIn(needle, txt)


if __name__ == "__main__":
    unittest.main()
