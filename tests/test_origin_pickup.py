"""Door pickup: the pickup postcode decides the departure airport (round 17, 21 Nov). Run: python -m unittest tests.test_origin_pickup"""
import os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main  # noqa: E402

CUSTOMER = "sara@lindqvist.mail"


def thread(tid, *bodies):
    for i, body in enumerate(bodies):
        m = main.mailbox.normalize({"id": tid + i, "from": CUSTOMER, "subject": "Air freight quote to EZE", "body": body,
                                    **({"in_reply_to": tid, "references": [tid]} if i else {})})
        db.save_mail(m)
        if not i:
            db.new_session(m)


class TestOriginFromPickup(unittest.TestCase):
    def test_round_17_model_guessed_fra_postcode_says_str(self):
        """The real mails of thread 4130: no airport anywhere, the model filled in FRA after the customer's answer."""
        thread(6610001, "Could you quote your cheapest air freight option to EZE, all-in in EUR, including truck pickup "
                        "from our warehouse to the airport?\nThe shipment is 12 pieces, 1805 kg gross and 6.92 cbm.",
               "Sorry I left out the pickup location: 72146 Tuebingen, Germany.")
        f = {"origin": "FRA", "destination": "EZE", "pickup_postcode": "72146"}
        main.origin_from_pickup(6610001, f)
        self.assertEqual(f["origin"], "STR")
        self.assertTrue(db.con().execute("SELECT 1 FROM events WHERE kind='origin_from_pickup' AND thread_id=6610001").fetchone())

    def test_agreeing_origin_is_untouched(self):
        thread(6610010, "Quote 676 kg to ORD, pickup at 51447 Bergisch Gladbach please.")
        f = {"origin": "CGN", "destination": "ORD", "pickup_postcode": "51447"}
        main.origin_from_pickup(6610010, f)
        self.assertEqual(f["origin"], "CGN")

    def test_missing_origin_is_filled(self):
        thread(6610020, "Quote 715 kg to GRU, pickup from our site in 61391 Bad Homburg.")
        f = {"origin": None, "destination": "GRU", "pickup_postcode": "61391"}
        main.origin_from_pickup(6610020, f)
        self.assertEqual(f["origin"], "FRA")

    def test_airport_the_customer_named_is_kept(self):
        thread(6610030, "Please quote 500 kg from FRA to JFK. Pickup at our site in 72146 Tuebingen, truck it to Frankfurt.")
        f = {"origin": "FRA", "destination": "JFK", "pickup_postcode": "72146"}
        main.origin_from_pickup(6610030, f)
        self.assertEqual(f["origin"], "FRA")

    def test_no_postcode_or_unknown_zone_changes_nothing(self):
        thread(6610040, "Quote 500 kg FRA to JFK.")
        for f in ({"origin": "FRA", "pickup_postcode": None}, {"origin": "FRA", "pickup_postcode": "99999"}):
            main.origin_from_pickup(6610040, f)
            self.assertEqual(f["origin"], "FRA")


if __name__ == "__main__":
    unittest.main()
