"""Attachments of customer mails (core/attachments.py) and the odd-attachment alarm. Run: python -m unittest tests.test_attachments"""
import base64, json, os, tempfile, unittest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import alarm, attachments, config, db, main  # noqa: E402


def att(name, data):
    return {"id": name, "filename": name, "content_base64": base64.b64encode(data).decode()}


def rfq(i, body, files):
    m = main.mailbox.normalize({"id": i, "from": "buyer%d@acme.mail" % i, "subject": "Quote", "body": body,
                                "attachments": files})
    main.process(m)
    return m, db.session(i)


BODY = "please quote 90 kg, 0.4 cbm HAM to BOG, industrial adhesives, general cargo"
PL = b"Packing list\nGross weight: 90 kg\nDangerous goods: UN1133, Class 3, Adhesives\n"


class TestAttachments(unittest.TestCase):
    def test_every_file_is_read_and_logged(self):
        m, s = rfq(8810001, BODY, [att("PL_1.txt", PL), att("photo.jpg", b"\xff\xd8\xff\xe0 not text")])
        files = {f["filename"]: f for f in m["attachments_text"]}
        self.assertTrue(files["PL_1.txt"]["readable"])
        self.assertIn("UN1133", files["PL_1.txt"]["text"])
        self.assertFalse(files["photo.jpg"]["readable"])
        ev = db.con().execute("SELECT data FROM events WHERE kind='attachments' AND mail_id=8810001").fetchone()
        self.assertEqual(len(json.loads(ev["data"])["files"]), 2)
        self.assertNotIn('"text"', ev["data"])                      # the log keeps a preview, not the whole file

    def test_dg_in_the_file_is_quoted_with_the_paragraph(self):
        _, s = rfq(8810002, BODY, [att("PL_1.txt", PL)])
        self.assertEqual(s["status"], "quoted", s["note"])
        self.assertIn("UN1133", s["reply"])

    def test_unreadable_file_raises_one_alarm(self):
        rfq(8810003, BODY, [att("scan.jpg", b"\xff\xd8\xff\xe0 binary")])
        found = [a for a in alarm.find() if a[0] == "att-8810003"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], "odd_attachment")
        self.assertIn("scan.jpg", found[0][3])

    def test_readable_known_file_raises_no_alarm(self):
        rfq(8810004, BODY, [att("PL_1.txt", PL)])
        self.assertFalse([a for a in alarm.find() if a[0] == "att-8810004"])

    def test_llm_gets_the_text_only_when_switched_on(self):
        m = {"id": 1, "body": "hello", "attachments_text": [{"filename": "PL.txt", "readable": True, "text": "Gross weight: 140 kg"}]}
        self.assertEqual(attachments.for_llm(m)["body"], "hello")
        old, config.ATTACH_LLM = config.ATTACH_LLM, True
        try:
            body = attachments.for_llm(m)["body"]
        finally:
            config.ATTACH_LLM = old
        self.assertIn("Gross weight: 140 kg", body)
        self.assertIn("PL.txt", body)
        self.assertEqual(m["body"], "hello")                        # the stored mail is never changed

    def test_mail_without_files_is_untouched(self):
        m, s = rfq(8810005, "please quote 90 kg, 0.4 cbm HAM to BOG", [])
        self.assertNotIn("attachments_text", m)
        self.assertEqual(s["status"], "quoted")


if __name__ == "__main__":
    unittest.main()
