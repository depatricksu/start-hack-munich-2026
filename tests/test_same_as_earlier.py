"""5U, 22 Nov 02:20 (round 103): 'quote the same shipment as in my earlier request ... new destination LAX'.
The details come from that earlier request of the same sender (core/recall.py)."""
import calendar, json, os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main, recall  # noqa: E402

ANNA = "anna@recall-test.mail"            # not a customer of any other test: all tests share one DB
T_MEL = calendar.timegm((2026, 11, 21, 23, 18, 53))
REAL = ("Hello,\n\nCould you please quote the same shipment as in my earlier request, \"Air freight quote request: STR to MEL\", sent on "
        "2026-11-21 at 23:18 UTC for destination MEL? The cargo and pickup details are unchanged, and you already have them from that request."
        "\n\nThe new destination is LAX, and the shipment will be ready for pickup on 2026-11-29. Please send me an all-in price in EUR for the "
        "cheapest option.\n\nThank you.\n\nKind regards\nAnna Sonnberg")


def earlier(tid, sender, subject, received, **fields):
    mail = {"id": tid, "thread_id": tid, "sender": sender, "subject": subject, "body": "x", "received_at": received, "raw": {}}
    db.save_mail(mail)
    db.new_session(mail)
    db.update_session(tid, fields=fields, status="lost")     # not a booking: the tracking tests must not see these


def new_mail(tid, body, sender=ANNA, subject="Air freight quote request to LAX"):
    return {"id": tid, "thread_id": tid, "sender": sender, "subject": subject, "body": body, "received_at": T_MEL + 7300, "raw": {}}


class SameAsEarlier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        earlier(930001, ANNA, "Air freight quote request to SGN", T_MEL - 15000, origin="CGN", destination="SGN", pickup_postcode="53629",
                weight_kg_total=1235.0, volume_cbm_total=10.24, pieces=[{"count": 16}])
        earlier(930002, ANNA, "Air freight quote request: STR to MEL", T_MEL, origin="STR", destination="MEL", pickup_postcode=None,
                weight_kg_total=1841.0, volume_cbm_total=4.63, pieces=[{"count": 6}], prefer="cheapest")
        earlier(930003, ANNA, "Air freight quote request to MIA", T_MEL + 3000, origin="STR", destination="MIA", pickup_postcode="71184",
                weight_kg_total=378.0, volume_cbm_total=1.86, pieces=[{"count": 4}])
        earlier(930004, "someone-else@hackloop.mail", "Air freight quote request: STR to MEL", T_MEL, origin="STR", destination="MEL",
                weight_kg_total=99.0, volume_cbm_total=0.5)

    def test_the_real_mail(self):
        f = {"origin": "STR", "destination": "LAX", "prefer": "cheapest", "filled_by_code": ["origin"], "weight_kg": None, "pieces": []}
        got = recall.merge(new_mail(930010, REAL), f)
        self.assertEqual(got["thread"], 930002)                              # by subject and time, not the newer MIA request
        self.assertEqual((f["weight_kg"], f["volume_cbm"], f["destination"], f["origin"], f.get("pickup_postcode")), (1841.0, 4.63, "LAX", "STR", None))
        self.assertEqual(main.shipment(f), (1841.0, 4.63))
        self.assertEqual(f["same_as_thread"], 930002)

    def test_pickup_details_come_along(self):
        said = ("Hi,\n\nplease quote the same shipment as in my earlier request \"Air freight quote request to SGN\". Cargo and pickup details are "
                "unchanged. New destination: BKK, cheapest option please.\n\nAnna")
        f = {"origin": None, "destination": "BKK", "prefer": "cheapest", "weight_kg": 0}
        self.assertEqual(recall.merge(new_mail(930011, said), f)["thread"], 930001)
        self.assertEqual((f["weight_kg"], f["volume_cbm"], f["pickup_postcode"], f["origin"], f["destination"]), (1235.0, 10.24, "53629", "CGN", "BKK"))

    def test_no_name_given_means_the_most_recent_request(self):
        f = {"destination": "ORD", "weight_kg": None}
        got = recall.merge(new_mail(930012, "Hello,\n\nsame shipment as last time please, but to ORD this time. Fastest option.\n\nAnna"), f)
        self.assertEqual((got["thread"], f["weight_kg"], f["pickup_postcode"]), (930003, 378.0, "71184"))

    def test_only_the_same_sender(self):
        f = {"destination": "LAX", "weight_kg": None}
        self.assertIsNone(recall.merge(new_mail(930013, REAL, sender="new-customer@hackloop.mail"), f))
        self.assertFalse(f.get("weight_kg"))

    def test_a_request_we_do_not_have_is_not_replaced_by_another(self):
        said = "Please quote the same shipment as in my earlier request \"Air freight quote request to NRT\", sent on 2026-11-20 at 09:00 UTC. New destination LAX."
        f = {"destination": "LAX", "weight_kg": None}
        self.assertIsNone(recall.merge(new_mail(930014, said), f))

    def test_a_mail_with_its_own_weight_or_without_a_pointer_is_untouched(self):
        f = {"origin": "STR", "destination": "LAX", "weight_kg": 500.0, "volume_cbm": 2.0, "self_delivery": True}
        self.assertIsNone(recall.merge(new_mail(930015, REAL), f))            # everything is in the new mail: nothing taken
        self.assertEqual((f["weight_kg"], f["volume_cbm"]), (500.0, 2.0))
        f = {"destination": "LAX", "weight_kg": None}
        self.assertIsNone(recall.merge(new_mail(930016, "Hello, please quote 2 pallets to LAX, cheapest option."), f))


