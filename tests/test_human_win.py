"""The jury's +10 for the most human accepted mail: what llm/ adds on top of humanize/ (Riky).

  variety   two requests do not read the same: own mails (opening x closing), and the shape card in the one gateway call
  mirror    the customer's personal line is answered ("have a lovely day!" -> "Have a lovely day too!")
  greeting  never the company name, in the quote and in the booking mails
  gate      llm/quality.py still passes our texts and still stops invented facts and machine phrases
  language  every text of ours is in the customer's language, the expert note too
"""
import json, os, tempfile, unittest
from unittest import mock

from booking import replies
from llm import extract as llm, human, lang as langmod, quality

BEST = {"total": "1500.00", "currency": "EUR", "airline": "Meridian Freightways", "transit_days": 2}
PETRA = ("Hi there,\n\nHope your week's going well! We'll deliver 6 pieces of precision instruments, 102 kg and 0.49 cbm, to "
         "Frankfurt airport (FRA) ourselves, ready on 2026-11-28. Could you send me the cheapest all-in price in EUR to DOH?\n\n"
         "Thanks a lot and have a lovely day!\nPetra Hofmann\nExport Desk, Hofmann Textilwerk KG")
TOBIAS = ("Hello,\n\nCould you please quote your cheapest air freight option to SGN? 11 pieces, 572 kg, 2.29 cbm, ready "
          "on 2026-11-30.\n\nBest greetings from Regensburg\nTobias Auer\nVersand / Shipping\nAuer Maschinenbau GmbH\n\n\n"
          "-----Original Message-----\nSent: 2026-10-25\nSubject: AMSTERDAM - HKG\n\nDear team,\n\npls quote.\n\nRegards\nMei Lin")
SARA = "Hi,\n\nCould you quote your cheapest air freight option to EZE, 1805 kg, 6.92 cbm?\n\nSara\nLindqvist Medtech"


def fields_for(body, sender, language="en", **more):
    f = {"origin": "FRA", "destination": "DOH", "weight_kg": 300, "language": language}
    f.update(more)
    return llm._annotate(f, {"subject": "Air freight quote", "body": body, "sender": sender}, language)


def parts(body):
    """(greeting, first sentence, closing line) of a finished mail."""
    paras = body.split("\n\n")
    return paras[0], paras[1].split(". ")[0], paras[-2]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patches = [mock.patch.object(human, "STATE", os.path.join(self.tmp, "h.json")),
                        mock.patch.object(human, "HUMAN_STYLE", "")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def own(self, tid, lg="en", customer="anna.schmidt@x.mail", **more):
        f = dict({"origin": "MUC", "destination": "JFK", "weight_kg": 300, "language": lg}, **more)
        with mock.patch.object(human, "HUMAN_STYLE", "control"):           # our own mail, no extra line
            return llm.final_reply("", BEST, f, customer, tid)[0]


class Variety(Base):
    def test_own_mails_two_requests_differ(self):
        a, b = parts(self.own(4130)), parts(self.own(4366))                # two real requests of the same customer
        self.assertNotEqual(a[1], b[1], "same opening")
        self.assertNotEqual(a[2], b[2], "same closing")

    def test_own_mails_use_every_opening_and_closing(self):
        for lg in llm.OPENING:
            seen = [parts(self.own(t, lg)) for t in range(60)]
            self.assertEqual(len({s[1] for s in seen}), len(llm.OPENING[lg]), lg)
            self.assertEqual(len({s[2] for s in seen}), len(llm.CLOSING[lg]), lg)
            most = max(sum(1 for s in seen if s[2] == c) for c in {s[2] for s in seen})
            self.assertLess(most, 40, "%s: one closing line in most mails" % lg)      # not always "just reply and I'll book it"
        self.assertEqual(self.own(77), self.own(77))                       # same thread, same mail (replay stays stable)

    def test_shape_card_rotates(self):
        cards = {human.style_card(t) for t in range(200)}
        self.assertEqual(len(cards), len(human.CARD_OPEN) * len(human.CARD_CLOSE))
        self.assertNotEqual(human.card_index(4130), human.card_index(4366))
        self.assertEqual(human.style_card(5), human.style_card(5))

    def call(self, voice):
        seen = []

        def api(method, path, body=None, **kw):
            seen.append(body)
            return 200, {"choices": [{"message": {"content": json.dumps(
                {"language": "en", "reply": "Hi Sara,\n\n{AIRLINE} can do {PRICE} all-in, {TRANSIT_DAYS} days.\n\nShall I book it?"})}}]}
        mail = {"id": 9, "thread_id": 4130, "sender": "lindqvist-medtech@hackloop.mail", "subject": "Quote", "body": SARA}
        with mock.patch.object(llm.mailbox, "api", api), mock.patch.object(llm.config, "LLM_FAKE", False), \
                mock.patch.object(llm, "HUMAN_VOICE", voice):
            llm.extract(mail)
        return seen

    def test_card_rides_in_the_one_gateway_call(self):
        seen = self.call(True)
        self.assertEqual(len(seen), 1)                                     # exactly one call per quote
        self.assertEqual(seen[0]["messages"][0]["content"], llm.SYSTEM)
        self.assertEqual(len(seen[0]["messages"]), 2)
        self.assertIn(human.style_card(4130), seen[0]["messages"][1]["content"])
        self.assertLess(max(len(human.style_card(t)) for t in range(50)), 600)   # about 120 tokens, not a second prompt

    def test_flag_off_is_the_old_prompt(self):
        seen = self.call(False)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["messages"][0]["content"], llm.SYSTEM_V1)
        self.assertNotIn("Shape of this reply", seen[0]["messages"][1]["content"])
        self.assertIn("Just reply and I'll book it", llm.SYSTEM_V1)
        self.assertNotIn("Just reply and I'll book it", llm.VOICE)         # the line every mail of ours ended with


