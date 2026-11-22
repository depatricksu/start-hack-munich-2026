"""5U, 22 Nov: when the rate API answers 503, only the portal's web page has the portal airlines' prices. 5U's rule
(04:03): no human in the loop, also not on that page. The clerk waits for a rate only when an AUTOMATED source is
configured (sourcing/portal_page.py); otherwise it quotes at the normal time with what it has."""
import json, os, tempfile, time, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import config, db  # noqa: E402
from sourcing import portal, portal_page  # noqa: E402


def session(tid, fields, options, received=None):
    mail = {"id": tid, "thread_id": tid, "sender": "mira@customer.mail", "subject": "Air freight quote", "body": "x",
            "received_at": received or time.time(), "raw": {}}
    db.save_mail(mail)
    db.new_session(mail)
    db.update_session(tid, fields=fields, options=options, status="waiting_bids")
    return mail


class PortalDown(unittest.TestCase):
    def setUp(self):
        self.source, config.PORTAL_PAGE_SOURCE = config.PORTAL_PAGE_SOURCE, "agent"      # an automated harness is running
        self.lanes = dict(portal.LANES)
        portal.LANES.clear()
        portal.LANES[("HAM", "YYZ")] = [{"code": "BX", "name": "Borealis Freight Airways"}, {"code": "JP", "name": "Juniper Cargo Lines"}]
        portal.LANES[("HAM", "MEX")] = [{"code": "RV", "name": "Riverbend Airlines Cargo"}]

    def tearDown(self):
        config.PORTAL_PAGE_SOURCE = self.source
        portal.LANES.clear()
        portal.LANES.update(self.lanes)

    def test_the_quote_is_held_and_says_what_to_look_up(self):
        f = {"origin": "HAM", "destination": "YYZ", "weight_kg_total": 81.0, "volume_cbm_total": 0.67, "prefer": "fastest"}
        mail = session(920001, f, [])
        self.assertTrue(portal_page.hold(920001, mail["id"], []))
        s = db.session(920001)
        self.assertAlmostEqual(s["deadline"], s["received_at"] + config.PORTAL_DOWN_HOLD_S, places=1)
        self.assertIn("RATE API DOWN, waiting for the portal page agent", s["note"])
        self.assertNotIn("Read the rate", s["note"])                # nothing asks a person to do anything
        for part in ("BX (Borealis Freight Airways", "JP (Juniper Cargo Lines", "HAM to YYZ", "81 kg", "0.67 cbm"):
            self.assertIn(part, s["note"])

    def test_a_rate_from_the_automated_source_becomes_an_option_and_releases_the_quote(self):
        f = {"origin": "HAM", "destination": "YYZ", "weight_kg_total": 81.0, "volume_cbm_total": 0.67, "prefer": "fastest"}
        mail = session(920002, f, [])
        portal_page.hold(920002, mail["id"], [])
        opt = portal_page.add(920002, "bx", "645.6", 1, "R-CN-Uk_5BeqIhb2d4", by="test-harness")
        self.assertEqual((opt["airline"], opt["airline_code"], opt["total_eur"], opt["transit_days"], opt["source"], opt["rate_id"]),
                         ("Borealis Freight Airways", "BX", "645.60", 1, "portal page", "R-CN-Uk_5BeqIhb2d4"))
        s = db.session(920002)
        self.assertLessEqual(s["deadline"], time.time())                       # the clerk quotes on its next tick
        self.assertEqual([o["airline"] for o in json.loads(s["options"])], ["Borealis Freight Airways"])
        portal_page.add(920002, "Borealis Freight Airways", "640.00", 1)      # read again: replaces, never doubles
        self.assertEqual([o["total_eur"] for o in json.loads(db.session(920002)["options"])], ["640.00"])
        self.assertEqual(portal_page.known_days("HAM", "YYZ"), {"Borealis Freight Airways": 1})

    def test_no_hold_when_no_portal_airline_can_be_the_answer(self):
        f = {"origin": "FRA", "destination": "ORD", "weight_kg_total": 1076.0, "volume_cbm_total": 4.83, "prefer": "fastest"}
        mail = session(920003, f, [])
        before = db.session(920003)["deadline"]
        self.assertFalse(portal_page.hold(920003, mail["id"], [{"airline": "Orion Cargo Air", "transit_days": 2, "total_eur": "2334.92"}]))   # no portal airline on the lane
        self.assertEqual(db.session(920003)["deadline"], before)
        # fastest wanted, and the only portal airline on the lane is known to be slower than a sheet airline
        db.event("options", 920004, options=[{"airline": "Riverbend Airlines Cargo", "origin": "HAM", "destination": "MEX", "transit_days": 4, "source": "portal"}])
        f = {"origin": "HAM", "destination": "MEX", "weight_kg_total": 500.0, "volume_cbm_total": 1.0, "prefer": "fastest"}
        mail = session(920004, f, [])
        self.assertFalse(portal_page.hold(920004, mail["id"], [{"airline": "Yellowtail Air Freight", "transit_days": 3, "total_eur": "1500.00"}]))
        self.assertTrue(portal_page.hold(920004, mail["id"], [{"airline": "Yellowtail Air Freight", "transit_days": 5, "total_eur": "1500.00"}]))

    def test_without_an_automated_source_nothing_waits_for_a_person(self):
        """5U, 04:03: 'no human in the loop ... that includes the portal page'. No source configured: no hold."""
        config.PORTAL_PAGE_SOURCE = ""
        f = {"origin": "HAM", "destination": "YYZ", "weight_kg_total": 81.0, "volume_cbm_total": 0.67, "prefer": "fastest"}
        mail = session(920007, f, [])
        before = db.session(920007)
        self.assertFalse(portal_page.hold(920007, mail["id"], []))
        after = db.session(920007)
        self.assertEqual((after["deadline"], after["note"]), (before["deadline"], before["note"]))   # normal time, no note for a person

    def test_the_source_is_logged_with_the_rate(self):
        f = {"origin": "HAM", "destination": "YYZ", "weight_kg_total": 81.0, "volume_cbm_total": 0.67, "prefer": "fastest"}
        session(920008, f, [])
        portal_page.add(920008, "BX", "645.60", 1, by="browser-agent")
        e = db.con().execute("SELECT data FROM events WHERE thread_id=920008 AND kind='portal_page_price'").fetchone()
        self.assertEqual(json.loads(e["data"])["by"], "browser-agent")

    def test_too_late_is_refused(self):
        f = {"origin": "HAM", "destination": "YYZ", "weight_kg_total": 81.0, "volume_cbm_total": 0.67}
        session(920005, f, [])
        db.update_session(920005, status="quoted")
        with self.assertRaises(SystemExit):
            portal_page.add(920005, "BX", "645.60", 1)

    def test_release_without_a_rate(self):
        f = {"origin": "HAM", "destination": "YYZ", "weight_kg_total": 81.0, "volume_cbm_total": 0.67, "prefer": "fastest"}
        mail = session(920006, f, [])
        portal_page.hold(920006, mail["id"], [])
        portal_page.go(920006)
        self.assertLessEqual(db.session(920006)["deadline"], time.time())


if __name__ == "__main__":
    unittest.main()
