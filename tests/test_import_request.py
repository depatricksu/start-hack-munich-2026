"""5U, 22 Nov 08:01 (request 47987): the first IMPORT, Tokyo to Hamburg. No sheet, no portal lane and no airline flies
into Germany for us, so the right answer is an honest "we cannot quote this", not silence (5U: accepted).
Run: python -m unittest tests.test_import_request -v"""
import json, os, tempfile, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, imports, main  # noqa: E402

CUSTOMER = "import-desk@import-test.mail"                      # its own address: one DB for the whole suite
REAL = ("Hi,\n\nCould you quote an all-in price in EUR for an airport-to-airport air import from Tokyo airport (NRT), JP, to "
        "Hamburg airport (HAM), Germany? Our supplier will hand over the goods at NRT, and we’re the receiver in Germany.\n\n"
        "The furniture samples will be ready on 2026-11-26: 6 pieces, 1741 kg gross, 12.61 cbm.\n\nThanks!\n\nMira Petersen\nNordlicht Audio")


def fields(origin, destination, **more):
    f = {"origin": origin, "destination": destination, "pickup_postcode": None, "weight_kg": 1741, "volume_cbm": 12.61, "pieces": [],
         "prefer": "none", "kind": "new_request", "language": "en", "missing": [], "customer_first_name": "Mira",
         "reply": "Hi Mira,\n\n{PRICE} with {AIRLINE}, {TRANSIT_DAYS} days.\n\nLena"}
    f.update(more)
    return f


def run(tid, f, body=REAL, subject="Air import quote NRT to HAM"):
    m = main.mailbox.normalize({"id": tid, "from": CUSTOMER, "subject": subject, "body": body})
    with mock.patch.object(main.llm, "extract", return_value=(f, {"fake": True})), mock.patch("sourcing.portal.options", return_value=[]):
        main.process(m)
    return db.session(tid)


def sent(tid, kinds=("mail_out_dry_run", "mail_out")):
    rows = db.con().execute("SELECT kind, data FROM events WHERE thread_id=?", (tid,)).fetchall()
    return [json.loads(r["data"]) for r in rows if r["kind"] in kinds]


class Lane(unittest.TestCase):
    def test_the_real_request_is_an_import(self):
        self.assertEqual(imports.lane(fields("NRT", "HAM"), {"body": REAL}), ("NRT", "HAM"))
        self.assertEqual(imports.lane(fields("PVG", "FRA"), {"body": "Please quote an import to FRA (Frankfurt) from PVG, 300 kg, 1.2 cbm."}), ("PVG", "FRA"))
        self.assertEqual(imports.lane(fields("NRT", "HAM", language="de"), {"body": "Bitte um ein Angebot für Luftfracht von Tokio (NRT) nach Hamburg (HAM), 300 kg."}), ("NRT", "HAM"))

    def test_an_export_called_the_buyers_import_is_not(self):
        """Requests 36828 and 43639, live: both were normal exports and were quoted."""
        body = ("I’m arranging air freight from Germany for our buyer’s import into Vietnam. Could you quote your cheapest option for "
                "this import shipment to SGN (Ho Chi Minh City, VN)? Ready at our site in 51341.")
        self.assertIsNone(imports.lane(fields("CGN", "SGN"), {"body": body}))
        self.assertIsNone(imports.lane(fields("MUC", "LAX"), {"body": "MUC to LAX import quote: we deliver to MUC ourselves, 350 kg."}))

    def test_anything_less_clear_is_not_declined(self):
        self.assertIsNone(imports.lane(fields("VIE", "HAM"), {"body": "RE: FW: VIENNA AIRPORT - HAM / 32 PLT. Please quote Hamburg to Vienna, 400 kg."}))  # lane not said that way
        self.assertIsNone(imports.lane(fields("NRT", "HAM", pickup_postcode="20095"), {"body": REAL}))       # pickup in Germany: an export, misread
        self.assertIsNone(imports.lane(fields("NRT", "LAX"), {"body": "from Tokyo (NRT) to Los Angeles (LAX)"}))   # does not end in Germany
        self.assertIsNone(imports.lane(fields(None, "HAM"), {"body": REAL}))
        self.assertIsNone(imports.lane(fields("NRT", "HAM", shipments=[{}, {}]), {"body": REAL}))


class Decline(unittest.TestCase):
    def test_the_customer_gets_an_honest_answer_and_no_price(self):
        s = run(940117, fields("NRT", "HAM"))
        self.assertEqual(s["status"], "lost")
        self.assertTrue(s["note"].startswith("import_declined: NRT to HAM"), s["note"])
        mails = sent(940117)
        self.assertEqual(len(mails), 1)
        body = mails[0]["body"]
        for text in ("Hi Mira,", "this is an import from NRT into HAM", "we arrange air export out of German airports", "I cannot give you a price"):
            self.assertIn(text, body)
        self.assertNotRegex(body, r"\d[\d.,]*\s*EUR")                              # never a price
        self.assertNotIn("{", body)
        self.assertEqual(sent(940117, ("bid_mail_out_dry_run", "bid_mail_out")), [])   # nobody is asked: no source flies it
        self.assertEqual(json.loads(db.con().execute("SELECT data FROM events WHERE thread_id=940117 AND kind='import_declined'").fetchone()["data"])["sent"], True)

    def test_in_german_when_they_wrote_german(self):
        body = "Guten Tag,\n\nbitte um ein Angebot für Luftfracht von Tokio (NRT) nach Hamburg (HAM), 6 Packstücke, 1741 kg, 12,61 cbm.\n\nMira Petersen"
        run(940218, fields("NRT", "HAM", language="de"), body=body)
        self.assertIn("Das ist ein Import von NRT nach HAM", sent(940218)[0]["body"])

    def test_an_unclear_foreign_origin_still_goes_to_a_person(self):
        s = run(940319, fields("VIE", "HAM"), body="Please quote Hamburg to Vienna, 400 kg, 2 cbm.", subject="Quote")
        self.assertEqual(s["status"], "needs_human")
        self.assertEqual(sent(940319), [])


if __name__ == "__main__":
    unittest.main()
