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
        tid = 88001
        db.con().execute("INSERT OR REPLACE INTO sessions(thread_id,customer,status,fields,options,received_at) VALUES(?,?,?,?,?,?)",
                         (tid, "c@x.mail", "new", '{"origin":"HAM","destination":"EZE","weight_kg_total":500}',
                          '[{"airline":"Wayzata Air Cargo","total_eur":"2000","transit_days":6,"source":"sheet"}]', 1.0))
        portal.LAST_DOWN = True                       # portal is down this round
        pending = bids.request({"thread_id": tid}, {"origin": "HAM", "destination": "EZE", "weight_kg_total": 500, "pickup_postcode": None})
        asked = [b for b in bids.rows(tid) if b["role"] in ("airline", "ratedesk")]
        self.assertGreater(len(asked), 0)             # we asked airlines + rate desk despite having a sheet option
        self.assertGreater(pending, 0)


if __name__ == "__main__":
    unittest.main()
