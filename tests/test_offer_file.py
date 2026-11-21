"""5U, 21 Nov 23:36 (round 76, rejected no_pdf_offer): "Please attach your offer as a PDF to your reply"."""
import base64, io, os, tempfile, unittest, zipfile
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import config, db, mailbox, offer_file  # noqa: E402

ASK = ("Hello,\n\nCould you please quote the fastest air freight option to DFW (Dallas, US)? 5 pieces, 65 kg, 0.37 cbm.\n\n"
       "Please attach your offer as a PDF to your reply, as our purchasing department needs it for filing.\n\nThank you.")
BEST = {"airline": "Lumen Air Cargo", "origin": "CGN", "destination": "DFW", "transit_days": 1, "total": "408.55",
        "currency": "EUR", "billed_kg": "65.0", "trucker": "Sternmeile Logistik"}
FIELDS = {"weight_kg_total": 65.0, "volume_cbm_total": 0.37, "pickup_postcode": "53345", "language": "en"}
SESSION = {"customer": "deniz@rheintal.mail", "subject": "Air freight quote to DFW \u2013 fastest option"}
BODY = "Hi Deniz,\n\nLumen Air Cargo is the fastest: 408.55 EUR all-in, about 1 day.\n\nShall I book it?\n\nBest regards\nLena Hofmann\nAir Export"


class Asked(unittest.TestCase):
    def test_what_the_customer_asks_our_offer_in(self):
        self.assertEqual(offer_file.requested(ASK), {"pdf"})
        self.assertEqual(offer_file.requested("Bitte senden Sie uns Ihr Angebot als PDF im Anhang."), {"pdf"})
        self.assertEqual(offer_file.requested("Merci de joindre votre offre en PDF."), {"pdf"})
        self.assertEqual(offer_file.requested("Please send your quotation as a Word document."), {"docx"})
        self.assertEqual(offer_file.requested("请以PDF附件形式发送报价。"), {"pdf"})

    def test_their_own_file_is_not_a_request(self):
        said = "please find our request for an air freight quotation attached, as a PDF file (quotation-request.pdf)."
        self.assertEqual(offer_file.requested(said), set())
        self.assertEqual(offer_file.requested(said + "\n\n--- attached file: quotation-request.pdf ---\nPlease send your offer as PDF"), set())

    def test_no_attachments_please(self):
        self.assertTrue(offer_file.refused("Our mail server strips files: no attachments please, the price in the mail text."))
        self.assertEqual(offer_file.build(1, SESSION, BEST, FIELDS, BODY, "No attachments please."), ([], set()))


class File(unittest.TestCase):
    def test_every_quote_carries_a_pdf_with_the_price_in_plain_text(self):
        files, asked = offer_file.build(21453, SESSION, BEST, FIELDS, BODY, "please quote 65 kg CGN to DFW")
        self.assertEqual(asked, set())
        self.assertEqual([f["filename"] for f in files], ["offer-GOOGLE-21453.pdf"])
        data = base64.b64decode(files[0]["content_base64"])
        self.assertTrue(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"(ALL-IN PRICE: 408.55 EUR) Tj", data)                  # uncompressed: any extractor finds it
        self.assertIn(b"Lumen Air Cargo", data)
        self.assertEqual(files[0]["content_type"], "application/pdf")

    def test_the_xref_table_points_at_the_objects(self):
        data = offer_file.pdf(["OFFER GOOGLE-1", "ALL-IN PRICE: 1.00 EUR"] + ["line %d" % i for i in range(120)])   # 3 pages
        start = int(data.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
        self.assertTrue(data[start:].startswith(b"xref"))
        rows = data[start:].split(b"\n")[3:]
        for n, row in enumerate(rows[:6], 1):
            self.assertTrue(data[int(row[:10]):].startswith(b"%d 0 obj" % n), row)
        self.assertEqual(data.count(b"/Type /Page "), 3)

    def test_word_when_they_ask_for_word(self):
        files, asked = offer_file.build(7, SESSION, BEST, FIELDS, BODY, "Please send your quotation as a Word document.")
        self.assertEqual(asked, {"docx"})
        names = {f["filename"].rsplit(".", 1)[1]: f for f in files}
        self.assertEqual(set(names), {"docx", "pdf"})
        z = zipfile.ZipFile(io.BytesIO(base64.b64decode(names["docx"]["content_base64"])))
        self.assertIn("ALL-IN PRICE: 408.55 EUR", z.read("word/document.xml").decode())

    def test_a_mail_in_another_script_keeps_a_clean_file(self):
        lines = offer_file.lines(9, SESSION, BEST, FIELDS, "你好，全包价格为 408.55 EUR。")
        self.assertIn("ALL-IN PRICE: 408.55 EUR", lines)
        self.assertFalse(any("?" in ln for ln in lines))

    def test_the_mail_says_so_only_when_asked(self):
        self.assertEqual(offer_file.say_so(BODY, set(), "en"), BODY)
        said = offer_file.say_so(BODY, {"pdf"}, "en")
        self.assertIn("Our offer is attached as PDF for your files.\n\nBest regards\nLena Hofmann", said)
        self.assertIn("als PDF im Anhang", offer_file.say_so(BODY, {"pdf"}, "de"))


class Send(unittest.TestCase):
    def test_the_file_goes_into_the_payload_and_only_its_name_into_the_log(self):
        sent = []
        def api(method, path, body=None, params=None, timeout=20):
            sent.append(body)
            return 201, {"id": 1}
        files, _ = offer_file.build(8850001, SESSION, BEST, FIELDS, BODY, ASK)
        with mock.patch.object(mailbox, "api", api), mock.patch.object(config, "DRY_RUN", False):
            self.assertTrue(mailbox.send("deniz@rheintal.mail", "Re: x", BODY, in_reply_to=8850001, thread_id=8850001, attachments=files))
        self.assertEqual(sent[0]["attachments"][0]["filename"], "offer-GOOGLE-8850001.pdf")
        ev = db.con().execute("SELECT data FROM events WHERE kind='mail_out' AND thread_id=8850001").fetchone()["data"]
        self.assertIn("offer-GOOGLE-8850001.pdf", ev)
        self.assertNotIn("content_base64", ev)

    def test_a_refused_file_never_costs_the_quote(self):
        calls = []
        def api(method, path, body=None, params=None, timeout=20):
            calls.append("attachments" in body)
            return (422, {"detail": "bad attachment"}) if "attachments" in body else (201, {"id": 2})
        files, _ = offer_file.build(8850002, SESSION, BEST, FIELDS, BODY, ASK)
        with mock.patch.object(mailbox, "api", api), mock.patch.object(config, "DRY_RUN", False):
            self.assertTrue(mailbox.send("deniz@rheintal.mail", "Re: x", BODY, in_reply_to=8850002, thread_id=8850002, attachments=files))
        self.assertEqual(calls, [True, False])


if __name__ == "__main__":
    unittest.main()
