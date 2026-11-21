"""Red-team tables (#47): sentences a real customer or 5U could send, checked against three plain rules.

    booking.handlers.classify(body)   customer reply to our quote -> accept/decline/better_price/faster/sending_docs/unclear
    router.route.route(mail)          new mail -> rfq or spam
    dg.quote.read_declaration(text)   commodity line -> DG found (dict) or not (None)

Each table has rows the clerk gets RIGHT (asserted) and a KNOWN_WRONG list with what a sensible forwarder wants,
the issue number and what the clerk says today. KNOWN_WRONG rows assert that the clerk is STILL wrong: when a rule
fix makes one pass, that test fails on purpose, so move the row up into the main table. No rule is changed here.
Run: python3 -m unittest tests.test_redteam_tables -v
"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from booking.handlers import classify  # noqa: E402
from router.route import route  # noqa: E402
from dg.quote import read_declaration  # noqa: E402

# Our quote, quoted under/over the customer's words (Gmail style).
QUOTED = ("On Sat, 21 Nov 2026 at 16:05, Google Forwarding <google@hackloop.mail> wrote:\n"
          "> Dear Anna, our price for 90 kg HAM to BOG is EUR 1,240 with Lufthansa, 3 days.\n> Best regards\n")
LONG_YES = ("Thanks for the detailed breakdown. We reviewed it with our logistics team and our finance department and "
            "compared it with the rates we had last quarter on the same lane. Everything is in order on our side. "
            "Please book it.")
LONG_YES_WITH_BUT = ("Thanks for the detailed breakdown. Last time the shipment was delayed in Bogota but your team "
                     "handled it well, and our finance department has compared your offer with the rates we had last "
                     "quarter on the same lane. Everything is in order on our side. Please go ahead.")

# ---------------------------------------------------------------- 1. customer replies (40 = 26 right + 14 known wrong)
REPLIES = [
    ("Yes please, book it.", "accept"),
    ("Thank you for the quick offer. Unfortunately we will not proceed.", "decline"),
    # A condition we must check first (can we make Friday?) is not a yes: a person decides.
    ("Only if you can do it by Friday.", "unclear"),
    # Wants another airline: we need a new option, not a booking. Not "decline" either: they still want to ship.
    ("Ok, but not with that airline.", "unclear"),
    ("Can you do it any cheaper? Our budget is tight.", "better_price"),
    ("Is there a faster option? We need it sooner.", "faster"),
    ("We will send the shipper's declaration and the MSDS tomorrow.", "sending_docs"),
    (LONG_YES, "accept"),                                          # yes after a long paragraph, no "but" in it
    (QUOTED + "\nYes, go ahead.", "accept"),                       # bottom-posted under our quoted mail
    ("Sounds good, but please wait until we have the final weight.", "unclear"),
    ("Not interested, thanks.", "decline"),
    # A yes with a new weight: the price changes, so we must not book the old quote.
    ("We accept the offer. Note the weight is now 420 kg.", "unclear"),
    ("Ja, bitte buchen.", "accept"),
    ("Vielen Dank, wir haben uns für einen anderen Anbieter entschieden.", "decline"),
    ("Geht das auch günstiger?", "better_price"),
    ("Wir brauchen es schneller, geht auch Express?", "faster"),
    ("Einverstanden, aber nur wenn die Ware bis Freitag in New York ist.", "unclear"),   # conditional yes
    ("Leider nein, danke.", "decline"),
    ("Va bene, procedete pure.", "accept"),
    ("Ci serve più veloce, avete un'opzione express?", "faster"),
    ("D'accord, vous pouvez réserver.", "accept"),
    ("Non merci, c'est trop cher pour nous.", "decline"),          # "too expensive" but a clear no: decline wins
    ("Oui, mais seulement si le vol part avant vendredi.", "unclear"),
    ("De acuerdo, pero no con esa aerolínea.", "unclear"),
    ("No gracias, ya lo hemos resuelto.", "decline"),
    ("¿Hay algo más barato?", "better_price"),
]

# (text, expected, what the clerk says today, issue)
REPLIES_KNOWN_WRONG = [
    # A bare "ok"/"Yes" in reply to a price is a yes in forwarding. Risky? The reply is to OUR quote, in thread, with
    # nothing else in it: a person would book it. Today it sits in needs_human and the time score runs out.
    ("ok", "accept", "unclear", 53),
    ("Yes", "accept", "unclear", 53),
    (QUOTED + "\nok", "accept", "unclear", 53),                     # bottom-posted "ok"
    ("Bitte um Buchung.", "accept", "unclear", 53),                 # "Buchung" is not "buchen"
    ("De acuerdo.", "accept", "unclear", 53),
    ("Sí, adelante.", "accept", "unclear", 53),
    # The "but" is in an old story, not in the answer: the answer is "Please go ahead."
    (LONG_YES_WITH_BUT, "accept", "unclear", 54),
    ("Thanks, but we decided to go with another forwarder this time.", "decline", "unclear", 55),
    ("Thanks a lot, we'll pass on this one.", "decline", "unclear", 55),
    # DANGEROUS: "we do not proceed" is booked ("procedi" matches inside "procediamo", no Italian negation).
    ("Grazie, ma non procediamo con questa offerta.", "decline", "accept", 56),
    ("È possibile avere un prezzo migliore?", "better_price", "unclear", 57),
    ("C'est un peu cher, vous pouvez faire mieux ?", "better_price", "unclear", 57),
    # A real yes, but DG papers follow: we must wait for them, not book now (5U rejects dg_docs_missing).
    ("Passt, das Sicherheitsdatenblatt schicken wir noch nach.", "sending_docs", "accept", 58),
    ("Nous vous envoyons la déclaration de l'expéditeur pour marchandises dangereuses.", "sending_docs", "unclear", 59),
]


# ---------------------------------------------------------------- 2. new mails (20 = 14 right + 6 known wrong)
def m(body, subject="Hello", sender="someone@x-example.mail"):
    return {"sender": sender, "subject": subject, "body": body, "attachments": [], "is_thread_start": True}


MAILS = [
    (m("Hi, I'm Laura from CargoBoost. Our platform helps forwarders win more freight quotes. Can I schedule a demo "
       "next week?", "Win more quotes"), "spam"),
    (m("Your 5U gateway access expires today. Reply with your API key to keep your account active.", "Action required"), "spam"),
    (m("Unser Newsletter im November: Neuigkeiten aus der Logistikbranche. Abmelden: unsubscribe", "Newsletter November"), "spam"),
    (m("Congratulations, you have won an iPhone 17! Claim your prize now.", "Winner!"), "spam"),
    (m("Please note our new bank details for the wire transfer of your last invoice.", "Updated bank details"), "spam"),
    (m("We offer SEO services and backlinks for logistics websites. Rank first on Google.", "Grow your traffic"), "spam"),
    (m("Start a free trial of our software, it already handles 2,000 shipments a day for forwarders like you.",
       "Automate your quotes"), "spam"),
    (m("Please quote 250 kg MUC to ORD. PS: please remove me from your newsletter.", "Quote MUC-ORD"), "rfq"),
    (m("Our IT asks whether you offer an API key for tracking. Anyway, we need a rate for 3 pallets FRA-DXB.",
       "Rate request"), "rfq"),
    (m("Good news, we won a new contract and need to ship 600 kg of machine parts from Stuttgart to Shanghai.",
       "New business"), "rfq"),
    (m("The winner of our tender gets the business: please send your best price for 1,000 kg FRA to NRT.", "Tender"), "rfq"),
    (m("Click here to download our packing list. Shipment: 2 crates, 180 kg, HAM to YYZ.", "Export HAM"), "rfq"),
    (m("Hola, necesitamos una cotización para 2 pallets de MAD a MIA. Para darse de baja del newsletter responda STOP.",
       "Cotización"), "rfq"),
    (m("Our sales team needs to send product samples, 15 kg, to our office in Chicago. Can you schedule a call?",
       "Samples to Chicago"), "rfq"),
]

MAILS_KNOWN_WRONG = [
    # Phishing / newsletter / crypto that use freight words: FREIGHT ("freight", "rate", "cargo") saves them from spam.
    # Not fatal (the gateway call reads them, then needs_human), but each costs a gateway call and a person's time.
    (m("Dear partner, to receive the new freight rates for 2027 please confirm your login details at "
       "http://rates-update.example", "New tariff 2027"), "spam", "rfq", 60),
    (m("Air Cargo Weekly: rates on Asia-Europe lanes climbed 4% this week. Read more on our site. Unsubscribe here.",
       "Air Cargo Weekly #47"), "spam", "rfq", 60),
    (m("Earn $3,000 a week with our freight-backed crypto token. Click here to join.", "Freight 2.0"), "spam", "rfq", 60),
    # A warehouse selling space: "5000 m3" looks like a shipment to SHIPMENT. Arguably "rfq when in doubt" is safe
    # here, but a forwarder never replies to this; judged spam.
    (m("We are a bonded warehouse at Frankfurt airport with 5000 m3 free space. Partnership opportunity? Our sales "
       "manager can call you.", "Warehouse space FRA"), "spam", "rfq", 61),
    # DANGEROUS: real requests dropped with no reply. "kilos" is not a unit to FREIGHT, "password" is a spam word.
    (m("Hi, our password-protected warehouse in Munich has 4 boxes ready for Toronto, about 60 kilos in total. "
       "Can you help?", "Boxes to Toronto"), "rfq", "spam", 62),
    # "newsletter" + no FREIGHT word ("fly", "engine", "ship" are not in it): a real request dropped.
    (m("Newsletter reader here: we need to fly a vehicle engine to Mexico City next week, can you help?",
       "Engine to Mexico"), "rfq", "spam", 63),
]

# ---------------------------------------------------------------- 3. dangerous goods (30 = 21 right + 9 known wrong)
DG = [
    ("Commodity: perfume, 120 bottles of eau de parfum", True),     # UN1266 class 3
    ("Power banks 10000 mAh, 200 pcs", True),                       # UN3480
    ("Spray paint cans, 48 cartons", True),                         # UN1950
    ("Water-based wall paint, 20 buckets", False),                  # not flammable: general cargo
    ("Nail polish, 500 bottles", True),                             # UN1263 class 3
    ("Biological samples packed in dry ice", True),                 # UN1845
    ("Lithium-free toy cars, 300 pcs", False),
    ("Battery holders (no cells), 500 pcs", False),
    ("Machine parts, steel, 3 crates", False),
    ("Maintenance spray cans. The goods are general cargo, non-dangerous.", True),   # 5U trap 2533: DG by nature
    ("Non-dangerous goods. Packing list: UN3481 lithium ion batteries packed with equipment", True),   # UN beats claim
    ("Paint thinner, non-dangerous, UN1993", True),
    ("Spraydosen, 40 Kartons", True),
    ("Trockeneis zur Kühlung der Proben", True),
    ("Lithium-Ionen-Akkus für E-Bikes, 2 Paletten", True),
    ("Ersatzteile für Maschinen, kein Gefahrgut", False),
    ("Gefahrgut: nein", False),
    ("Laptops with built-in lithium batteries, 40 pcs", True),      # UN3481 in equipment: still DG by air
    ("Empty aerosol cans (unfilled), 1000 pcs", False),
    ("Fragrance-free soap, 80 cartons", False),
    ("Alkaline AA batteries, 100 boxes", False),                    # not restricted (special provision A123)
]

DG_KNOWN_WRONG = [
    ("Commodity: eau de parfum in 50 ml glass bottles", True, False, 64),            # perfume without the word
    ("Solvent-based industrial paint, flash point 23 C, 12 drums", True, False, 65), # UN1263 class 3
    ("Farbe auf Lösemittelbasis, 8 Fässer", True, False, 65),                        # same, in German
    ("Parfüm, 30 Kartons", True, False, 66),                                         # German words missing
    ("Nagellack, 200 Flaschen", True, False, 66),
    ("Feuerzeuge, 10 Kartons", True, False, 66),                                     # lighters, UN1057
    ("Hand sanitizer gel, 70% alcohol, 60 cartons", True, False, 67),                # UN1170 class 3
    ("Car batteries, wet, filled with acid", True, False, 68),                       # UN2794 class 8
    # False positive: caps are plastic, no perfume in them. Asking for DG papers on general cargo costs the round.
    ("Perfume bottle caps, plastic, 5000 pcs", False, True, 69),
]


class TestReplies(unittest.TestCase):
    def test_right(self):
        for text, want in REPLIES:
            with self.subTest(text=text[-70:]):
                self.assertEqual(classify(text), want)

    def test_known_wrong_still_wrong(self):
        for text, want, now, issue in REPLIES_KNOWN_WRONG:
            with self.subTest(text=text[-70:], issue=issue):
                got = classify(text)
                self.assertNotEqual(got, want, "fixed (#%d): move this row into REPLIES" % issue)
                self.assertEqual(got, now)


class TestSpamRoute(unittest.TestCase):
    def test_right(self):
        for mail, want in MAILS:
            with self.subTest(body=mail["body"][:70]):
                self.assertEqual(route(mail), want)

    def test_known_wrong_still_wrong(self):
        for mail, want, now, issue in MAILS_KNOWN_WRONG:
            with self.subTest(body=mail["body"][:70], issue=issue):
                got = route(mail)
                self.assertNotEqual(got, want, "fixed (#%d): move this row into MAILS" % issue)
                self.assertEqual(got, now)


class TestDangerousGoods(unittest.TestCase):
    def test_right(self):
        for text, found in DG:
            with self.subTest(text=text):
                self.assertEqual(read_declaration(text) is not None, found, read_declaration(text))

    def test_known_wrong_still_wrong(self):
        for text, want, now, issue in DG_KNOWN_WRONG:
            with self.subTest(text=text, issue=issue):
                got = read_declaration(text) is not None
                self.assertNotEqual(got, want, "fixed (#%d): move this row into DG" % issue)
                self.assertEqual(got, now)

    def test_table_sizes(self):
        self.assertEqual(len(REPLIES) + len(REPLIES_KNOWN_WRONG), 40)
        self.assertEqual(len(MAILS) + len(MAILS_KNOWN_WRONG), 20)
        self.assertEqual(len(DG) + len(DG_KNOWN_WRONG), 30)


if __name__ == "__main__":
    unittest.main()
