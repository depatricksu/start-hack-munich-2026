"""5U, 22 Nov 02:46 (round 107): after 'can you match 7 percent less?' we kept the price and offered a call. The
customer answered 'we accept your offer. Please book the shipment now.' and nothing was booked."""
import os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from booking import handlers  # noqa: E402

REAL = "That works for us, and we accept your offer. Please book the shipment now.\n\nMira Petersen\nNordlicht Audio"


class AcceptAfterCallOffer(unittest.TestCase):
    def decide(self, text):
        return handlers.books_after_call_offer(handlers.classify(text), handlers.own_text(text, ""))

    def test_the_real_answer_books(self):
        self.assertEqual(handlers.classify(REAL), "accept")
        self.assertTrue(self.decide(REAL))

    def test_other_plain_acceptances_book(self):
        for said in ("Understood, please go ahead and book it at the quoted price.", "OK, we accept the quote. Please proceed with the booking.",
                     "In Ordnung, bitte buchen Sie die Sendung zum genannten Preis."):
            self.assertTrue(self.decide(said), said)

    def test_picking_a_time_stays_with_a_person(self):
        for said in ("Tuesday 09:00 works for us, please confirm.", "Mon 23 Nov at 10:30 is fine.", "Yes, let us have the call on Wednesday.",
                     "That works for us.", "Please book the call for Tuesday.", "Dienstag um 9 Uhr passt, bitte bestaetigen."):
            self.assertFalse(self.decide(said), said)

    def test_the_price_question_itself_is_not_an_acceptance(self):
        first = ("Thanks for the offer. It looks good, and we\u2019d like to place the shipment with you.\n\nAnother forwarder has quoted 7 percent "
                 "less for the same shipment. Can you match their rate?")
        self.assertEqual(handlers.classify(first), "better_price")
        self.assertFalse(self.decide(first))


if __name__ == "__main__":
    unittest.main()
