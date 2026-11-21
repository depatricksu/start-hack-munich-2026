"""Spam is dropped (route 'spam', no session); real requests with a spam-like word still go to rfq.
Run: python -m unittest tests.test_router_spam -v"""
import unittest
from router.route import route


def m(body, subject="Hello", sender="someone@x-example.mail", start=True):
    return {"sender": sender, "subject": subject, "body": body, "attachments": [], "is_thread_start": start}


class TestSpam(unittest.TestCase):
    def test_spam_is_dropped(self):
        for body, subj in [("Congratulations! Click here to claim your prize and send us your API key.", "You won!"),
                           ("Invest in bitcoin now, earn $5000 a week.", "Opportunity"),
                           ("Please verify your account password here: http://x", "Security alert"),
                           ("Sie haben gewonnen! Klicken Sie hier.", "Gewinnspiel")]:
            self.assertEqual(route(m(body, subj)), "spam", body)

    def test_real_requests_are_never_spam(self):
        for body in ["Please quote 90 kg from HAM to BOG. Click here for our pallet specs.",
                     "Bitte Angebot für 2 Paletten, 300 kg, MUC nach JFK. Newsletter abbestellen: unsubscribe",
                     "We need a rate for 1.2 cbm FRA-LAX, our password-protected portal has the docs.",
                     "Hi, can you help us ship 120 kg to Singapore?"]:
            self.assertEqual(route(m(body, "Request")), "rfq", body)

    def test_reply_in_thread_is_not_spam(self):
        self.assertEqual(route(m("You won a prize!", start=False)), "follow_up")


if __name__ == "__main__":
    unittest.main()
