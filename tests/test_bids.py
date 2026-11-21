"""Bids by mail (sourcing/bids.py). Run: python -m unittest tests.test_bids -v"""
import json, os, tempfile, time, unittest
from decimal import Decimal

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""
os.environ["BID_EXPERIMENT"] = "1"

from core import config, db, main  # noqa: E402
from sourcing import bids  # noqa: E402

_next = [7790000]


def rfq(tid, origin, dest, kg, cbm=0.5, postcode=None, prefer="none"):
    """Start a session as if the gateway call had returned these fields."""
    mail = main.mailbox.normalize({"id": tid, "from": "buyer@acme.mail", "subject": "Quote please",
                                   "body": "%s kg %s to %s" % (kg, origin, dest)})
    db.save_mail(mail)
    db.new_session(mail)
    fields = {"origin": origin, "destination": dest, "weight_kg": kg, "volume_cbm": cbm, "pieces": [],
              "pickup_postcode": postcode, "prefer": prefer, "missing": [], "kind": "new_request",
              "weight_kg_total": kg, "volume_cbm_total": cbm, "reply": main.llm.FALLBACK_REPLY}
    db.update_session(tid, fields=fields, reply_template=fields["reply"])
    main.price_and_quote(tid, mail, fields)
    return db.session(tid)


def answer(bid, text):
    _next[0] += 1
    main.process(main.mailbox.normalize({"id": _next[0], "from": bid["email"], "in_reply_to": 1,
                                         "subject": "Re: request [BID-%d]" % bid["id"], "body": text}))


def quote(tid):
    rows = db.con().execute("SELECT data FROM events WHERE kind='mail_out_dry_run' AND thread_id=?", (tid,)).fetchall()
    return [json.loads(r["data"]) for r in rows]


