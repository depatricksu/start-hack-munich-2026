"""Language of the customer (llm/lang.py) and the reply quality gate (llm/quality.py). No network, no key."""
import os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["LLM_FAKE"] = "1"

from llm import lang, quality, extract as llm
from booking import replies, tracking

ROUND4 = ("Hello,\n\nCould you please quote your cheapest air freight option to ORD for 3 pallets, 420 kg in total, "
          "1.8 cbm? Pickup would be at our site in 51465 Bergisch Gladbach.\n\nViele Gruesse / Many greetings,\n"
          "Deniz Yilmaz\nRheintal Elektronik GmbH")
GERMAN = ("Guten Tag,\n\nwir benötigen ein Angebot für eine Sendung von Hamburg nach Chicago, 250 kg, 1,2 cbm. "
          "Bitte die schnellste Option.\n\nViele Grüße\nKatrin Weber")
ITALIAN = ("Buongiorno,\n\nvorremmo un preventivo per una spedizione aerea da Francoforte a Dubai, 180 kg, 0,9 cbm. "
           "Grazie per la risposta.\n\nCordiali saluti\nMarco Rossi")
BEST = {"total": "1234.50", "currency": "EUR", "airline": "Rhein Cargo", "transit_days": 4}
FIELDS = {"origin": "CGN", "destination": "ORD", "weight_kg_total": 420.0, "language": "en",
          "customer_numbers": quality.numbers(ROUND4), "customer_lines": quality.customer_lines(ROUND4)}
GOOD = ("Hi Deniz,\n\nthanks for the details on your 3 pallets to Chicago. For the 420 kg we can offer 1234.50 EUR all-in "
        "with Rhein Cargo, about 4 days in transit.\n\nJust reply to this mail and I'll book it.\n\n"
        "Best regards\n%s\nAir Export" % llm.SIGNER)


class Detect(unittest.TestCase):
    def test_round4_english_mail_with_german_signoff_and_town(self):
        self.assertEqual(lang.detect("Air freight quote ORD\n" + ROUND4), "en")

    def test_german_italian_french_spanish(self):
        self.assertEqual(lang.detect(GERMAN), "de")
        self.assertEqual(lang.detect(ITALIAN), "it")
        self.assertEqual(lang.detect("Bonjour, pouvez-vous nous envoyer un devis pour un envoi de 200 kg vers Dubai ? Merci"), "fr")
        self.assertEqual(lang.detect("Hola, necesitamos una cotización para un envío de 200 kg desde Hamburgo. Gracias"), "es")

    def test_one_line_is_not_sure(self):
        for t in ("FRA JFK 200 kg", "Quote FRA - JFK, 200 kg, 1 cbm", "", "Angebot HAM BOG 90 kg"):
            self.assertIsNone(lang.detect(t), t)

    def test_hint_and_override(self):
        self.assertEqual(lang.hint("en"), "The customer wrote in English. Write the reply in English.")
        self.assertEqual(lang.hint(None), "")
        f = llm._annotate({"language": "de"}, {"subject": "Quote", "body": ROUND4}, lang.detect(ROUND4))
        self.assertEqual((f["language"], f["language_model"]), ("en", "de"))
        f = llm._annotate({"language": "de"}, {"subject": "x", "body": "FRA JFK 200 kg"}, None)
        self.assertEqual(f["language"], "de")                     # not sure: the model's answer stays

    def test_one_call_carries_the_hint(self):
        seen = []

        def api(method, path, timeout=0, body=None):
            seen.append(body)
            return 200, {"choices": [{"message": {"content": '{"language": "de", "reply": "Hi, {PRICE} {AIRLINE} {TRANSIT_DAYS}"}'}}]}
        old, old_fake = llm.mailbox.api, llm.config.LLM_FAKE
        llm.mailbox.api, llm.config.LLM_FAKE = api, False
        try:
            f, _ = llm.extract({"subject": "Quote ORD", "body": ROUND4})
        finally:
            llm.mailbox.api, llm.config.LLM_FAKE = old, old_fake
        self.assertEqual(len(seen), 1)                            # exactly one gateway call
        self.assertIn("The customer wrote in English.", seen[0]["messages"][1]["content"])
        self.assertEqual(f["language"], "en")


