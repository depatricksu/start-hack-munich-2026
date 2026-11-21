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

    def test_vendor_pitch_is_dropped(self):
        """5U 21:21, the real mail: it mentions quotes and RFQs but has no shipment in it."""
        pitch = ("Hi there,\n\nI noticed your company handles air export quotes. Most forwarders we talk to lose 30% of "
                 "their RFQs because replies are too slow.\n\nFreightSoft Pro answers every RFQ in under 60 seconds. Could "
                 "we book 15 minutes this week to show you a demo? Just reply with a time that suits you.\n\nCheers\n"
                 "Tom Becker\nAccount Executive, FreightSoft Pro")
        self.assertEqual(route(m(pitch, "Quick question about your quoting process")), "spam")
        self.assertEqual(route(m("Our platform cuts freight costs. Schedule a call with our sales team?", "Save 20%")), "spam")

    def test_a_request_with_sales_words_is_still_a_request(self):
        for body in ["Could we book a call? We also need a quote for 300 kg from FRA to JFK.",
                     "Our account executive asked me to request a rate: 2 pallets, 1.4 cbm, pickup in 80331 Munich.",
                     "Please quote MUC-ORD for our product samples, details follow.",
                     "Can you show us a demo of your tracking? Shipment is 85 kg to Dubai."]:
            self.assertEqual(route(m(body, "Request")), "rfq", body)
        with_file = dict(m("Our software team sends the packing list attached, please book a call if unclear."),
                         attachments=[{"filename": "packing-list.pdf"}])
        self.assertEqual(route(with_file), "rfq")                # an attachment may hold the shipment: never dropped

    def test_reply_in_thread_is_not_spam(self):
        self.assertEqual(route(m("You won a prize!", start=False)), "follow_up")


if __name__ == "__main__":
    unittest.main()
