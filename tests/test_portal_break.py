"""Portal weight-break: also price at the next bracket start; cheaper one wins. Fake API, no network."""
import os, unittest
from unittest import mock
os.environ.setdefault("DRY_RUN", "1")
from core import config
from sourcing import portal

RATES = {1.0: "0", 45: "4.0", 100: "3.0", 300: "2.5", 500: "2.0", 1000: "1.5"}


def fake_api(method, path, body=None, params=None, timeout=20):
    if path == "/v1/portal/brackets":
        return 200, {"breaks_kg": [0, 45, 100, 300, 500, 1000]}
    w = float(params["weight_kg"])
    rate = [r for b, r in sorted(RATES.items()) if w >= b][-1]
    return 200, {"airline": "Meridian Freightways", "airline_code": "MD", "transit_days": 2, "currency": "EUR",
                 "total": "%.2f" % (w * float(rate)), "rate_id": "R-%dabcdefgh" % w, "chargeable_weight_kg": str(w)}


DEEP = {0: 5.0, 45: 4.0, 100: 3.0, 300: 2.5, 500: 2.0, 1000: 0.9, 2000: 0.4}


def deep_api(method, path, body=None, params=None, timeout=20):
    if path == "/v1/portal/brackets":
        return 200, {"breaks_kg": sorted(DEEP)}
    w = float(params["weight_kg"])
    rate = [r for b, r in sorted(DEEP.items()) if w >= b][-1]
    return 200, {"airline": "Lumen", "airline_code": "LU", "transit_days": 2, "currency": "EUR",
                 "total": "%.2f" % (w * rate), "rate_id": "R-%dabcdefgh" % w, "chargeable_weight_kg": str(w)}


class TestBreak(unittest.TestCase):
    def run_opts(self, w, on):
        portal._BREAKS.clear()
        with mock.patch.object(config, "API_KEY", "x"), mock.patch.object(portal.mailbox, "api", fake_api), \
                mock.patch.dict(portal.LANES, {("CGN", "ORD"): [{"code": "MD", "name": "Meridian"}]}):
            return portal.options("CGN", "ORD", w, 0, weight_break=on)

    def test_off_is_unchanged(self):
        self.assertEqual([o["total"] for o in self.run_opts(676, False)], ["1352.00"])

    def test_next_break_cheaper(self):
        opts = self.run_opts(676, True)                  # 676 x 2.0 = 1352 vs 1000 x 1.5 = 1500
        self.assertEqual(len(opts), 2)
        opts = self.run_opts(900, True)                  # 900 x 2.0 = 1800 vs 1000 x 1.5 = 1500 -> break wins
        best = min(opts, key=lambda o: float(o["total"]))
        self.assertEqual((best["total"], best["billed_kg"], best.get("weight_break")), ("1500.00", "1000.0", True))

    def test_deeper_bracket_found(self):
        portal._BREAKS.clear()
        with mock.patch.object(config, "API_KEY", "x"), mock.patch.object(portal.mailbox, "api", deep_api), \
                mock.patch.dict(portal.LANES, {("MUC", "SYD"): [{"code": "LU", "name": "Lumen"}]}):
            opts = portal.options("MUC", "SYD", 400, 0, weight_break=True)
        best = min(opts, key=lambda o: float(o["total"]))
        # 400 x 2.5 = 1000; next 500 x 2.0 = 1000; 1000 x 0.9 = 900; 2000 x 0.4 = 800 -> the deepest wins
        self.assertEqual((best["billed_kg"], best["total"]), ("2000.0", "800.00"))

    def test_stops_when_climbing_gets_expensive(self):
        reads = []

        def api(method, path, body=None, params=None, timeout=20):
            if path != "/v1/portal/brackets":
                reads.append(float(params["weight_kg"]))
            return fake_api(method, path, body, params, timeout)
        portal._BREAKS.clear()
        with mock.patch.object(config, "API_KEY", "x"), mock.patch.object(portal.mailbox, "api", api), \
                mock.patch.dict(portal.LANES, {("CGN", "ORD"): [{"code": "MD", "name": "Meridian"}]}):
            portal.options("CGN", "ORD", 50, 0, weight_break=True)
        # 50 x 4 = 200; 100 x 3 = 300 (50 % dearer) -> stop, no read at 300 kg
        self.assertEqual(reads, [50.0, 100.0])

    def test_top_bracket_no_extra_read(self):
        self.assertEqual(len(self.run_opts(1500, True)), 1)


if __name__ == "__main__":
    unittest.main()