class Gate(unittest.TestCase):
    def check(self, body, **kw):
        return quality.check(body, kw.get("lang", "en"), BEST, dict(FIELDS, **kw.get("fields", {})),
                             "deniz.yilmaz@rheintal.mail", llm.SIGNER, ["deniz", "yilmaz"])

    def test_good_reply_passes(self):
        self.assertEqual(self.check(GOOD), [])

    def test_wrong_language(self):
        de = GOOD.replace("thanks for the details on your 3 pallets to Chicago. For the 420 kg we can offer",
                          "danke für Ihre Anfrage, für Ihre 420 kg können wir mit").replace(
            "Just reply to this mail and I'll book it.", "Wenn das für Sie passt, antworten Sie einfach und ich buche.")
        self.assertTrue(any("customer wrote en" in r for r in self.check(de)))

    def test_invented_instruction_round5(self):
        bad = GOOD.replace("Just reply", "Please make sure to drop off your goods before the latest time provided by us. Just reply")
        self.assertTrue(any("cannot know" in r for r in self.check(bad)))

    def test_each_rule(self):
        cases = {
            "placeholder": GOOD.replace("420 kg", "{WEIGHT_KG}"),
            "sign-off": GOOD.replace("\n\nBest regards", "\n\nBest,\nDeniz Yilmaz\n\nBest regards"),
            "not signed": GOOD.replace(llm.SIGNER, "Deniz Yilmaz"),
            "exactly one price": GOOD.replace("about 4 days", "or 990.00 EUR with about 4 days"),
            "airline": GOOD.replace("Rhein Cargo", "the airline"),
            "too long": GOOD.replace("Just reply", "We look at this lane often and it is a good one. " * 8 + "Just reply"),
            "machine phrase": GOOD.replace("thanks for", "I hope this email finds you well. Thanks for"),
            "not from our data": GOOD.replace("Just reply", "The flight leaves on 27 November. Just reply"),
        }
        for want, body in cases.items():
            self.assertTrue(any(want in r for r in self.check(body)), "%s: %s" % (want, self.check(body)))

    def test_failed_reply_falls_back_to_our_own_text(self):
        bad = ("Guten Tag Deniz Yilmaz,\n\nunser Preis für Ihre Sendung ist {PRICE} mit {AIRLINE}, Laufzeit {TRANSIT_DAYS} Tage. "
               "Wir freuen uns auf Ihre Antwort.\n\nDeniz Yilmaz")
        body, why = llm.final_reply(bad, BEST, FIELDS, "deniz.yilmaz@rheintal.mail", 4)
        self.assertTrue(why)
        self.assertTrue(body.startswith("Hi Deniz,"))
        self.assertEqual(quality.check(body, "en", BEST, FIELDS, "", llm.SIGNER, ["deniz", "yilmaz"]), [])
        self.assertEqual(body.count("Deniz"), 1)                  # greeting only: never signed with the customer's name (03ddbf3)
        self.assertTrue(body.endswith("%s\nAir Export" % llm.SIGNER))

    def test_good_model_reply_is_kept(self):
        t = ("Hi Deniz,\n\nfor your 3 pallets to Chicago we can do {PRICE} all-in with {AIRLINE}, around {TRANSIT_DAYS} days "
             "in transit. Just reply and I'll book it.")
        body, why = llm.final_reply(t, BEST, FIELDS, "deniz.yilmaz@rheintal.mail", 4)
        self.assertEqual(why, [])
        self.assertIn("3 pallets to Chicago", body)

    def test_own_templates_pass_in_every_language(self):
        for lg in llm.HUMAN:
            for tid in range(6):
                f = dict(FIELDS, language=lg)
                body, why = llm.final_reply("", BEST, f, "anna.schmidt@x.mail", tid)
                self.assertEqual(quality.check(body, lg, BEST, f, "", llm.SIGNER, ["anna", "schmidt"]), [], body)
                self.assertNotIn("{", body)


