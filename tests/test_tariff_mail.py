"""Tariff mails -> live price update. Run: python -m unittest tests.test_tariff_mail -v
Uses the TXT tariff (no extra packages). The XLSX case runs only where openpyxl is installed."""
import base64, json, os, tempfile, unittest

TMP = tempfile.mkdtemp()
os.environ.setdefault("DB_PATH", os.path.join(TMP, "test.db"))
os.environ["TARIFF_OVERRIDES"] = os.path.join(TMP, "overrides.json")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import config, db, main  # noqa: E402
from pricing import price, tariff_mail  # noqa: E402

KIT = os.path.join(config.ROOT, "kit", "start-kit")
TXT = open(os.path.join(KIT, "yellowtail-air-freight-tariff-2026-11.txt"), encoding="utf-8").read()
YT = "yellowtail-air-freight@hackloop.mail"


def b64(s):
    return base64.b64encode(s.encode() if isinstance(s, str) else s).decode()


def send(mid, sender, atts=(), subject="Tariff update", body="Please find our new tariff attached."):
    main.process(main.mailbox.normalize({"id": mid, "from": sender, "subject": subject, "body": body,
                                         "attachments": list(atts)}))
    rows = db.con().execute("SELECT kind, data FROM events WHERE mail_id=? AND kind LIKE 'tariff%'", (mid,))
    return [(r["kind"], json.loads(r["data"])) for r in rows]


def yt_total():
    return next(o for o in price.options("MUC", "LAX", 230, 1.0) if o["airline"] == "Yellowtail Air Freight")["total"]


class TestTariffMail(unittest.TestCase):
    def setUp(self):
        price.OVERRIDES = os.environ["TARIFF_OVERRIDES"]       # another test may have imported price first
        tariff_mail.INBOX = os.path.join(TMP, "tariffs_in")
        if os.path.exists(os.environ["TARIFF_OVERRIDES"]):
            os.remove(os.environ["TARIFF_OVERRIDES"])
        price._TARIFFS[:] = price._load()

    def test_routed_as_tariff(self):
        m = main.mailbox.normalize({"id": 1, "from": YT, "subject": "x", "body": "y",
                                    "attachments": [{"filename": "a.txt"}]})
        self.assertEqual(main.route(m, config.OUR_ADDRESS), "tariff")

    def test_new_rates_apply_immediately(self):
        before = yt_total()
        cheaper = TXT.replace("MUC-LAX              5  EUR 82.00   EUR 3.12  EUR 2.28  EUR 1.73",
                              "MUC-LAX              5  EUR 82.00   EUR 3.12  EUR 2.28  EUR 1.50")
        self.assertNotEqual(cheaper, TXT)
        ev = send(775001, YT, [{"filename": "yellowtail-2026-11-v2.txt", "content_base64": b64(cheaper)}])
        self.assertEqual(ev[-1][0], "tariff_loaded", ev)
        self.assertEqual(ev[-1][1]["changed"], ["MUC-LAX"])
        after = yt_total()
        self.assertLess(float(after), float(before))
        self.assertTrue(os.path.exists(os.environ["TARIFF_OVERRIDES"]))
        price._TARIFFS[:] = price._load()            # restart keeps the new prices
        self.assertEqual(yt_total(), after)

    def test_sheet_from_other_airline_rejected(self):
        ev = send(775002, "cobalt-skylift@hackloop.mail",
                  [{"filename": "t.txt", "content_base64": b64(TXT)}])
        self.assertEqual(ev[0][0], "tariff_rejected")
        self.assertIn("mail is from cobalt skylift", str(ev[0][1]["why"]).lower())

    def test_expired_sheet_rejected(self):
        old = TXT.replace("30.11.2026", "31.10.2026").replace("01.11.2026", "01.10.2026")
        ev = send(775003, YT, [{"filename": "old.txt", "content_base64": b64(old)}])
        self.assertEqual(ev[0][0], "tariff_rejected")
        self.assertIn("expired", str(ev[0][1]["why"]))

    def test_future_sheet_not_applied_yet(self):
        dec = TXT.replace("01.11.2026", "01.12.2026").replace("30.11.2026", "31.12.2026")
        ev = send(775004, YT, [{"filename": "dec.txt", "content_base64": b64(dec)}])
        self.assertIn("valid only from", str(ev[0][1]["why"]))

    def test_image_needs_human(self):
        ev = send(775005, YT, [{"filename": "scan.jpg", "content_base64": b64(b"\xff\xd8\xff")}])
        self.assertIn("needs a human", str(ev[0][1]["why"]))

    def test_broken_rates_rejected(self):
        bad = TXT.replace("EUR 3.12  EUR 2.28  EUR 1.73", "EUR 3.12  EUR 2.28  EUR 9.73")
        ev = send(775006, YT, [{"filename": "bad.txt", "content_base64": b64(bad)}])
        self.assertEqual(ev[0][0], "tariff_rejected")
        self.assertIn("not descending", str(ev[0][1]["why"]))

    def test_tariff_in_body(self):
        ev = send(775007, YT, [], subject="Yellowtail tariff", body=TXT)
        self.assertEqual(ev[-1][0], "tariff_loaded", ev)

    @unittest.skipUnless(__import__("importlib").util.find_spec("openpyxl"), "openpyxl not installed")
    def test_xlsx_attachment(self):
        data = open(os.path.join(KIT, "vega-skyfreight-tariff-2026-11.xlsx"), "rb").read()
        ev = send(775008, "vega-skyfreight@hackloop.mail", [{"filename": "vega.xlsx", "content_base64": b64(data)}])
        self.assertEqual(ev[-1][0], "tariff_loaded", ev)


if __name__ == "__main__":
    unittest.main()