class Mirror(Base):
    TPL = "Hi Petra,\n\n{AIRLINE} is the cheapest to Doha right now: {PRICE} all-in, about {TRANSIT_DAYS} days.\n\nShall I book it?"

    def test_their_wish_is_answered(self):
        f = fields_for(PETRA, "hofmann-textilwerk@hackloop.mail")
        self.assertEqual(f["personal_cues"], {"well": "week", "wish": ["lovely day", "!"]})
        body, why = llm.final_reply(self.TPL, BEST, f, "hofmann-textilwerk@hackloop.mail", 2822)
        self.assertEqual(why, [])
        self.assertEqual(f["human_style"], "mirror")
        self.assertRegex(body.split("\n\n")[1], r"^[A-Z][^.]*\bweek\b[^.]*\. Meridian Freightways is the cheapest")
        self.assertIn("\n\nHave a lovely day too!\n\n", body)
        self.assertEqual(quality.check(body, "en", BEST, f, "hofmann-textilwerk@hackloop.mail", llm.SIGNER), [])

    def test_greetings_from_their_town_go_back_in_the_sign_off(self):
        f = fields_for(TOBIAS, "auer-maschinenbau@hackloop.mail")
        self.assertEqual(f["personal_cues"], {"town": "Regensburg"})
        body, why = llm.final_reply(self.TPL.replace("Petra", "Tobias"), BEST, f, "auer-maschinenbau@hackloop.mail", 3630)
        self.assertEqual(why, [])
        sign = body.split("\n")[-3:]
        self.assertRegex(sign[0], r"^(Best regards to|Greetings back to|Kind regards to) Regensburg$")
        self.assertEqual(sign[1:], [llm.SIGNER, "Air Export"])

    def test_nothing_personal_nothing_added(self):
        f = fields_for(SARA, "lindqvist-medtech@hackloop.mail")
        self.assertEqual(f["personal_cues"], {})
        with mock.patch.object(human, "HUMAN_STYLE", "control"):
            body, _ = llm.final_reply(self.TPL.replace("Petra", "Sara"), BEST, f, "lindqvist-medtech@hackloop.mail", 4130)
        self.assertEqual(body.count("\n\n"), 3)                            # greeting, text, closing, signature
        self.assertNotIn("too", body)

    def test_not_doubled_when_the_model_already_said_it(self):
        f = fields_for(PETRA, "hofmann-textilwerk@hackloop.mail")
        tpl = ("Hi Petra,\n\nAll fine here, I hope your week is good as well. {AIRLINE}: {PRICE} all-in, {TRANSIT_DAYS} days."
               "\n\nShall I book it? Have a lovely day too.")
        body, _ = llm.final_reply(tpl, BEST, f, "hofmann-textilwerk@hackloop.mail", 2822)
        self.assertEqual(body.lower().count("hope"), 1)
        self.assertEqual(body.lower().count("lovely day"), 1)

    def test_flag_off_no_mirror(self):
        f = fields_for(PETRA, "hofmann-textilwerk@hackloop.mail")
        with mock.patch.object(llm, "HUMAN_VOICE", False), mock.patch.object(human, "HUMAN_STYLE", "control"):
            body, _ = llm.final_reply(self.TPL, BEST, f, "hofmann-textilwerk@hackloop.mail", 2822)
        self.assertNotIn("lovely day", body)

    def test_other_languages(self):
        cases = {
            "de": ("Guten Tag,\n\nich hoffe, es geht Ihnen gut. Bitte um Ihr Angebot für 300 kg nach New York.\n\nIhnen noch einen "
                   "schönen Tag!\n\nMit freundlichen Grüßen aus Esslingen\nKatharina Brandt\nBrandt Präzision GmbH",
                   ("ich hoffe, bei Ihnen", "Ihnen auch einen schönen Tag!", "nach Esslingen")),
            "it": ("Buongiorno,\n\nabbiamo bisogno di una quotazione per 300 kg da Monaco a New York, grazie.\n\nGrazie mille e "
                   "buona giornata!\n\nGiulia Ferrari\nFerrari Tessuti", ("Buona giornata anche a voi!",)),
            "fr": ("Bonjour,\n\nj'espère que vous allez bien. Nous avons besoin d'un devis pour 300 kg de Munich à New York.\n\n"
                   "Merci et bonne journée\n\nClaire Morel\nMorel Textiles", ("j'espère que vous aussi", "Bonne journée à vous aussi.")),
            "es": ("Hola,\n\nespero que estén bien. Necesitamos una cotización para 300 kg desde Múnich a Nueva York, por favor."
                   "\n\nGracias y buen día\n\nAna Ruiz\nRuiz Textil", ("espero que ustedes también", "Igualmente, buen día.")),
        }
        for lg, (mail, expected) in cases.items():
            f = fields_for(mail, "kunde-firma@hackloop.mail", lg, origin="MUC", destination="JFK")
            body, why = llm.final_reply("", BEST, f, "kunde-firma@hackloop.mail", 11)
            self.assertEqual(why, [], body)
            for text in expected:
                self.assertIn(text, body, lg)
            self.assertEqual(quality.check(body, lg, BEST, f, "kunde-firma@hackloop.mail", llm.SIGNER), [], body)
            self.assertIn(langmod.detect(body), (lg, None), body)