class BookingAndTracking(unittest.TestCase):
    V = {"ROUTE": "HAM-BOG", "AIRLINE": "Elbflug", "PRICE": "900.00 EUR", "REF": "BK-AAAA1111", "TRANSIT": 3,
         "SLOTS": "Mon 10:00", "FORWARDER": "Jonas", "ALT_AIRLINE": "Isar Air", "ALT_PRICE": "850.00 EUR", "ALT_TRANSIT": 5, "NEW_PRICE": "990.00 EUR"}

    def test_booking_mails_language_signature_and_tone(self):
        import re
        ph = lambda texts: set().union(*(re.findall(r"\{[A-Z_]+\}", t) for t in texts))
        for kind in replies.BODY:
            for lg in ("en", "de", "it", "fr", "es"):
                self.assertIn(lg, replies.BODY[kind], (kind, lg))     # really used, not the English fallback
                self.assertIn(lg, replies.CLOSE[kind], (kind, lg))
                self.assertTrue(lg in replies.GREET and lg in replies.SIGN, lg)
                for part in (replies.BODY, replies.CLOSE):            # same placeholders as the English texts
                    en = ph(part[kind]["en"])
                    self.assertEqual(ph(part[kind][lg]), en, (kind, lg))
                    for t in part[kind][lg]:
                        self.assertLessEqual(ph([t]), en, t)
                        if lg not in ("en", "de"):
                            self.assertIsNone(re.search(r"\d", t), t)  # never a digit of a price in the text
                self.assertEqual(replies.combos(kind, lg)[0], lg)
                for tid in range(8):
                    text = replies.render(kind, lg, self.V, thread_id=tid, customer="deniz.yilmaz@x.mail")[0]
                    self.assertNotIn("{", text)
                    self.assertIn(lang.detect(text), (lg, None), text)
                    self.assertEqual(text.split("\n")[-2], llm.SIGNER)
                    self.assertEqual(text.count("Deniz"), 1)
                    self.assertNotIn("Yilmaz", text)
                    self.assertIsNone(quality.AI_PHRASES.search(text))

    def test_tracking_answers_in_the_customers_language(self):
        b = {"origin": "HAM", "destination": "MEX", "booking_reference": "BK-CCCC3333", "team_reference": "GOOGLE-105",
             "status": "confirmed", "confirmed_at": 1795000000, "booked_at": 1795000000, "transit_days": 3,
             "weight_kg": 300.0, "volume_cbm": 1.5, "airline": "Elbflug Air Freight"}
        en, de = tracking.answer_text(b, 1), tracking.answer_text(b, 1, "de")
        self.assertEqual(lang.detect(en.split("\n\n")[1]), "en")
        self.assertEqual(lang.detect(de.split("\n\n")[1]), "de")
        for t in (en, de, tracking.not_found("en"), tracking.not_found("de")):
            self.assertEqual(t.split("\n")[-2], llm.SIGNER)
            self.assertNotIn("{", t)
        for fact in ("BK-CCCC3333", "GOOGLE-105", "Elbflug Air Freight", "300 kg"):
            self.assertIn(fact, de)


class TestGateAllowsOurOwnBilledWeight(unittest.TestCase):
    def test_expert_note_numbers_pass_the_gate(self):
        from llm import extract as E
        best = {"total": "1500.00", "currency": "EUR", "airline": "Meridian Freightways", "transit_days": 2, "billed_kg": "1000"}
        f = {"weight_kg_total": 676, "volume_cbm_total": 0.5, "language": "en", "origin": "CGN", "destination": "ORD"}
        body, reasons = E.final_reply("{HELLO}\n\nCGN to ORD: {AIRLINE} at {PRICE} all-in.\n\nJust reply and I'll book it.", best, f, "anna.schmidt@x.mail", 1)
        self.assertEqual(reasons, [])
        self.assertIn("billed it at 1,000 kg rather than 676 kg", body)

    def test_rounded_volume_weight_in_the_expert_note_passes(self):
        from llm import extract as E
        best = {"total": "840.00", "currency": "EUR", "airline": "Wayzata Air Cargo", "transit_days": 4}
        f = {"weight_kg_total": 150, "volume_cbm": 1.2, "language": "de", "origin": "MUC", "destination": "LAX"}
        body, reasons = E.final_reply("{HELLO}\n\nMUC nach LAX: {AIRLINE} zu {PRICE} all-in.\n\nAntworten Sie einfach kurz.", best, f, "k.weber@x.mail", 3)
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()
