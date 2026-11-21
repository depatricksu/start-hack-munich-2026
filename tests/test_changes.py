"""Setup-change detection: diff lines, portal lane refresh logs and swaps lanes. Fake API, no network."""
import os, tempfile, unittest
from unittest import mock
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "changes.db"))
from core import config
from monitor import changes
from sourcing import portal


class TestDiff(unittest.TestCase):
    def test_lists_and_brackets(self):
        self.assertEqual(changes.diff("ports", ["FRA-JFK:PL,SL"], ["FRA-JFK:SL", "MUC-JFK:SL"]),
                         ["+ FRA-JFK:SL", "+ MUC-JFK:SL", "- FRA-JFK:PL,SL"])
        self.assertEqual(changes.diff("brackets", {"MD": [0, 45, 100]}, {"MD": [0, 45, 300]}), ["MD: [0, 45, 100] -> [0, 45, 300]"])

    def test_openapi_text_change(self):
        a = {"paths": {"/x": {"get": {"description": "Poll. There is no push. Keep since_id going."}}}}
        b = {"paths": {"/x": {"get": {"description": "Poll. Mail can be pushed. Keep since_id going."}, "put": {"summary": "new"}}}}
        lines = changes.diff("openapi", a, b)
        self.assertTrue(any("There is no push" in l for l in lines))
        self.assertTrue(any("/x/put/summary" in l for l in lines))


class TestPortalRefresh(unittest.TestCase):
    def test_lanes_swap_and_log(self):
        logged = []

        def api(method, path, body=None, params=None, timeout=20):
            return 200, {"lanes": [{"origin": "FRA", "destination": "JFK", "airlines": [{"code": "SL", "name": "Solace"}]}]}
        with mock.patch.object(config, "API_KEY", "x"), mock.patch.object(portal.mailbox, "api", api), \
                mock.patch.object(portal, "_log", lambda kind, **d: logged.append((kind, d))), \
                mock.patch.dict(portal.LANES, {("FRA", "JFK"): [{"code": "PL"}, {"code": "SL"}]}, clear=True):
            portal.refresh_lanes(force=True)
            self.assertEqual([a["code"] for a in portal.LANES[("FRA", "JFK")]], ["SL"])
        self.assertEqual(logged[0][0], "setup_change")
        self.assertIn("FRA-JFK ['PL', 'SL']->['SL']", logged[0][1]["changed"])


if __name__ == "__main__":
    unittest.main()
