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


def run(tid, fields, attachments=(), body=BODY, portal=()):
    m = main.mailbox.normalize({"id": tid, "from": CUSTOMER, "subject": "Two shipments", "body": body,
                                "attachments": list(attachments)})
    with mock.patch.object(main.llm, "extract", return_value=fields), \
         mock.patch("sourcing.portal.options", return_value=list(portal)):
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


def packing_list(text):
    import base64
    return {"id": "a1", "filename": "PL_1.txt", "content_base64": base64.b64encode(text.encode()).decode()}


DG_LIST = "Packing list\nDangerous goods: UN1950, Class 2.1, Aerosols, flammable\n"


class TestMultiDangerousGoods(unittest.TestCase):
    """Several shipments AND dangerous goods: the multi reply must carry the same DG paragraph as a single quote."""
    SH = TestMulti.SH

    def test_dg_in_attachment_gets_the_paragraph(self):
        s = run(9101, form(self.SH), attachments=[packing_list(DG_LIST)])
        self.assertEqual(s["status"], "quoted", s["note"])
        body = sent(9101)[0]["body"]
        self.assertIn("UN1950", body)
        self.assertIn("Shipper's Declaration", body)
        self.assertLess(body.index("UN1950"), body.index("Best regards"))      # before the sign-off
        self.assertIn("All-in total", body)                                     # the prices are still there
        self.assertEqual(len(sent(9101)), 1)

    def test_no_dg_reply_is_unchanged(self):
        s = run(9102, form(self.SH), attachments=[packing_list("Packing list\nGross weight: 210 kg\n")])
        self.assertEqual(s["status"], "quoted")
        self.assertNotIn("dangerous", sent(9102)[0]["body"].lower())

    def test_denial_in_the_mail_is_not_dg(self):
        f, u = form(self.SH)
        f["dangerous_goods"] = True                                             # the model flagged the word
        s = run(9103, (f, u), body=BODY + " All general cargo, non-dangerous.")
        self.assertEqual(s["status"], "quoted")
        self.assertNotIn("Shipper's Declaration", sent(9103)[0]["body"])

    def test_dg_declared_in_the_mail_gets_the_paragraph(self):
        f, u = form(self.SH)
        f["dangerous_goods"] = True
        s = run(9104, (f, u), body=BODY + " Dangerous goods: UN3480, Class 9, lithium batteries.")
        self.assertEqual(s["status"], "quoted", s["note"])
        self.assertIn("UN3480", sent(9104)[0]["body"])

    def test_dg_mode_human_sends_nothing(self):
        os.environ["DG_MODE"] = "human"
        try:
            s = run(9105, form(self.SH), attachments=[packing_list(DG_LIST)])
        finally:
            os.environ.pop("DG_MODE", None)
        self.assertEqual(s["status"], "needs_human")
        self.assertIn("dangerous goods", s["note"])
        self.assertEqual(sent(9105), [])

    def test_surcharge_mode_changes_the_total_in_text_and_record(self):
        os.environ.update(DG_MODE="surcharge", DG_SURCHARGE_EUR_PER_KG="0", DG_SURCHARGE_MIN_EUR="50")
        try:
            s = run(9106, form(self.SH), attachments=[packing_list(DG_LIST)])
        finally:
            for k in ("DG_MODE", "DG_SURCHARGE_EUR_PER_KG", "DG_SURCHARGE_MIN_EUR"):
                os.environ.pop(k, None)
        chosen = json.loads(s["chosen"])
        parts = sum(float(p["total_eur"]) for p in chosen["parts"])
        self.assertAlmostEqual(float(chosen["total"]), parts + 50, places=2)
        self.assertIn("%.2f" % (parts + 50), sent(9106)[0]["body"])              # the mail shows the new total
        self.assertNotIn("All-in total: %.2f EUR" % parts, sent(9106)[0]["body"])

    def test_price_without_exchange_rate_is_never_summed(self):
        usd = {"airline": "Lumen Air Cargo", "origin": "HAM", "destination": "BOG", "transit_days": 2,
               "currency": "USD", "total": "10.00", "total_eur": "10.00", "source": "portal", "fx_missing": True,
               "rate_id": "R-12345678"}
        s = run(9107, form(self.SH), portal=[usd])
        self.assertEqual(s["status"], "quoted")
        self.assertNotIn("Lumen", json.loads(s["chosen"])["airline"])           # the 10.00 "EUR" trap was not taken


if __name__ == "__main__":
    unittest.main()
