"""BID_ALWAYS: ask 2-5 carriers + the rate desk on EVERY request and wait, even when the portal/sheet priced it.
Board evidence: airline bids beat our quote ~80% of the time, so skipping them loses too_high rounds (33, 34).
Run: python -m unittest tests.test_bid_always"""
import os, tempfile, unittest
from unittest import mock
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from sourcing import bids, portal  # noqa: E402
from core import db, config  # noqa: E402

FIELDS = {"origin": "MUC", "destination": "CAI", "weight_kg_total": 300, "pickup_postcode": None, "prefer": "cheapest"}
SIX = [{"name": "A%d" % i, "email": "a%d@hackloop.mail" % i} for i in range(6)]


class TestBidAlways(unittest.TestCase):
    def _session(self, tid, options):
        db.con().execute("DELETE FROM bids WHERE thread_id=?", (tid,))
        db.con().execute("INSERT OR REPLACE INTO sessions(thread_id,customer,status,fields,options,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, "c@x.mail", "new",
                          '{"origin":"MUC","destination":"CAI","weight_kg_total":300}', options, 1.0))

    def test_asks_five_carriers_plus_desk_when_price_exists(self):
        import random
        tid = random.randint(870000, 879999)
        self._session(tid, '[{"airline":"Borealis","total_eur":"1475","transit_days":4,"source":"portal"}]')
        portal.LAST_DOWN = False
        with mock.patch.object(config, "BID_ALWAYS", True), mock.patch.object(config, "BID_MAX_CARRIERS", 5), \
             mock.patch.object(bids, "serving", lambda role, key: SIX if role == "airline" else []):
            pending = bids.request(db.session(tid), FIELDS)
        asked = [b for b in bids.rows(tid) if b["role"] in ("airline", "ratedesk") and b["required"]]
        self.assertEqual(len(asked), 6)             # 5 carriers (capped) + the rate desk
        self.assertEqual(pending, 6)                # all required: the clerk waits for them

    def test_off_by_default_keeps_fast_path(self):
        import random
        tid = random.randint(860000, 869999)
        self._session(tid, '[{"airline":"Borealis","total_eur":"1475","transit_days":4,"source":"portal"}]')
        portal.LAST_DOWN = False
        with mock.patch.object(config, "BID_ALWAYS", False), mock.patch.object(config, "BID_EXPERIMENT", False), \
             mock.patch.object(bids, "serving", lambda role, key: SIX if role == "airline" else []):
            pending = bids.request(db.session(tid), FIELDS)
        self.assertEqual(pending, 0)                # nobody required: quote immediately on the portal price


if __name__ == "__main__":
    unittest.main()


class TestBidsOnlyFollowsPrefer(unittest.TestCase):
    """Round 47: a bids-only lane pre-picked the 'balanced' airline on a CHEAPEST request (Fjordline 2604) instead
    of the cheapest (Nova Atlas 1833) -> too_high. Now every bid becomes an option and finalize picks by the wish."""
    def _lane(self, tid, prefer):
        import time, json as J
        db.con().execute("DELETE FROM bids WHERE thread_id=?", (tid,))
        db.con().execute("INSERT OR REPLACE INTO sessions(thread_id,customer,status,fields,options,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, "c@x.mail", "waiting_bids", J.dumps({"origin": "STR", "destination": "EZE", "weight_kg_total": 485, "prefer": prefer}), "[]", time.time()))
        bids.ensure()
        for carrier, total, days in (("Nova Atlas Cargo", "1833.66", 7), ("Aurelia Air Cargo", "2408.21", 6), ("Fjordline Air Cargo", "2603.80", 4)):
            db.con().execute("INSERT INTO bids(thread_id,carrier,kind,email,role,required,status,requested_at,replied_at,total,currency,transit_days,total_eur) "
                             "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (tid, carrier, "airline", carrier.lower().replace(" ", "-") + "@x", "airline", 1, "ok", time.time(), time.time(), total, "EUR", days, total))

    def test_cheapest_request_takes_the_cheapest_bid(self):
        import random, json as J
        tid = random.randint(900000, 909999)
        self._lane(tid, "cheapest")
        opts = bids.final_options(tid, J.loads(db.session(tid)["options"]))
        best = min(opts, key=lambda x: float(x["total_eur"]))
        self.assertEqual(best["airline"], "Nova Atlas Cargo")        # cheapest, not the balanced Fjordline
        self.assertEqual(len(opts), 3)                                # all three bids are options, not one pre-pick

    def test_fastest_request_can_still_take_the_fastest(self):
        import random, json as J
        tid = random.randint(910000, 919999)
        self._lane(tid, "fastest")
        opts = bids.final_options(tid, J.loads(db.session(tid)["options"]))
        best = min(opts, key=lambda x: (x["transit_days"], float(x["total_eur"])))
        self.assertEqual(best["airline"], "Fjordline Air Cargo")      # 4 days, the fastest
