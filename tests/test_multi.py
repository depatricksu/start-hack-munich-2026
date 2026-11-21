"""Several shipments in one mail. Run: python -m unittest tests.test_multi -v"""
import json, os, tempfile, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main  # noqa: E402

CUSTOMER = "lea@customer-example.mail"
BODY = "Hi, two shipments please: 90 kg, 0.4 cbm HAM to BOG and 120 kg, 0.6 cbm FRA to DFW. Cheapest."


def form(shipments, reply="Hi Lea,\n\n{PRICE_TABLE}\n\nTotal all-in: {TOTAL}\n\nYour forwarding team"):
    return {"origin": None, "destination": None, "weight_kg": None, "volume_cbm": None, "pieces": [],
            "prefer": "cheapest", "kind": "new_request", "multi_shipment": True, "shipments": shipments,
            "language": "en", "missing": [], "reply": reply}, {"fake": True}


def run(tid, fields):
    m = main.mailbox.normalize({"id": tid, "from": CUSTOMER, "subject": "Two shipments", "body": BODY})
    with mock.patch.object(main.llm, "extract", return_value=fields), \
         mock.patch("sourcing.portal.options", return_value=[]):
        main.process(m)
    return db.session(tid)


def sent(tid):
    rows = db.con().execute("SELECT data FROM events WHERE kind IN ('mail_out_dry_run','mail_out') AND thread_id=?",
                            (tid,))
    return [json.loads(r["data"]) for r in rows]


class TestMulti(unittest.TestCase):
    SH = [{"origin": "HAM", "destination": "BOG", "weight_kg": 90, "volume_cbm": 0.4},
          {"origin": "FRA", "destination": "DFW", "weight_kg": 120, "volume_cbm": 0.6}]

    def test_two_lanes_one_reply_with_total(self):
        s = run(9001, form(self.SH))
        self.assertEqual(s["status"], "quoted")
        chosen = json.loads(s["chosen"])
        self.assertEqual(len(chosen["parts"]), 2)
        total = sum(float(p["total_eur"]) for p in chosen["parts"])
        self.assertAlmostEqual(float(chosen["total"]), total, places=2)
        mails = sent(9001)
        self.assertEqual(len(mails), 1)
        body = mails[0]["body"]
        self.assertIn("HAM to BOG", body)
        self.assertIn("FRA to DFW", body)
        self.assertIn("%.2f EUR" % total, body)
        self.assertNotIn("{", body)

    def test_fallback_reply_when_llm_used_single_placeholders(self):
        s = run(9002, form(self.SH, reply="Price {PRICE} with {AIRLINE}"))
        self.assertEqual(s["status"], "quoted")
        self.assertIn("All-in total", sent(9002)[0]["body"])

    def test_unknown_lane_goes_to_human_and_sends_nothing(self):
        sh = self.SH + [{"origin": "MUC", "destination": "XXX", "weight_kg": 50, "volume_cbm": 0.1}]
        s = run(9003, form(sh))
        self.assertEqual(s["status"], "needs_human")
        self.assertIn("multi_shipment #3", s["note"])
        self.assertEqual(sent(9003), [])

    def test_door_pickup_goes_to_human(self):
        sh = [dict(self.SH[0]), {"pickup_postcode": "80331", "destination": "DFW", "weight_kg": 50, "volume_cbm": 0.2}]
        s = run(9004, form(sh))
        self.assertEqual(s["status"], "needs_human")
        self.assertIn("door pickup", s["note"])

    def test_accept_goes_to_human_with_parts(self):
        run(9005, form(self.SH))
        reply = main.mailbox.normalize({"id": 9006, "from": CUSTOMER, "subject": "Re: Two shipments",
                                        "body": "Great, please book both.", "references": [9005], "in_reply_to": 9005})
        main.process(reply)
        s = db.session(9005)
        self.assertEqual(s["status"], "needs_human")
        self.assertIn("multi_shipment accepted", s["note"])


if __name__ == "__main__":
    unittest.main()
