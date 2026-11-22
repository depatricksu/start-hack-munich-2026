"""history/: importing a forwarder's old mails and Excel registers, sorting, duplicates, search.
Run: python -m unittest tests.test_history"""
import json, os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from core import db, mailbox  # noqa: E402
from history import importer, find  # noqa: E402

OURS = "export@hofmann-spedition.de"


def mail(mid, frm, to, subject, body, date, reply_to=None, html=False):
    head = ["From: %s" % frm, "To: %s" % to, "Subject: %s" % subject, "Date: %s" % date]
    if mid:
        head.append("Message-ID: <%s>" % mid)
    if reply_to:
        head += ["In-Reply-To: <%s>" % reply_to, "References: <%s>" % reply_to]
    head.append("Content-Type: %s; charset=utf-8" % ("text/html" if html else "text/plain"))
    return "\n".join(head) + "\n\n" + body + "\n"


A1 = mail("a1@sonnberg", "Anna Sonnberg <anna.sonnberg@sonnberg-kaffee.de>", OURS, "Air freight quote to PVG",
          "Hello,\n\ncheapest air freight MUC to PVG please, 5 pieces, 540 kg, 1.33 cbm, machine parts.\n\nAnna Sonnberg",
          "Mon, 03 Mar 2025 09:02:00 +0100")
ARCHIVE = [
    A1,
    mail("a2@hofmann", "Lena Hofmann <%s>" % OURS, "anna.sonnberg@sonnberg-kaffee.de", "Re: Air freight quote to PVG",
         "Hi Anna,\n\nMeridian Freightways, 1,921.60 EUR all-in, about 3 days.\n\nLena", "Mon, 03 Mar 2025 10:15:00 +0100", "a1@sonnberg"),
    mail("a3@sonnberg", "Anna Sonnberg <anna.sonnberg@sonnberg-kaffee.de>", OURS, "Re: Air freight quote to PVG",
         "Great, please book it.\n\nAnna", "Mon, 03 Mar 2025 11:00:00 +0100", "a2@hofmann"),
    mail("a4@meridian", "meridian-freightways@hackloop.mail", OURS, "Booking BK-AW8CXJCM confirmed",
         "your booking BK-AW8CXJCM is confirmed.", "Mon, 03 Mar 2025 11:30:00 +0100"),
    # B: German, Outlook without reply headers, customer says no
    mail("b1@weber", "Thomas Weber <t.weber@weber-bau.de>", OURS, "Anfrage Luftfracht JFK",
         "Guten Morgen,\n\nbitte Angebot FRA nach JFK, 3 Kisten, 820 kg, 3,9 cbm.\n\nThomas Weber", "Tue, 11 Mar 2025 08:15:00 +0100"),
    mail("b2@hofmann", OURS, "t.weber@weber-bau.de", "AW: Anfrage Luftfracht JFK",
         "<p>Hallo Herr Weber,</p><p>Wayzata Air Cargo, <b>2.156,60 EUR</b> all-in.</p>", "Tue, 11 Mar 2025 09:00:00 +0100", html=True),
    mail("b3@weber", "Thomas Weber <t.weber@weber-bau.de>", OURS, "AW: AW: Anfrage Luftfracht JFK",
         "Danke, wir haben uns anders entschieden und buchen nicht.\n\nGruß Weber", "Wed, 12 Mar 2025 14:00:00 +0100"),
    # C: the same request sent twice, in two conversations
    mail("c1@brandt", "Jonas Brandt <jonas@brandt-optik.de>", OURS, "Quote ORD",
         "Hello, cheapest FRA to ORD, 300 kg, 1.5 cbm. Jonas Brandt", "Mon, 07 Apr 2025 10:00:00 +0200"),
    mail("c2@brandt", "Jonas Brandt <jonas@brandt-optik.de>", OURS, "Quote ORD - urgent",
         "Hello again, did you get my request? Cheapest FRA to ORD, 300 kg, 1.5 cbm. Jonas Brandt", "Tue, 08 Apr 2025 09:00:00 +0200"),
    # D: a request we never answered
    mail("d1@kessler", "Kessler <info@kessler-feinmechanik.de>", OURS, "Air freight HAM to BOG",
         "Dear Sir or Madam, please quote HAM to BOG, 630 kg, 3.96 cbm.", "Thu, 15 May 2025 16:00:00 +0200"),
    # a trucker answers about booking A (no customer in it): hangs on case A by the reference
    mail("t1@neckar", "neckarstrom-kurier@hackloop.mail", OURS, "Pickup BK-AW8CXJCM done",
         "Picked up today, delivered to MUC terminal for BK-AW8CXJCM.", "Tue, 04 Mar 2025 15:00:00 +0100"),
]
REGISTER_CSV = ("Datum;Kunde;Von;Nach;Gewicht;Preis;Währung;Airline;Buchungsnummer;Status\n"
                "03.03.2025;anna.sonnberg@sonnberg-kaffee.de;MUC;PVG;540;1.921,60;EUR;Meridian Freightways;BK-AW8CXJCM;geflogen\n"
                "11.03.2025;t.weber@weber-bau.de;FRA;JFK;820;2.156,60;EUR;Wayzata Air Cargo;;verloren\n"
                "20.01.2025;einkauf@alpen-pharma.de;STR;SIN;95;1.240,00;EUR;Solace Air Cargo;BK-OLD00042;geflogen\n"
                "20.01.2025;einkauf@alpen-pharma.de;STR;SIN;95;1.240,00;EUR;Solace Air Cargo;BK-OLD00042;geflogen\n")


