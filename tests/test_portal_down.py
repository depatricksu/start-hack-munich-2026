"""5U turned the portal rate API off (503). We must fall back to email bids. Run: python -m unittest tests.test_portal_down"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from sourcing import portal, bids  # noqa: E402
from core import db  # noqa: E402


class TestPortalDownTriggersBids(unittest.TestCase):
    def test_503_sets_last_down(self):
        portal.LAST_DOWN = False
        # simulate a 503 read
        import sourcing.portal as P
        orig = P.mailbox.api
        P.mailbox.api = lambda *a, **k: (503, {"detail": "rate API unavailable"})
        try:
            P.options("HAM", "EZE", 500, 2) if P.config.API_KEY else P._rate("HAM", "EZE", "MD", 500, 2)
            P._rate("HAM", "EZE", "MD", 500, 2)
        finally:
            P.mailbox.api = orig
        self.assertTrue(portal.LAST_DOWN)

    def test_request_asks_airlines_when_portal_down_even_with_sheet_options(self):
        import random
        tid = random.randint(880000, 889999)          # unique: the suite shares one DB
        db.con().execute("DELETE FROM bids WHERE thread_id=?", (tid,))
        db.con().execute("INSERT OR REPLACE INTO sessions(thread_id,customer,status,fields,options,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, "c@x.mail", "new", '{"origin":"HAM","destination":"EZE","weight_kg_total":500}',
                          '[{"airline":"Wayzata Air Cargo","total_eur":"2000","transit_days":6,"source":"sheet"}]', 1.0))
        orig = bids.serving                           # independent of the carrier-list file / DB state
        bids.serving = lambda role, key: ([{"name": "Tamarind Airways", "email": "tamarind-airways@hackloop.mail"}] if role == "airline" else [])
        portal.LAST_DOWN = True                       # portal is down this round
        try:
            pending = bids.request({"thread_id": tid}, {"origin": "HAM", "destination": "EZE", "weight_kg_total": 500, "pickup_postcode": None})
        finally:
            bids.serving = orig
        asked = [b for b in bids.rows(tid) if b["role"] in ("airline", "ratedesk")]
        self.assertGreater(len(asked), 0)             # we asked airlines + rate desk despite having a sheet option
        self.assertGreater(pending, 0)


class TestBidsUsedWhenSheetsExist(unittest.TestCase):
    def test_fast_bid_beats_slow_sheet(self):
        import random, json, time
        tid = random.randint(890000, 899999)
        db.con().execute("INSERT OR REPLACE INTO sessions(thread_id,customer,status,fields,options,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, "c@x.mail", "waiting_bids", json.dumps({"origin": "HAM", "destination": "EZE", "weight_kg_total": 500, "prefer": "fastest"}),
                          json.dumps([{"airline": "Wayzata Air Cargo", "total": "2000", "total_eur": "2000", "currency": "EUR", "transit_days": 6, "source": "sheet"}]), time.time()))
        bids.ensure()
        db.con().execute("INSERT INTO bids(thread_id,carrier,kind,email,role,required,status,requested_at,replied_at,total,currency,transit_days,total_eur) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (tid, "Meridian Freightways", "airline", "m@x", "airline", 1, "ok", time.time(), time.time(), "2400", "EUR", 3, "2400"))
        opts = bids.final_options(tid, json.loads(db.session(tid)["options"]))
        self.assertIn("Meridian Freightways", [o["airline"] for o in opts])
        best = min(opts, key=lambda x: (x["transit_days"], float(x["total_eur"])))
        self.assertEqual(best["airline"], "Meridian Freightways")


    def test_cheaper_bid_from_an_airline_we_already_priced_wins(self):
        """Round 33 (19:15 change): the winners booked Borealis, which we had from the portal at a higher price.
        The mailed Borealis price must compete with the portal one, not be skipped (Kai's review point 3)."""
        import random, json, time
        tid = random.randint(900000, 909999)
        db.con().execute("INSERT OR REPLACE INTO sessions(thread_id,customer,status,fields,options,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, "c@x.mail", "waiting_bids", json.dumps({"origin": "FRA", "destination": "ORD", "weight_kg_total": 500, "prefer": "cheapest"}),
                          json.dumps([{"airline": "Borealis Freight Airways", "total": "2000", "total_eur": "2000", "currency": "EUR", "transit_days": 3, "source": "portal"}]), time.time()))
        bids.ensure()
        db.con().execute("INSERT INTO bids(thread_id,carrier,kind,email,role,required,status,requested_at,replied_at,total,currency,transit_days,total_eur) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (tid, "Borealis Freight Airways", "airline", "b@x", "airline", 1, "ok", time.time(), time.time(), "1700", "EUR", 3, "1700"))
        opts = bids.final_options(tid, json.loads(db.session(tid)["options"]))
        best = min(opts, key=lambda x: float(x["total_eur"]))
        self.assertEqual((best["airline"], best["total_eur"], best["source"]), ("Borealis Freight Airways", "1700", "bid"))


if __name__ == "__main__":
    unittest.main()


class TestExcludedAirline(unittest.TestCase):
    """Round 42 (20:09): 'Please do not offer Zephyr Steppe Cargo (ZS)'. On a lane priced by bids only, the pick must
    skip the excluded airline and take the next one, not pick it and end with no option."""
    def test_excluded_airline_is_never_picked_on_a_bid_only_lane(self):
        import random, json, time
        tid, cust = random.randint(910000, 919999), "meyer%d@x.mail" % random.randint(1, 10**6)
        db.con().execute("INSERT INTO mails(id,thread_id,sender,subject,body,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, tid, cust, "Quote to ULN", "Cheapest option to ULN please.\n\nPlease do not offer Zephyr Steppe Cargo (ZS) "
                          "for this shipment or for any of our future inquiries.\n\nBest regards", time.time()))
        db.con().execute("INSERT OR REPLACE INTO sessions(thread_id,customer,status,fields,options,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, cust, "waiting_bids", json.dumps({"origin": "FRA", "destination": "ULN", "weight_kg_total": 911, "prefer": "cheapest"}), "[]", time.time()))
        bids.ensure()
        for name, total in (("Zephyr Steppe Cargo", "1000"), ("Lagoon Isles Airways", "3210"), ("Pampero Air Cargo", "3780")):
            db.con().execute("INSERT INTO bids(thread_id,carrier,kind,email,role,required,status,requested_at,replied_at,total,currency,transit_days,hours,total_eur) "
                             "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (tid, name, "airline", "b@x", "airline", 1, "ok", time.time(), time.time(), total, "EUR", 3, 72, total))
        opts = bids.final_options(tid, [])
        self.assertNotIn("Zephyr Steppe Cargo", [x["airline"] for x in opts])
        self.assertEqual(min(opts, key=lambda x: float(x["total_eur"]))["airline"], "Lagoon Isles Airways")
