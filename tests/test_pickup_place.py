"""5U, 22 Nov 11:03 (request 56806, rejected 'too low'): truck pickup wanted, the place came as a town only
("Sorry I left out the pickup location: Cologne, Germany."), so no trucker was asked and the flight alone was quoted.
core/pickup.py gives such a request the postcode of the town's area, and takes a postcode the model missed.
Run: python -m unittest tests.test_pickup_place -v"""
import json, os, tempfile, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main, pickup  # noqa: E402
from llm import clarify  # noqa: E402
from sourcing import bids  # noqa: E402

CUSTOMER = "pickup-desk@pickup-test.mail"                      # its own address: one DB for the whole suite
REQUEST = ("Hi,\n\nPlease quote the fastest air freight option to LIM, including truck pickup from our warehouse to the airport. The "
           "automotive sensors will be ready for pickup on 2026-11-30: 2 pieces, 633 kg gross, 2.73 cbm.\n\nMira Petersen\nNordlicht Audio")
ANSWER = "Sorry I left out the pickup location: Cologne, Germany.\n\nFor the other shipment details, please refer to my first email.\n\nMira Petersen\nNordlicht Audio"
OPTION = {"airline": "Nova Atlas Cargo", "airline_code": "NV", "origin": "CGN", "destination": "LIM", "transit_days": 3, "currency": "EUR",
          "total": "2620.62", "total_eur": "2620.62", "chargeable_kg": "633.0", "billed_kg": "633.0", "source": "portal", "rate_id": "R-test-lim"}


def fields(**more):
    f = {"origin": None, "destination": "LIM", "pickup_postcode": None, "weight_kg": 633, "volume_cbm": 2.73,
         "pieces": [{"count": 2, "l_cm": None, "w_cm": None, "h_cm": None, "kg_each": None}], "prefer": "fastest", "kind": "new_request",
         "language": "en", "missing": [], "shipments": [], "self_delivery": False,
         "reply": "Hi Mira,\n\n{PRICE} with {AIRLINE}, {TRANSIT_DAYS} days.\n\nLena"}
    f.update(more)
    return f


def mail(id, body, subject="Air freight quote to LIM", refs=None):
    return main.mailbox.normalize({"id": id, "from": CUSTOMER, "subject": subject, "body": body,
                                   "references": refs or [], "in_reply_to": refs[-1] if refs else None})


def truckers(tid):
    return sorted(b["carrier"] for b in bids.rows(tid) if b["role"] == "trucker")


class Place(unittest.TestCase):
    def test_the_town_in_a_sentence_about_the_pickup(self):
        self.assertEqual(pickup.place(ANSWER), (None, "Cologne", "50"))
        self.assertEqual(pickup.place("Hello,\n\nSorry I left out the pickup location. The goods are in Augsburg, Germany."), (None, "Augsburg", "86"))
        self.assertEqual(pickup.place("Abholung bitte bei uns im Lager in Köln."), (None, "Cologne", "50"))
        self.assertEqual(pickup.place("Please collect at our site in Munich South."), (None, "Munich South", "81"))
        self.assertEqual(pickup.place("The pickup address is Frankfurt, Germany."), (None, "Frankfurt am Main", "60"))

    def test_a_postcode_wins_over_the_town(self):
        self.assertEqual(pickup.place("Sorry I left out the pickup location: 51115 Bergisch Gladbach, Germany."), ("51115", "Bergisch Gladbach", "51"))
        self.assertEqual(pickup.place("Please collect the goods at 50380."), ("50380", "Cologne", "50"))

    def test_a_town_elsewhere_is_not_the_pickup_place(self):
        for text in ("Best greetings from Regensburg\nTobias Auer", "Weidner Spielwaren GmbH, Nuremberg", "We fly to Hamburg often.",
                     "Our buyer in Munich is waiting.", "Ready for pickup on 2026-11-30: 2 pieces, 633 kg gross, 2.73 cbm.",
                     "The pickup is at our warehouse in Paris."):
            self.assertIsNone(pickup.place(text), text)


