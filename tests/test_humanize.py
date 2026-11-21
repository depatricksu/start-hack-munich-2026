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
