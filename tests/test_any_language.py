"""5U, 21 Nov 23:00: the reply must be in the customer's language, whatever it is.

Live, round 72 (thr 20153): a request in Chinese with the sign-off "Thanks a lot and have a lovely day!" was counted
as English, answered in English, and rejected (wrong_language). The customer's "so we won\u2019t go ahead" was then
read as a yes and booked, and "Cologne, Germany" was taken for perfume.
"""
import json, os, tempfile, time, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import config, db, mailbox  # noqa: E402
from booking import handlers  # noqa: E402
from dg import quote  # noqa: E402
from llm import lang, translate  # noqa: E402

ZH = ("您好，\n\n希望您这周过得顺利！想请您帮忙看看一票发往 LIM（Lima, PE）的空运。这票货我们想走最便宜的方案。\n\n货物是汽车传感器，"
      "共 11 件，毛重 704 kg，体积 3.08 cbm。2026-11-23 可以提货，提货地点是我们在 Cologne, Germany 的场地，邮编 50978。"
      "麻烦您安排卡车上门提货并送到机场。\n\n能否请您报一个包含上门提货和空运的 EUR 全包价？谢谢！\n\n"
      "Thanks a lot and have a lovely day!\nPetra Hofmann\nExport Desk, Hofmann Textilwerk KG")
EN = "Hi Petra,\n\nThe all-in price is 2353.76 EUR with Xenon Cargo Airlines, about 4 days.\n\nBest regards\nLena Hofmann"


class Detect(unittest.TestCase):
    def test_the_script_of_the_mail_beats_an_english_sign_off(self):
        self.assertEqual(lang.detect(ZH), "zh")
        self.assertEqual(lang.detect("お世話になっております。フランクフルトから成田まで200 kgの見積もりをお願いします。Thanks and best regards"), "ja")
        self.assertEqual(lang.detect("안녕하세요. 프랑크푸르트에서 인천까지 200 kg 견적 부탁드립니다. Thanks and best regards"), "ko")

    def test_cyrillic_or_arabic_is_left_to_the_model(self):
        self.assertIsNone(lang.detect("Здравствуйте, просим предложить самый дешевый вариант авиаперевозки 200 кг из Франкфурта. Thanks and regards to you"))

    def test_our_five_languages_are_unchanged(self):
        self.assertEqual(lang.detect("Hello, could you please quote the cheapest option for our shipment to JFK? Thanks"), "en")
        self.assertEqual(lang.detect("Guten Tag, bitte bieten Sie uns die günstigste Luftfrachtoption nach RUH an. Vielen Dank."), "de")
        self.assertEqual(lang.detect("Bonjour, pouvez-vous nous communiquer votre tarif pour un envoi vers Sydney ? Merci"), "fr")

    def test_another_latin_language_with_an_english_sign_off_is_not_english(self):
        nl = ("Goedemiddag, graag ontvangen wij uw scherpste prijs voor luchtvracht naar Singapore. Het gaat om twaalf dozen "
              "onderdelen, brutogewicht 300 kg, volume 1.2 cbm, ophalen bij ons magazijn in Keulen op woensdag. Alvast "
              "bedankt voor uw offerte en de snelle reactie.\n\nThanks and have a lovely day!\nJan")
        self.assertIsNone(lang.detect(nl))                       # not sure: the model names the language

    def test_which_languages_need_a_translation(self):
        self.assertTrue(translate.needed("zh")); self.assertTrue(translate.needed("nl"))
        for own in ("en", "de", "fr", "it", "es", "", None):
            self.assertFalse(translate.needed(own))


class Amounts(unittest.TestCase):
    def test_the_quoted_amount_comes_back_exactly(self):
        self.assertEqual(translate.restore_amounts("De prijs is 2.353,76 EUR.", EN), "De prijs is 2353.76 EUR.")
        self.assertEqual(translate.restore_amounts("Cena: 2 353,76 EUR", EN), "Cena: 2353.76 EUR")
        self.assertEqual(translate.restore_amounts("价格为 2353.76 EUR", EN), "价格为 2353.76 EUR")


class SendTime(unittest.TestCase):
    def session(self, tid, language):
        db.con().execute("DELETE FROM sessions WHERE thread_id=?", (tid,))
        db.con().execute("INSERT INTO sessions(thread_id, customer, subject, status, fields, received_at) VALUES(?,?,?,?,?,?)",
                         (tid, "petra@hofmann.mail", "Quote", "quoted", json.dumps({"language": language}), time.time()))
        db.con().commit()

    def test_a_chinese_customer_gets_the_translated_mail(self):
        self.session(8830001, "zh")
        with mock.patch.object(translate, "to", return_value=("嗨 Petra，全包价格为 2353.76 EUR。", 0.0001)):
            body = mailbox.in_customer_language("petra@hofmann.mail", EN, 8830001)
        self.assertIn("2353.76 EUR", body); self.assertIn("全包价格", body)
        ev = db.con().execute("SELECT data FROM events WHERE kind='translated' AND thread_id=8830001").fetchone()
        self.assertEqual(json.loads(ev["data"])["english"], EN)                  # what we meant stays in the log

    def test_own_languages_carriers_and_failures_go_out_unchanged(self):
        self.session(8830002, "de")
        with mock.patch.object(translate, "to", side_effect=AssertionError("must not be called")):
            self.assertEqual(mailbox.in_customer_language("petra@hofmann.mail", EN, 8830002), EN)
        self.session(8830003, "zh")
        with mock.patch.object(translate, "to", side_effect=AssertionError("must not be called")):
            self.assertEqual(mailbox.in_customer_language("xenon@hackloop.mail", EN, 8830003), EN)          # an airline
            self.assertEqual(mailbox.in_customer_language("petra@hofmann.mail", EN, 8830003, "bid_mail_out"), EN)
        with mock.patch.object(translate, "to", return_value=(None, "gateway 503")):
            self.assertEqual(mailbox.in_customer_language("petra@hofmann.mail", EN, 8830003), EN)           # English, as before

    def test_no_gateway_in_tests(self):
        self.assertEqual(translate.to(EN, "zh")[0], None)                        # LLM_FAKE: never a call


class SameThread(unittest.TestCase):
    def test_a_typographic_apostrophe_does_not_turn_no_into_yes(self):
        said = ("Thank you for your reply. It wasn\u2019t in the language I wrote to you in, and I couldn\u2019t follow it, "
                "so we won\u2019t go ahead.")
        self.assertEqual(handlers.classify(said), "decline")
        self.assertEqual(handlers.classify("Great, please go ahead and book it."), "accept")

    def test_cologne_the_city_is_not_perfume(self):
        self.assertIsNone(quote.infer_commodity_dg(ZH))
        self.assertIsNone(quote.infer_commodity_dg("Automotive sensors, 11 pieces. Pickup at our site in Cologne, Germany (50978)."))
        self.assertTrue(quote.infer_commodity_dg("We ship 40 cartons of Eau de Cologne."))
        self.assertTrue(quote.infer_commodity_dg("200 bottles of cologne and aftershave, 300 kg"))


if __name__ == "__main__":
    unittest.main()