class Greeting(Base):
    def test_never_the_company_name_in_the_quote(self):
        for mail, sender, name in ((TOBIAS, "auer-maschinenbau@hackloop.mail", "Tobias"),
                                   (SARA, "lindqvist-medtech@hackloop.mail", "Sara"),
                                   (PETRA, "hofmann-textilwerk@hackloop.mail", "Petra")):
            f = fields_for(mail, sender)
            self.assertEqual(f["customer_first_name"], name)               # the forwarded "Mei Lin" below is not theirs
            for tpl in ("", "Hi there,\n\n{AIRLINE}: {PRICE} all-in, {TRANSIT_DAYS} days.\n\nShall I book it?"):
                body, _ = llm.final_reply(tpl, BEST, f, sender, 3630)
                company = sender.split("-")[0].capitalize()
                self.assertNotRegex(body.split("\n")[0], r"\b%s\b" % company, body)
            self.assertTrue(llm.final_reply("", BEST, f, sender, 3630)[0].startswith("Hi %s," % name))

    def test_no_name_signed_no_name_guessed(self):
        f = fields_for("Hello,\n\nplease quote 300 kg FRA to DOH.\n\nThanks", "auer-maschinenbau@hackloop.mail")
        self.assertTrue(llm.final_reply("", BEST, f, "auer-maschinenbau@hackloop.mail", 1)[0].startswith("Hello,\n"))
        self.assertIsNone(replies.first_name("auer-maschinenbau@hackloop.mail"))
        self.assertEqual(replies.first_name("anna.schmidt@x.mail"), "Anna")

    def test_booking_mails_never_greet_the_company(self):
        v = {"ROUTE": "CGN to SGN", "AIRLINE": "Lumen Air Cargo", "PRICE": "2358.88 EUR", "REF": "BK-1", "TRANSIT": 4}
        for kind in ("booked", "confirmed"):
            for tid in range(900100, 900112):
                text = replies.render(kind, "en", v, thread_id=tid, customer="lindqvist-medtech@hackloop.mail")[0]
                self.assertNotIn("Lindqvist", text.split("\n")[0], text)

    def test_model_forgot_the_greeting(self):
        f = fields_for(SARA, "lindqvist-medtech@hackloop.mail")
        body, why = llm.final_reply("I've checked your lane to Buenos Aires. {AIRLINE} is the cheapest at {PRICE} all-in, "
                                    "{TRANSIT_DAYS} days.\n\nShall I book it?", BEST, f, "lindqvist-medtech@hackloop.mail", 5)
        self.assertEqual(why, [])
        self.assertTrue(body.startswith("Hi Sara,\n\nI've checked your lane"), body)

    def test_first_word_after_the_greeting(self):
        self.assertEqual(human.polish("Hi Sara,\n\nfor your crates we can do it.", "en").split("\n")[2][:3], "For")
        self.assertEqual(human.polish("Hallo Katrin,\n\nFür Ihre Kisten passt das.", "de").split("\n")[2][:3], "für")
        self.assertEqual(human.polish("Hallo Katrin,\n\nIhre Kisten fliegen mit.", "de").split("\n")[2][:4], "Ihre")   # polite form stays