class Priced(unittest.TestCase):
    def test_town_only_after_our_question_gets_the_truck(self):
        """The live case: no place, we ask, 'Cologne, Germany', the model returns CGN and no postcode."""
        tid = 970117
        with mock.patch.object(main.llm, "extract", return_value=(fields(), {"fake": True})), mock.patch("sourcing.portal.options", return_value=[dict(OPTION)]):
            main.process(mail(tid, REQUEST))
        self.assertEqual(db.session(tid)["status"], "asked_customer")
        self.assertEqual(truckers(tid), [])
        with mock.patch.object(clarify, "_merge_call", return_value=("provides_info", {"origin": "CGN"}, {})), \
                mock.patch("sourcing.portal.options", return_value=[dict(OPTION)]):
            main.process(mail(tid + 1, ANSWER, "Re: Air freight quote to LIM", refs=[tid]))
        s = db.session(tid)
        f = json.loads(s["fields"])
        self.assertEqual((f["pickup_postcode"], f["pickup_area"], f["origin"]), ("50000", "Cologne", "CGN"))
        self.assertEqual(s["status"], "waiting_bids", s["note"])                # it waits for the truckers now
        self.assertEqual(truckers(tid), sorted(c["name"] for c in bids.serving("trucker", "50")))
        self.assertTrue(len(truckers(tid)) >= 3)
        asked = [json.loads(r["data"]) for r in db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind LIKE 'bid_mail_out%'", (tid,))]
        self.assertTrue(any("postcode 50000" in (a.get("body") or "") or "50000" in (a.get("subject") or "") for a in asked), asked[:1])
        e = json.loads(db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind='pickup_place'", (tid,)).fetchone()["data"])
        self.assertEqual((e["area"], e["given"]), ("Cologne", "town"))

    def test_town_in_the_first_mail(self):
        tid = 970218
        body = REQUEST.replace("from our warehouse to the airport", "from our warehouse in Augsburg, Germany, to the airport")
        with mock.patch.object(main.llm, "extract", return_value=(fields(origin="MUC"), {"fake": True})), \
                mock.patch("sourcing.portal.options", return_value=[dict(OPTION, origin="MUC")]):
            main.process(mail(tid, body))
        f = json.loads(db.session(tid)["fields"])
        self.assertEqual((f["pickup_postcode"], f["pickup_area"]), ("86000", "Augsburg"))
        self.assertEqual(truckers(tid), sorted(c["name"] for c in bids.serving("trucker", "86")))

    def test_the_other_way_round_only_a_postcode(self):
        """A postcode and nothing else: the airport comes from the postcode area, and the truckers of that area are asked,
        also when the model did not put the postcode into its form."""
        tid = 970319
        body = REQUEST.replace("from our warehouse to the airport", "from our warehouse to the airport. Please collect the goods at 50380")
        with mock.patch.object(main.llm, "extract", return_value=(fields(), {"fake": True})), mock.patch("sourcing.portal.options", return_value=[dict(OPTION)]):
            main.process(mail(tid, body))
        s = db.session(tid)
        f = json.loads(s["fields"])
        self.assertEqual((f["pickup_postcode"], f["origin"], f.get("pickup_area")), ("50380", "CGN", None))
        self.assertEqual(s["status"], "waiting_bids", s["note"])
        self.assertEqual(truckers(tid), sorted(c["name"] for c in bids.serving("trucker", "50")))

    def test_delivering_to_the_airport_themselves_is_no_pickup(self):
        """Requests 1631, 2822 and 7240, live: a town, the word pickup, and no truck wanted."""
        for body in ("The cargo will be ready for pickup on 2026-11-29, and we will deliver it to Munich airport (MUC) ourselves.",
                     "We\u2019ll deliver the goods to Frankfurt airport (FRA) ourselves, so there\u2019s no pickup needed.",
                     "We\u2019ll deliver the textile samples to Cologne airport (CGN) ourselves, so there\u2019s no need to arrange pickup."):
            self.assertIsNone(pickup.place(body), body)                          # "Munich airport" is not a pickup town
            self.assertTrue(pickup.OWN_DELIVERY.search(body), body)
        tid = 970521
        m = mail(tid, "Please quote MUC to LIM, 633 kg, 2.73 cbm. The cargo will be ready for pickup at our Munich site on 2026-11-29, "
                      "and we will deliver it to the airport ourselves.")
        with mock.patch.object(main.llm, "extract", return_value=(fields(origin="MUC"), {"fake": True})), \
                mock.patch("sourcing.portal.options", return_value=[dict(OPTION, origin="MUC")]):
            main.process(m)
        self.assertIsNone(json.loads(db.session(tid)["fields"]).get("pickup_postcode"))
        self.assertEqual(truckers(tid), [])

    def test_no_pickup_wanted_or_own_delivery_changes_nothing(self):
        f = fields(origin="CGN", self_delivery=True)
        tid = 970420
        m = mail(tid, "Please quote CGN to LIM, 633 kg, 2.73 cbm. We deliver to the airport ourselves from our warehouse in Cologne.")
        with mock.patch.object(main.llm, "extract", return_value=(f, {"fake": True})), mock.patch("sourcing.portal.options", return_value=[dict(OPTION)]):
            main.process(m)
        self.assertIsNone(json.loads(db.session(tid)["fields"]).get("pickup_postcode"))
        self.assertEqual(truckers(tid), [])


if __name__ == "__main__":
    unittest.main()
