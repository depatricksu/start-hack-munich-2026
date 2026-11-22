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
        f = {"destination": "LAX", "weight_kg": 500.0, "volume_cbm": 2.0}
        self.assertIsNone(recall.merge(new_mail(930015, REAL), f))
        self.assertEqual((f["weight_kg"], f["volume_cbm"]), (500.0, 2.0))
        f = {"destination": "LAX", "weight_kg": None}
        self.assertIsNone(recall.merge(new_mail(930016, "Hello, please quote 2 pallets to LAX, cheapest option."), f))


class OddPieces(unittest.TestCase):
    def test_a_piece_count_instead_of_piece_records_does_not_crash(self):
        """Live 02:20:49: the model answered pieces=[6] for 'across six pieces' and the request went to a person."""
        self.assertEqual(main.shipment({"weight_kg": 1841, "volume_cbm": 4.63, "pieces": [6]}), (1841.0, 4.63))
        self.assertEqual(main.shipment({"weight_kg": 1841, "volume_cbm": 4.63, "pieces": 6}), (1841.0, 4.63))
        self.assertEqual(main.shipment({"weight_kg": 0, "pieces": [{"count": 2, "kg_each": 50}, "x"]}), (100.0, 0.0))


if __name__ == "__main__":
    unittest.main()