class Variations(unittest.TestCase):
    """Erik, 22 Nov 02:23: 'the same route but a new weight, or the same as last time but two more pallets'."""

    @classmethod
    def setUpClass(cls):
        earlier(931001, "bea@recall-test.mail", "Air freight quote request to ATL", T_MEL + 360, origin="DUS", destination="ATL", pickup_postcode="40043",
                weight_kg_total=585.0, volume_cbm_total=5.01, pieces=[{"count": 11}], language="en")
        earlier(931002, "cem@recall-test.mail", "Luftfrachtanfrage nach NRT", T_MEL + 400, origin="MUC", destination="NRT", pickup_postcode="80331",
                weight_kg_total=600.0, volume_cbm_total=3.0, pieces=[], language="de")

    def ask(self, tid, body, sender="bea@recall-test.mail", **f):
        fields = dict({"weight_kg": None, "pieces": [], "language": "en"}, **f)
        return recall.merge(new_mail(tid, body, sender=sender, subject="New request"), fields), fields

    def test_same_route_new_cargo(self):
        got, f = self.ask(931010, "Hello,\n\nsame route and pickup as in my earlier request to ATL, but new cargo: 4 pieces, 320 kg, 1.9 cbm. Cheapest please.",
                          weight_kg=320.0, volume_cbm=1.9)
        self.assertEqual(got["thread"], 931001)
        self.assertEqual((f["origin"], f["destination"], f["pickup_postcode"], f["weight_kg"], f["volume_cbm"]), ("DUS", "ATL", "40043", 320.0, 1.9))
        self.assertNotIn("recall_note", f)                                    # nothing was worked out, nothing to explain

    def test_same_route_new_weight_without_volume_is_not_guessed(self):
        got, f = self.ask(931011, "Hello,\n\nsame route as last week's ATL request, this time 250 kg of spare parts.", weight_kg=250.0)
        self.assertEqual((f["destination"], f["pickup_postcode"], f["weight_kg"]), ("ATL", "40043", 250.0))
        self.assertFalse(f.get("volume_cbm"))                                 # other goods: their volume is not the old one

    def test_same_shipment_new_weight_scales_the_volume(self):
        got, f = self.ask(931012, "Hello,\n\nplease quote the same shipment as in my earlier request to ATL, but the gross weight is now 702 kg. "
                                  "New destination ORD.", weight_kg=702.0, destination="ORD")
        self.assertEqual((f["destination"], f["weight_kg"], f["volume_cbm"]), ("ORD", 702.0, 6.01))      # 5.01 x 702 / 585
        self.assertEqual(f["recall_note"], "I have priced it on 702 kg and 6.01 cbm: the volume scaled with the new weight.")

    def test_two_more_pallets(self):
        got, f = self.ask(931013, "Hello,\n\nsame as last time to ATL, but with two more pallets of the same goods. Fastest option please.")
        self.assertEqual((f["weight_kg"], f["volume_cbm"], f["destination"], f["pickup_postcode"]), (691.4, 5.92, "ATL", "40043"))   # x 13 / 11
        self.assertEqual(f["recall_note"], "I have priced it on 691.4 kg and 5.92 cbm: your earlier shipment of 11 pieces, now 13 of the same size.")
        self.assertEqual(main.shipment(f), (691.4, 5.92))

    def test_fewer_pieces_and_double(self):
        _, f = self.ask(931014, "Same shipment as in my earlier request to ATL, but 3 pieces fewer this time.")
        self.assertEqual((f["weight_kg"], f["volume_cbm"]), (425.5, 3.64))                                 # x 8 / 11
        _, f = self.ask(931015, "Same shipment as in my earlier request to ATL, but double the quantity.")
        self.assertEqual((f["weight_kg"], f["volume_cbm"]), (1170.0, 10.02))
        self.assertIn("2 times your earlier shipment", f["recall_note"])

    def test_more_pallets_without_an_earlier_piece_count_is_not_guessed(self):
        got, f = self.ask(931016, "Guten Tag,\n\ngleiche Sendung wie in meiner letzten Anfrage nach NRT, aber zwei Paletten mehr.", sender="cem@recall-test.mail",
                          language="de")
        self.assertFalse(f.get("weight_kg"))                                  # the clerk then asks the customer for the weight
        self.assertEqual((f["destination"], f["pickup_postcode"]), ("NRT", "80331"))

    def test_the_quote_says_the_totals_it_was_priced_on(self):
        body = "Hi Bea,\n\nFjordline Air Cargo: 3229.68 EUR all-in, about 2 days.\n\nShall I book it?\n\nKind regards\nLena"
        out = main.llm._add_expert_note(body, "I have priced it on 691.4 kg and 5.92 cbm: your earlier shipment of 11 pieces, now 13 of the same size.", "3229.68")
        self.assertIn("about 2 days. I have priced it on 691.4 kg and 5.92 cbm", out)


class OddPieces(unittest.TestCase):
    def test_a_piece_count_instead_of_piece_records_does_not_crash(self):
        """Live 02:20:49: the model answered pieces=[6] for 'across six pieces' and the request went to a person."""
        self.assertEqual(main.shipment({"weight_kg": 1841, "volume_cbm": 4.63, "pieces": [6]}), (1841.0, 4.63))
        self.assertEqual(main.shipment({"weight_kg": 1841, "volume_cbm": 4.63, "pieces": 6}), (1841.0, 4.63))
        self.assertEqual(main.shipment({"weight_kg": 0, "pieces": [{"count": 2, "kg_each": 50}, "x"]}), (100.0, 0.0))


if __name__ == "__main__":
    unittest.main()