class TestBids(unittest.TestCase):
    def test_math_per_kg_bid(self):
        form = {"rate_per_kg": 2.5, "surcharges_per_kg": 0.5, "flat_fees": 20, "min_charge": 100}
        self.assertEqual(bids.bid_total(form, 120), Decimal("380.00"))      # 300 + 60 + 20
        self.assertEqual(bids.bid_total(dict(form, min_charge=400), 120), Decimal("480.00"))
        self.assertIsNone(bids.bid_total({"total": None}, 120))

    def test_door_pickup_waits_then_adds_cheapest_trucker(self):
        s = rfq(771001, "MUC", "LAX", 120, 0.9, postcode="80331")
        self.assertEqual(s["status"], "waiting_bids", s["note"])
        trucks = [b for b in bids.rows(771001) if b["role"] == "trucker"]
        self.assertGreaterEqual(len(trucks), 2)
        self.assertEqual(quote(771001), [])                                    # nothing to the customer yet
        flight = min(Decimal(x["total_eur"]) for x in json.loads(s["options"]))
        answer(trucks[0], "We can do it for 240 EUR all-in, delivery in 1 day.")
        main.tick()
        self.assertEqual(db.session(771001)["status"], "waiting_bids")         # others may still be cheaper
        for i, t in enumerate(trucks[1:]):
            answer(t, "Our price: %d EUR, 1 day." % (180 + 30 * i))
        main.tick()
        s = db.session(771001)
        self.assertEqual(s["status"], "quoted")
        chosen = json.loads(s["chosen"])
        self.assertEqual(Decimal(chosen["total_eur"]), flight + 180)
        self.assertEqual(chosen["trucker_total"], "180.00")
        self.assertEqual(len(quote(771001)), 1)
        self.assertIn(chosen["total"], quote(771001)[0]["body"])

    def test_no_trucker_answer_waits_longer_then_human(self):
        rfq(771002, "MUC", "LAX", 120, 0.9, postcode="80331")
        db.update_session(771002, deadline=time.time() - 1)                    # BID_WAIT_S is over
        main.tick()
        self.assertEqual(db.session(771002)["status"], "waiting_bids")         # late quote beats no quote
        db.update_session(771002, received_at=time.time() - config.BID_MAX_WAIT_S - 1)
        main.tick()
        self.assertEqual(db.session(771002)["status"], "needs_human")
        self.assertEqual(quote(771002), [])

    def test_one_trucker_at_deadline_is_enough(self):
        rfq(771003, "MUC", "LAX", 120, 0.9, postcode="80331")
        answer([b for b in bids.rows(771003) if b["role"] == "trucker"][0], "200 EUR, 1 day")
        main.tick()
        self.assertEqual(db.session(771003)["status"], "waiting_bids")
        db.update_session(771003, deadline=time.time() - 1)
        main.tick()
        self.assertEqual(db.session(771003)["status"], "quoted")

    def test_rare_lane_uses_balanced_pick(self):
        s = rfq(771004, "FRA", "ULN", 100)
        self.assertEqual(s["status"], "waiting_bids", s["note"])
        asked = bids.rows(771004)
        self.assertIn("ratedesk", {b["role"] for b in asked})
        airlines = [b for b in asked if b["role"] == "airline"]
        answer(airlines[0], "Total 2000 EUR, transit 6 days")
        answer(airlines[1], "Total 2100 EUR, transit 2 days")
        for b in asked:
            if b["id"] not in (airlines[0]["id"], airlines[1]["id"]):
                answer(b, "Sorry, no capacity, we cannot quote.")
        main.tick()
        s = db.session(771004)
        self.assertEqual(s["status"], "quoted")
        self.assertEqual(json.loads(s["chosen"])["total"], "2100.00")      # 5% dearer but 3x faster wins 50/50
        self.assertEqual(json.loads(s["chosen"])["source"], "bid")

    def test_experiment_never_delays_the_quote(self):
        s = rfq(771005, "HAM", "BOG", 90, 0.4)
        self.assertEqual(s["status"], "quoted")
        asked = bids.rows(771005)
        self.assertTrue(asked and all(not b["required"] for b in asked))
        answer(asked[0], "We offer 300 EUR, 2 days")
        ev = db.con().execute("SELECT data FROM events WHERE kind='bid_received' AND thread_id=771005").fetchone()
        self.assertTrue(json.loads(ev["data"])["late"])
        self.assertEqual(len(quote(771005)), 1)                                # still exactly one quote

    def _door(self, tid, prefer):
        """Two truckers: one cheap and slow (100 EUR, 48 hours), one a bit dearer and fast (110 EUR, 24 hours)."""
        rfq(tid, "MUC", "LAX", 120, 0.9, postcode="80331", prefer=prefer)
        trucks = [b for b in bids.rows(tid) if b["role"] == "trucker"]
        answer(trucks[0], "All-in price is 100 EUR. Transit time from pickup: 48 hours")
        answer(trucks[1], "All-in price is 110 EUR. Transit time from pickup: 24 hours")
        for t in trucks[2:]:
            answer(t, "Sorry, no capacity, we cannot quote.")
        main.tick()
        s = db.session(tid)
        self.assertEqual(s["status"], "quoted", s["note"])
        return json.loads(s["chosen"])["trucker_total"]

    def test_trucker_pick_follows_the_booth_rule(self):
        # Pin the rule so the live .env (which may override BID_PICK) does not change this unit test of the auto logic.
        from core import config
        old = config.BID_PICK
        config.BID_PICK = "auto"
        try:
            self.assertEqual(self._door(7711001, "none"), "110.00")       # no preference: balanced 50/50, not cheapest
            self.assertEqual(self._door(7711002, "cheapest"), "100.00")   # customer asked for the cheapest
            self.assertEqual(self._door(7711003, "fastest"), "110.00")    # customer asked for fast
        finally:
            config.BID_PICK = old

    def test_bid_pick_flag_forces_balanced_for_everyone(self):
        from core import config
        old = config.BID_PICK
        config.BID_PICK = "balanced"
        try:
            self.assertEqual(self._door(7711010, "cheapest"), "110.00")   # flag overrides: balanced even for a cheapest customer
        finally:
            config.BID_PICK = old

    def test_hours_are_read_and_stored(self):
        self._door(7711004, "none")
        hours = sorted(b["hours"] for b in bids.rows(7711004) if b["status"] == "ok")
        self.assertEqual(hours, [24.0, 48.0])
        self.assertEqual(bids._hours({"transit_days": 2}), 48.0)

    def test_bid_pick_override(self):
        old, config.BID_PICK = config.BID_PICK, "cheapest"
        try:
            self.assertEqual(self._door(7711005, "none"), "100.00")
        finally:
            config.BID_PICK = old

    def test_unknown_carrier_mail_is_only_logged(self):
        main.process(main.mailbox.normalize({"id": 7780001, "from": "cobalt-skylift@hackloop.mail", "in_reply_to": 1,
                                             "subject": "Re: booking", "body": "Confirmed."}))
        self.assertTrue(db.con().execute("SELECT 1 FROM events WHERE kind='carrier_mail_unmatched' AND mail_id=7780001").fetchone())

    def test_usd_bid_without_rate_is_not_used(self):
        rfq(771006, "FRA", "ULN", 100)
        a = [b for b in bids.rows(771006) if b["role"] == "airline"][0]
        answer(a, "Total 2000 USD, 3 days")
        self.assertEqual([b for b in bids.rows(771006) if b["id"] == a["id"]][0]["status"], "no_fx")


class TestPortalCurrency(unittest.TestCase):
    """A non-EUR portal price without an exchange rate must never be relabelled as EUR."""

    def _rate(self, reply):
        from sourcing import portal
        old = portal.mailbox.api
        portal.mailbox.api = lambda *a, **k: (200, reply)
        try:
            return portal._rate("FRA", "JFK", "LM", 100, 0.5)
        finally:
            portal.mailbox.api = old

    BASE = {"airline": "Lumen Air Cargo", "transit_days": 3, "total": "1000.00", "rate_id": "R-12345678"}

    def test_usd_with_rate_is_converted(self):
        o = self._rate(dict(self.BASE, currency="USD", fx_eur_per_usd="0.92"))
        self.assertEqual(o["total_eur"], "920.00")
        self.assertEqual(main.quote_in_eur(o)["total"], "920.00")
        self.assertEqual(main.quote_in_eur(o)["currency"], "EUR")

    def test_usd_without_rate_stays_usd(self):
        o = self._rate(dict(self.BASE, currency="USD"))
        self.assertTrue(o["fx_missing"])
        q = main.quote_in_eur(o)
        self.assertEqual((q["total"], q["currency"]), ("1000.00", "USD"))

    def test_eur_is_untouched(self):
        o = self._rate(dict(self.BASE, currency="EUR"))
        self.assertNotIn("fx_missing", o)
        self.assertEqual(main.quote_in_eur(o)["total"], "1000.00")


if __name__ == "__main__":
    unittest.main()
