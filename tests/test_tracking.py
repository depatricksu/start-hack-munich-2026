"""Task 05 tracking answers. Run: python -m unittest tests.test_tracking -v"""
import json, os, tempfile, time, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main  # noqa: E402
from booking import crm, tracking  # noqa: E402

TRACKER = "tracking@hackloop.mail"


def ask(id, body, subject="Shipment status"):
    main.process(main.mailbox.normalize({"id": id, "from": TRACKER, "subject": subject, "body": body}))
    rows = db.con().execute("SELECT data FROM events WHERE kind IN ('mail_out_dry_run','mail_out') AND mail_id=?",
                            (id,)).fetchall()
    return [json.loads(r["data"]) for r in rows]


class TestTracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        now = time.time()
        crm.upsert(101, customer="a@x.mail", origin="STR", destination="MEL", airline="Yellowtail Air Freight",
                   weight_kg=90, volume_cbm=0.4, transit_days=3, status="confirmed",
                   booking_reference="BK-7F3K2Q9A", booked_at=now, confirmed_at=now)
        crm.upsert(102, customer="b@x.mail", origin="FRA", destination="DFW", airline="Elbflug Air Freight",
                   weight_kg=120, transit_days=3, status="requested")
        crm.upsert(103, customer="c@x.mail", origin="MUC", destination="LAX", airline="Yellowtail Air Freight",
                   weight_kg=230, transit_days=5, status="booked", booking_reference="BK-AAAA1111", booked_at=now)
        crm.upsert(104, customer="d@x.mail", origin="MUC", destination="LAX", airline="Wayzata Air Cargo",
                   weight_kg=500, transit_days=4, status="booked", booking_reference="BK-BBBB2222", booked_at=now)

    def test_routed_to_tracking(self):
        self.assertEqual(main.route(main.mailbox.normalize({"id": 1, "from": TRACKER, "subject": "x", "body": "y"}),
                                    "google@hackloop.mail"), "tracking")

    def test_by_booking_reference(self):
        out = ask(201, "Hi, where is shipment BK-7F3K2Q9A?")
        self.assertEqual(len(out), 1)
        body = out[0]["body"]
        self.assertEqual(out[0]["to"], TRACKER)
        for s in ("BK-7F3K2Q9A", "STR to MEL", "Yellowtail Air Freight", "confirmed", "Expected arrival"):
            self.assertIn(s, body)

    def test_by_team_reference(self):
        body = ask(202, "Status for GOOGLE-102 please")[0]["body"]
        self.assertIn("FRA to DFW", body)
        self.assertIn("waiting for their confirmation", body)

    def test_by_route_unique(self):
        self.assertIn("BK-7F3K2Q9A", ask(203, "Our STR to MEL cargo, any update?")[0]["body"])

    def test_by_route_and_weight(self):
        self.assertIn("BK-BBBB2222", ask(204, "Where is the 500 kg shipment MUC-LAX?")[0]["body"])

    def test_ambiguous_route_asks_for_reference(self):
        body = ask(205, "Where is our MUC to LAX shipment?")[0]["body"]
        self.assertIn("booking reference", body)
        self.assertNotIn("BK-", body.replace("(BK-...)", ""))

    def test_unknown_never_invents(self):
        body = ask(206, "Where is BK-ZZZZ9999?")[0]["body"]
        self.assertIn("couldn't match", body)


    def test_by_thread_of_our_booking_mail(self):
        crm.upsert(105, customer="lea@x.mail", origin="HAM", destination="MEX", airline="Elbflug Air Freight",
                   weight_kg=300, transit_days=3, status="booked", booking_reference="BK-CCCC3333", booked_at=time.time())
        main.process(main.mailbox.normalize({"id": 207, "from": TRACKER, "subject": "Re: Booking", "body": "Where is it?",
                                             "references": [105], "in_reply_to": 105}))
        rows = db.con().execute("SELECT data FROM events WHERE kind='mail_out_dry_run' AND mail_id=207").fetchall()
        self.assertIn("BK-CCCC3333", json.loads(rows[0]["data"])["body"])

    def test_by_customer_company(self):
        crm.upsert(106, customer="t.auer@auer-maschinenbau.de", origin="DUS", destination="JFK",
                   airline="Fjordline Air Cargo", weight_kg=800, transit_days=3, status="booked",
                   booking_reference="BK-DDDD4444", booked_at=time.time())
        body = ask(208, "Hello, can you tell us where the shipment of Auer Maschinenbau is?")[0]["body"]
        self.assertIn("BK-DDDD4444", body)
        self.assertIn("Düsseldorf to New York", body)


if __name__ == "__main__":
    unittest.main()
