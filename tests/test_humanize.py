"""humanize/: the last touch on a quote mail (owner Riky). Real mails from the 21 Nov snapshot."""
import re
import unittest

import humanize

ANNA = ("Dear Sir or Madam,\n\nCould you please quote the fastest air freight option to JFK (New York, US)? The shipment "
        "will be ready for pickup on 2026-11-25.\n\nPlease provide your all-in price in EUR and confirm the earliest "
        "available arrival at JFK.\n\nKind regards\nAnna Sonnberg\nHead of Purchasing\nSonnberg Kaffeeroesterei GmbH")
REPLY = ("Hi Sonnberg,\n\nThe all-in price is 5357.76 EUR with Solace Air Cargo, transit 2 days, 1,233 kg kg.\n\n"
         "Best regards\nLena Hofmann\nAir Export")
BEST = {"total": "5357.76", "transit_days": 2}


class Polish(unittest.TestCase):
    def test_real_request_424(self):
        body, changes = humanize.polish(REPLY, {"destination": "JFK", "language": "en"}, BEST, ANNA)
        self.assertTrue(body.startswith("Hi Anna,"))
        self.assertIn("arrive in New York around Fri 27 Nov", body)
        self.assertNotIn("kg kg", body)
        self.assertLess(body.index("arrive in New York"), body.index("Best regards"))
        self.assertEqual(re.findall(r"\d+\.\d\d", body), ["5357.76"])          # the price is never touched
        self.assertEqual(set(changes), {"greeting_name", "doubled_unit", "answered_ask"})

    def test_signed_name(self):
        self.assertEqual(humanize.signed_name(ANNA), "Anna")
        self.assertEqual(humanize.signed_name("Hi,\n\nquote please.\n\nSara\nLindqvist Medtech"), "Sara")
        self.assertEqual(humanize.signed_name("Viele Gruesse / Many greetings\nDeniz Yilmaz\nRheintal Elektronik GmbH"), "Deniz")
        self.assertIsNone(humanize.signed_name("pls quote.\n\nThanks"))

    def test_insurance_customs_usd(self):
        mail = "Please quote in USD, including insurance and customs clearance.\n\nBest\nTom"
        body, _ = humanize.polish("Hi Tom,\n\nTotal 900.00 EUR.\n\nBest regards\nLena", {}, {}, mail)
        for part in ("Cargo insurance isn't included", "Customs clearance isn't included", "quoted the total in EUR"):
            self.assertIn(part, body)

    def test_nothing_to_do_and_errors(self):
        plain = "Hi Tom,\n\nTotal 900.00 EUR.\n\nBest regards\nLena"
        self.assertEqual(humanize.polish(plain, {}, {}, "Quote FRA-JFK 100 kg.\n\nBest\nTom"), (plain, []))
        self.assertEqual(humanize.polish(None, None, None, None)[0], None)


if __name__ == "__main__":
    unittest.main()


class Dates(unittest.TestCase):
    """Kai's review of #24: a deadline must never be read as the ready date."""
    REPLY = "Hi Tom,\n\nTotal 900.00 EUR, transit 5 days.\n\nBest regards\nLena"

    def test_deadline_only_says_nothing(self):
        mail = "It MUST arrive by 2026-11-24. When will it arrive?\n\nBest\nTom"
        body, _ = humanize.polish(self.REPLY, {}, {"transit_days": 5}, mail)
        self.assertNotIn("Nov", body)

    def test_ready_date_wins_over_deadline(self):
        mail = "Arrival needed before 2026-11-30, goods ready 2026-11-25. When will it arrive?\n\nBest\nTom"
        body, _ = humanize.polish(self.REPLY, {}, {"transit_days": 3}, mail)
        self.assertIn("ready on Wed 25 Nov", body)
        self.assertIn("around Sat 28 Nov, ahead of your Mon 30 Nov deadline", body)

    def test_we_would_miss_the_deadline(self):
        mail = "Goods ready 2026-11-25, must arrive by 2026-11-27. Earliest arrival?\n\nBest\nTom"
        body, _ = humanize.polish(self.REPLY, {}, {"transit_days": 5}, mail)
        self.assertNotIn("arrive in", body)


class Layout(unittest.TestCase):
    def test_german_date_words_and_sentence_before_signature(self):
        mail = "Bitte um Angebot, die Ware ist am 2026-11-28 abholbereit. Wann kommt sie an?\n\nViele Grüße\nDeniz Yilmaz"
        reply = "Guten Tag Deniz Yilmaz,\n\nPreis 1599.41 EUR, 3 Tage.\n\nLena Hofmann\nLuftfracht Export"
        body, _ = humanize.polish(reply, {"language": "de", "destination": "ORD"}, {"transit_days": 3}, mail)
        self.assertIn("28. November", body)
        self.assertNotIn("28.11.", body)
        self.assertTrue(body.rstrip().endswith("Lena Hofmann\nLuftfracht Export"))
        self.assertEqual(re.findall(r"\d+\.\d\d", body), ["1599.41"])
