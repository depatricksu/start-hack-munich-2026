"""Quote mails: expert note from our own pricing, prompt asks for mirrored tone with examples."""
import unittest
from llm import extract as llm

BEST = {"total": "1500.00", "currency": "EUR", "airline": "Meridian Freightways", "transit_days": 2}


class TestExpertNote(unittest.TestCase):
    def test_weight_break_note_en_de(self):
        f = {"weight_kg_total": 676, "volume_cbm_total": 0.5, "language": "en", "origin": "CGN", "destination": "ORD"}
        body = llm.fill_reply("{HELLO}\n\nCGN to ORD: {AIRLINE} at {PRICE} all-in.\n\nJust reply and I'll book it.",
                              dict(BEST, billed_kg="1000"), f, "anna.schmidt@x.mail", 1)
        self.assertIn("billed it at 1,000 kg rather than 676 kg", body)
        self.assertIn("1500.00 EUR all-in. I've billed", body)            # same paragraph as the price
        de = llm.expert_note(dict(BEST, billed_kg="2000"), {"weight_kg_total": 1233}, "de")
        self.assertIn("2.000 kg statt 1.233 kg", de)

    def test_volume_note(self):
        n = llm.expert_note(dict(BEST, billed_kg="334"), {"weight_kg_total": 120, "volume_cbm_total": 2.0}, "en")
        self.assertIn("chargeable weight here is 334 kg", n)

    def test_no_note_when_nothing_special(self):
        self.assertEqual(llm.expert_note(dict(BEST, billed_kg="90"), {"weight_kg_total": 90, "volume_cbm_total": 0.4}, "en"), "")
        self.assertEqual(llm.expert_note(BEST, {"weight_kg_total": 90}, "en"), "")

    def test_note_passes_safety_check(self):
        n = llm.expert_note(dict(BEST, billed_kg="1000"), {"weight_kg_total": 676}, "en")
        self.assertTrue(llm.safe_reply("Hi, {PRICE}. " + n, "en")[1])


class TestPrompt(unittest.TestCase):
    def test_prompt_has_examples_and_mirroring(self):
        self.assertIn("Mirror the customer", llm.SYSTEM)
        self.assertIn('Customer: "Hi, price for 300 kg MUC to JFK', llm.SYSTEM)
        self.assertIn("Never start with a thank-you formula", llm.SYSTEM)


if __name__ == "__main__":
    unittest.main()
