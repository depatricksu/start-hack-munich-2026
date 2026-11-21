"""A request in one language on top of a forwarded/quoted chain in another: the request's language wins.
Run: python -m unittest tests.test_lang_own_text -v"""
import os, tempfile, unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")

from llm import extract as x  # noqa: E402

EN_CHAIN = ("\n\n-----Original Message-----\nFrom: john@x.com\nSubject: shipment\n\nHello team, could you please send us "
            "the price for the shipment we discussed last week? We need it soon and would like to know the cheapest "
            "option. Thanks and best regards, John")


def mail(body, subject="Anfrage"):
    return {"subject": subject, "body": body}


class OwnText(unittest.TestCase):
    def test_german_on_top_of_english_chain(self):
        b = "Hallo,\n\nbitte um ein Angebot für 300 kg von München nach JFK, die günstigste Option.\n\nViele Grüße\nAnna" + EN_CHAIN
        self.assertEqual(x.detect_lang(mail(b)), "de")

    def test_italian_on_top_of_quoted_english(self):
        b = ("Buongiorno,\n\nvorremmo un preventivo per 300 kg da Milano a JFK, grazie.\n\nCordiali saluti\nGiulia\n\n"
             "> On Monday John wrote:\n> Hello, could you please send the price for the shipment, we need it soon and "
             "would like the cheapest option, thanks and kind regards")
        self.assertEqual(x.detect_lang(mail(b, "Richiesta")), "it")

    def test_english_with_german_signoff_stays_english(self):
        b = "Hello,\n\ncould you please quote 300 kg MUC to JFK, cheapest option?\n\nMit freundlichen Grüßen\nAnna Schmidt"
        self.assertEqual(x.detect_lang(mail(b, "Quote")), "en")

    def test_too_short_own_text_falls_back_to_whole_mail(self):
        b = "FRA JFK 200 kg" + EN_CHAIN                           # own words say nothing: old behaviour
        self.assertEqual(x.detect_lang(mail(b, "")), "en")

    def test_attached_file_text_is_kept(self):
        b = ("Hello, please find our request attached.\n\n[Files attached to this email, as text. They are part of the "
             "request.]\n--- attached file: anfrage.pdf ---\nSehr geehrte Damen und Herren, wir benötigen ein Angebot "
             "für die günstigste Sendung von München nach JFK, 300 kg. Mit freundlichen Grüßen")
        self.assertEqual(x.detect_lang(mail(b, "")), "de")


if __name__ == "__main__":
    unittest.main()