class History(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = tempfile.mkdtemp()
        cls.dir = d
        with open(os.path.join(d, "old.mbox"), "w") as f:
            for m in ARCHIVE:
                f.write("From - Mon Jan  1 00:00:00 2025\n" + m.replace("\nFrom ", "\n>From ") + "\n")
        os.makedirs(os.path.join(d, "eml"))
        with open(os.path.join(d, "eml", "copy_of_a1.eml"), "w") as f:      # the same mail exported again
            f.write(A1)
        with open(os.path.join(d, "register.csv"), "w", encoding="utf-8") as f:
            f.write(REGISTER_CSV)
        head = ["Date", "Customer", "Origin", "Destination", "Weight kg", "Price", "Currency", "Carrier", "Status"]
        row = ["2025-02-10", "sales@nordlicht-audio.de", "CGN", "LIM", 1745, 4760, "EUR", "Xenon Cargo Airlines", "Delivered"]
        try:                                                   # the Excel register (openpyxl is in requirements.txt)
            import openpyxl
            wb = openpyxl.Workbook()
            wb.active.append(head)
            wb.active.append(row)
            sheet = os.path.join(d, "shipments.xlsx")
            wb.save(sheet)
        except ImportError:                                    # same row as a tab-separated export
            sheet = os.path.join(d, "shipments.tsv")
            with open(sheet, "w") as f:
                f.write("\t".join(head) + "\n" + "\t".join(map(str, row)) + "\n")
        cls.report = importer.run([os.path.join(d, "old.mbox"), os.path.join(d, "eml"), os.path.join(d, "register.csv"),
                                   sheet], ours=[OURS], quiet=True)
        cls.cases = {c["customer"]: dict(c) for c in importer.con().execute("SELECT * FROM archive_cases")}

    def test_report(self):
        r = self.report
        self.assertEqual(r["mails_read"], len(ARCHIVE) + 1)
        self.assertEqual(r["duplicate_mails"], 1)                       # A1 exported twice
        self.assertEqual(r["register_duplicate_rows"], 1)               # the alpen-pharma row twice
        self.assertEqual(r["rows_merged_into_mail_cases"], 2)           # Sonnberg (by BK) and Weber (by lane + weight)
        self.assertEqual(r["requests_sent_twice"], 1)                   # Brandt
        self.assertEqual(r["cases"], 7)                                 # A, B, C, C', D, alpen-pharma, nordlicht

    def test_cases_read_right(self):
        a = self.cases["anna.sonnberg@sonnberg-kaffee.de"]
        self.assertEqual((a["origin"], a["destination"], a["weight_kg"], a["status"]), ("MUC", "PVG", 540.0, "confirmed"))
        self.assertEqual((a["price"], a["airline"], a["booking_reference"]), ("1921.60", "Meridian Freightways", "BK-AW8CXJCM"))
        self.assertIn("register.csv row 2", a["sources"])
        b = self.cases["t.weber@weber-bau.de"]
        self.assertEqual((b["origin"], b["destination"], b["status"], b["price"]), ("FRA", "JFK", "lost", "2156.60"))
        self.assertEqual(self.cases["info@kessler-feinmechanik.de"]["status"], "open")
        self.assertEqual(self.cases["einkauf@alpen-pharma.de"]["status"], "confirmed")
        self.assertEqual(self.cases["sales@nordlicht-audio.de"]["airline"], "Xenon Cargo Airlines")

    def test_threads_and_carrier_mails(self):
        a = self.cases["anna.sonnberg@sonnberg-kaffee.de"]
        roles = [r[0] for r in importer.con().execute("SELECT role FROM archive_mails WHERE case_key=? ORDER BY date", (a["key"],))]
        self.assertEqual(roles.count("customer"), 2)
        self.assertIn("carrier", roles)                                  # airline confirmation + trucker hang on case A
        b = self.cases["t.weber@weber-bau.de"]
        n = importer.con().execute("SELECT count(*) FROM archive_mails WHERE case_key=?", (b["key"],)).fetchone()[0]
        self.assertEqual(n, 3)                                           # Outlook 'AW: AW:' joined by subject

    def test_reimport_changes_nothing(self):
        before = importer.con().execute("SELECT count(*) FROM archive_cases").fetchone()[0]
        importer.run([os.path.join(self.dir, "old.mbox"), os.path.join(self.dir, "register.csv")], ours=[OURS], quiet=True)
        self.assertEqual(importer.con().execute("SELECT count(*) FROM archive_cases").fetchone()[0], before)

    def test_search(self):
        keys = lambda words: [c["customer"] for c in find.search(words) if c["where"] == "archive"]
        self.assertEqual(keys(["weber", "JFK"]), ["t.weber@weber-bau.de"])
        self.assertEqual(keys(["BK-AW8CXJCM"]), ["anna.sonnberg@sonnberg-kaffee.de"])
        self.assertEqual(keys(["2025-03", "540kg"]), ["anna.sonnberg@sonnberg-kaffee.de"])
        self.assertEqual(keys(["pharma", "SIN"]), ["einkauf@alpen-pharma.de"])
        self.assertEqual(len(keys(["brandt"])), 2)

    def test_agent_answers_about_an_old_booking(self):
        from booking import tracking
        m = mailbox.normalize({"id": 7770001, "from": "tracking@hackloop.mail", "subject": "Status of booking BK-OLD00042",
                               "body": "What happened to booking BK-OLD00042?"})
        db.save_mail(m)
        tracking.handle(m)
        out = [json.loads(r[0]) for r in db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind LIKE 'mail_out%'", (7770001,))]
        self.assertIn("found this shipment in our archive", out[-1]["body"])
        self.assertIn("STR to SIN", out[-1]["body"])


if __name__ == "__main__":
    unittest.main()
