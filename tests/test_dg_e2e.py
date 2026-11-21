"""End to end: a customer RFQ whose ATTACHMENT declares dangerous goods goes through the whole clerk (intake ->
attachment text -> gate -> sheet price -> finalize -> dg paragraph -> humanize) and the quote asks for the DG documents
with the price unchanged. Owner: Riky. No network, no key: DRY_RUN, LLM_FAKE, temp DB, sheet prices only.
5U's 17:00 change (rounds 10, 11 lost): the mail says 'general cargo, non-dangerous', the packing list says UN1133.
"""
import base64, io, json, os, re, tempfile, unittest, zipfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "e2e.db")
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")
os.environ["FIVEU_API_KEY"] = ""
os.environ["DG_OCR_WARMUP"] = "0"

from core import config, db, main  # noqa: E402


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def xlsx(*rows):
    strings = [c for r in rows for c in r]
    shared = "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>"
    i, xml = 0, []
    for r in rows:
        cells = []
        for _ in r:
            cells.append(f'<c t="s"><v>{i}</v></c>')
            i += 1
        xml.append("<row>" + "".join(cells) + "</row>")
    sheet = "<worksheet><sheetData>" + "".join(xml) + "</sheetData></worksheet>"
    return _zip({"xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": sheet})


def docx(text):
    return _zip({"word/document.xml": f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"})


def pdf(text):
    """A tiny one-page PDF with the text in an uncompressed stream (readable by PDFKit, pdftotext or the fallback)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % n + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


BODY = ("Hello,\n\nplease quote the cheapest air freight option from FRA to ORD (Chicago, US) for 120 kg, 0.9 cbm, "
        "industrial adhesives. The goods are general cargo, non-dangerous. Our packing list is attached.\n\n"
        "Kind regards\nAnna Sonnberg\nSonnberg GmbH")


class EndToEnd(unittest.TestCase):
    n = 990000

    def run_mail(self, filename, data, body=BODY):
        EndToEnd.n += 1
        mid = EndToEnd.n
        raw = {"id": mid, "from": "anna@sonnberg.mail", "subject": "Air freight quote FRA-ORD", "body": body,
               "attachments": [{"filename": filename, "content_base64": base64.b64encode(data).decode()}] if data else []}
        config.DRY_RUN = True
        main.process(main.mailbox.normalize(raw))
        main.tick()
        return db.session(mid) or {}

    def assert_dg_quote(self, s, un):
        self.assertEqual(s.get("status"), "quoted", s.get("note"))
        self.assertIn("dangerous goods documents", s["reply"])
        self.assertIn(un, s["reply"])
        chosen = json.loads(s["chosen"])
        self.assertIn(chosen["total"], s["reply"].replace(",", ""))          # the price in the mail is the chosen total
        fields = json.loads(s["fields"])
        self.assertEqual((fields.get("dg") or {}).get("un"), un)

    def test_xlsx_packing_list(self):
        s = self.run_mail("PL_53839.xlsx", xlsx(["Description", "Industrial adhesives"],
                                                ["Dangerous goods:", "UN1133, Class 3, Adhesives"]))
        self.assert_dg_quote(s, "UN1133")

    def test_docx_sli(self):
        self.assert_dg_quote(self.run_mail("SLI.docx", docx("Dangerous goods: UN1950, Class 2.1, Aerosols")), "UN1950")

    def test_pdf_sli(self):
        self.assert_dg_quote(self.run_mail("SLI.pdf", pdf("Dangerous goods: UN1133, Class 3, Adhesives")), "UN1133")

    def test_packing_list_that_says_no_dg_gets_a_plain_quote(self):
        s = self.run_mail("PL.xlsx", xlsx(["Description", "Industrial adhesives"], ["Dangerous goods:", "No"]))
        self.assertEqual(s.get("status"), "quoted", s.get("note"))
        self.assertNotIn("dangerous goods documents", s["reply"])

    def test_no_attachment_plain_quote(self):
        s = self.run_mail(None, None)
        self.assertEqual(s.get("status"), "quoted", s.get("note"))
        self.assertNotIn("dangerous goods documents", s["reply"])


if __name__ == "__main__":
    unittest.main()