class Gate(Base):
    def test_every_own_mail_passes_in_every_language(self):
        for lg in llm.HUMAN:
            for tid in range(40):
                f = {"origin": "MUC", "destination": "JFK", "weight_kg": 1805, "volume_cbm": 12.5, "language": lg}
                body, why = llm.final_reply("", dict(BEST, billed_kg="2088"), f, "anna.schmidt@x.mail", tid)
                self.assertEqual(why, [])
                self.assertEqual(quality.check(body, lg, BEST, f, "", llm.SIGNER, ["anna", "schmidt"]), [], body)
                self.assertNotIn("{", body)
                self.assertIn(langmod.detect(body), (lg, None), body)
                self.assertLessEqual(len(body.split()), 90)

    def test_expert_note_in_the_customers_language(self):
        f = {"weight_kg_total": 874, "volume_cbm_total": 2.77}
        self.assertIn("anziché 874 kg", llm.expert_note(dict(BEST, billed_kg="1000"), f, "it"))
        self.assertIn("au lieu de 874 kg", llm.expert_note(dict(BEST, billed_kg="1000"), f, "fr"))
        self.assertIn("en lugar de 874 kg", llm.expert_note(dict(BEST, billed_kg="1000"), f, "es"))
        self.assertIn("billed it at 1,000 kg rather than 874 kg", llm.expert_note(dict(BEST, billed_kg="1000"), f, "en"))
        bulky = {"weight_kg_total": 120, "volume_cbm_total": 2.0}
        self.assertIn("(2,00 cbm)", llm.expert_note(dict(BEST, billed_kg="334"), bulky, "fr"))
        for lg in ("it", "fr", "es"):
            for fx, billed in ((f, "1000"), (bulky, "334")):
                self.assertIn(langmod.detect(llm.expert_note(dict(BEST, billed_kg=billed), fx, lg)), (lg, None))

    def test_guarantees_are_kept(self):
        f = fields_for(SARA, "lindqvist-medtech@hackloop.mail")
        good = "Hi Sara,\n\n{AIRLINE} can take it for {PRICE} all-in, about {TRANSIT_DAYS} days.\n\nShall I book it?"
        self.assertEqual(llm.final_reply(good, BEST, f, "lindqvist-medtech@hackloop.mail", 1)[1], [])
        for bad, word in (("It has to be at the airport by 14:00.", "number"), ("Customs is included.", "cannot know"),
                          ("I hope this email finds you well.", "machine"), ("We are delighted to help.", "machine"),
                          ("Ready on the 29th is fine.", "number")):
            why = llm.final_reply(good.replace("\n\nShall", " " + bad + "\n\nShall"), BEST, f, "lindqvist-medtech@hackloop.mail", 1)[1]
            self.assertTrue(any(word in w for w in why), "%s -> %s" % (bad, why))

    def test_the_customers_own_date_is_not_an_invented_number(self):
        mail = "Guten Tag,\n\nbitte Angebot für 300 kg von Stuttgart nach Singapur, bereit ab 2026-12-02.\n\nKatharina Brandt"
        f = fields_for(mail, "brandt-praezision@hackloop.mail", "de", origin="STR", destination="SIN")
        tpl = ("Guten Tag Katharina,\n\n{AIRLINE} fliegt Ihre Sendung für {PRICE} all-in, Laufzeit rund {TRANSIT_DAYS} Tage. "
               "Den %s habe ich als Bereitstellung notiert.\n\nSoll ich buchen?")
        for said in ("2. Dezember", "02.12."):
            self.assertEqual(llm.final_reply(tpl % said, BEST, f, "brandt-praezision@hackloop.mail", 3)[1], [], said)
        self.assertTrue(llm.final_reply(tpl % "5. Dezember", BEST, f, "brandt-praezision@hackloop.mail", 3)[1])
        self.assertIsNone(quality.DENY.search("environ 4 jours de délai de transit"))
        self.assertIsNotNone(quality.DENY.search("livraison dans le délai prévu"))

    def test_their_own_delivery_can_be_said_back_but_not_invented(self):
        mail = ("Sehr geehrte Damen und Herren,\n\nbitte Angebot für 412 kg von Stuttgart nach Singapur. Die Ware steht ab dem "
                "02.12.2026 bereit, wir liefern selbst am Flughafen an.\n\nKatharina Brandt")
        f = fields_for(mail, "brandt-praezision@hackloop.mail", "de", origin="STR", destination="SIN")
        tpl = ("Guten Tag,\n\n{AIRLINE} fliegt Ihre Messgeräte für {PRICE} all-in, Laufzeit rund {TRANSIT_DAYS} Tage. %s\n\n"
               "Ein kurzes Ja genügt, dann buche ich.")
        said_back = tpl % "Ich habe notiert, dass Sie die Ware am 02.12.2026 selbst am Flughafen anliefern."
        body, why = llm.final_reply(said_back, BEST, f, "brandt-praezision@hackloop.mail", 3)
        self.assertEqual(why, [])
        self.assertTrue(body.startswith("Guten Tag Katharina,"), body)       # she signed with her name, the model wrote none
        ours = tpl % "Die Anlieferung muss bis 12 Uhr erfolgen."              # a time of ours: still stopped
        self.assertTrue(llm.final_reply(ours, BEST, f, "brandt-praezision@hackloop.mail", 3)[1])
        nobody = fields_for(mail.replace("wir liefern selbst am Flughafen an", "bitte bestätigen"),
                            "brandt-praezision@hackloop.mail", "de", origin="STR", destination="SIN")
        self.assertTrue(llm.final_reply(said_back, BEST, nobody, "brandt-praezision@hackloop.mail", 3)[1])   # they never said it

    def test_pickup_is_ours_and_no_direct_flight(self):
        mail = "Hi,\n\nsorry for the rush: 9 crates, 2380 kg, pickup at our plant in 90411 Nuremberg please, fastest to ORD.\n\nKlaus"
        f = fields_for(mail, "weidner-spielwaren@hackloop.mail", pickup_postcode="90411", destination="ORD")
        tpl = "Hi,\n\n{AIRLINE} flies your crates for {PRICE} all-in, {TRANSIT_DAYS} days. %s\n\nShall I book it?"
        ok, why = llm.final_reply(tpl % "Our truck collects at your plant, that's in the price.", BEST, f,
                                  "weidner-spielwaren@hackloop.mail", 9)
        self.assertEqual(why, [])
        self.assertTrue(ok.startswith("Hi Klaus,\n\nNo "), ok)               # name added, the rush answered
        for bad in ("I've noted that you'll arrange pickup at your plant.", "It goes on a direct flight."):
            self.assertTrue(llm.final_reply(tpl % bad, BEST, f, "weidner-spielwaren@hackloop.mail", 9)[1], bad)

    def test_a_sentence_starting_with_thanks_is_not_cut_as_a_sign_off(self):
        body = llm._own_signature("Hi Sara,\n\nThanks, all good here.\nMeridian can do 1500.00 EUR.\n\nShall I book it?", "en", 1)
        self.assertIn("Thanks, all good here.", body)
        self.assertIn("Shall I book it?", body)
        cut = llm._own_signature("Hi Sara,\n\n1500.00 EUR.\n\nBest regards\nSara", "en", 1)             # a real sign-off still goes
        self.assertEqual(cut.count("Sara"), 1)


if __name__ == "__main__":
    unittest.main()
