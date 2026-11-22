"""Problems during transit. Run: python3 -m unittest carrierops.tests.test_disruptions"""
import unittest

from carrierops import disruptions, messages

REAL = {
    "weather": ["Due to heavy snowfall all departures from Munich are suspended.", "The flight is grounded because of a storm.",
                "The airport is closed due to fog.", "Wegen Unwetter startet der Flug heute nicht.",
                "Bad weather: your cargo will not make today's flight."],
    "strike": ["A ground handling strike affects your shipment.", "Wegen Streik steht die Fracht fest."],
    "customs": ["Your shipment is held by customs.", "Die Sendung hängt im Zoll fest."],
    "technical": ["Aircraft technical problem, departure pushed back to tomorrow."],
    "closure": ["The airspace is closed until further notice."],
    "diverted": ["The flight was diverted to Muscat."],
    "connection": ["The flight missed its connection in Doha."],
    "damaged": ["One piece was damaged in handling.", "Eine Kiste ist beschädigt."],
    "missing": ["We cannot locate two of the five pieces."],
}
QUIET = ["Your booking is confirmed.", "Departed on time despite the storm.", "A storm may affect flights tomorrow.",
         "If the airport is closed we will inform you.", "Your shipment is not affected by the strike.",
         "The airport has reopened after the snow.", "The shipment has been released by customs.",
         "The cargo was not damaged.", "Arrived at the airport.", "Please send the customs invoice.",
         "Thanks.\n> the airport is closed due to fog"]


class Disruptions(unittest.TestCase):
    def test_real_problems(self):
        for key, texts in REAL.items():
            for t in texts:
                self.assertEqual((disruptions.detect("Booking BK-TEST1234 update", t) or {}).get("key"), key, t)

    def test_no_false_alarm(self):
        for t in QUIET:
            self.assertIsNone(disruptions.detect("Booking BK-TEST1234 update", t), t)

    def test_unknown_new_date_is_never_the_old_date(self):
        s = {"airline": "Test Air", "destination": "ORD", "eta_current": "2026-11-29", "our_ref": "GOOGLE-1"}
        body = messages.customer_update(s, "delayed", {})[1]
        self.assertIn("to follow", body)
        self.assertNotIn("29 Nov", body)


if __name__ == "__main__":
    unittest.main()
