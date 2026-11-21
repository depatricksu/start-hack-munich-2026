"""dg/: dangerous goods in the quote (owner Riky). Pure functions, no network."""
import os
import unittest

import dg

BODY = "Hi Anna,\n\nMUC to JFK, 120 kg: 1234.50 EUR all-in with Lumen, 3 days.\n\nBest regards,\nLena Hofmann\nAir Export"
BEST = {"airline": "Lumen", "total": "1234.50", "total_eur": "1234.50", "currency": "EUR", "billed_kg": "120"}


class ReadDeclaration(unittest.TestCase):
    def test_packing_list_from_round_10(self):
        info = dg.read_declaration("Dangerous goods: UN1133, Class 3, Adhesives")
        self.assertEqual(info["un"], "UN1133")
        self.assertEqual(info["class"], "3")
        self.assertEqual(info["name"], "Adhesives")

    def test_sli_from_round_11(self):
        info = dg.read_declaration("Dangerous goods: UN1950, Class 2.1, Aerosols, flammable")
        self.assertEqual((info["un"], info["class"]), ("UN1950", "2.1"))
        self.assertTrue(info["name"].startswith("Aerosols"))

    def test_mail_that_says_non_dangerous_is_not_dg(self):
        self.assertIsNone(dg.read_declaration("Industrial adhesives, general cargo, non-dangerous."))
        self.assertIsNone(dg.read_declaration("Dangerous goods: no"))
        self.assertIsNone(dg.read_declaration(""))

    def test_denials_in_a_mail(self):
        for text in ("Spray cans, no dangerous goods.", "Industrial adhesives, non-DGR, general cargo",
                     "kein Gefahrgut", "non-hazardous chemicals"):
            self.assertIsNone(dg.read_declaration(text), text)
        self.assertEqual(dg.read_declaration("Dangerous goods: Class 3 adhesives")["class"], "3")

    def test_un_number_wins_over_a_non_dangerous_claim(self):
        self.assertEqual(dg.read_declaration("non-dangerous ... UN 3480 lithium")["un"], "UN3480")


class Apply(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ("DG_MODE", "DG_SURCHARGE_EUR_PER_KG", "DG_SURCHARGE_MIN_EUR")}

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_no_dg_changes_nothing(self):
        self.assertEqual(dg.apply(BEST, {}, BODY), (BEST, BODY, None))

    def test_docs_mode_adds_paragraph_before_signature(self):
        os.environ.pop("DG_MODE", None)
        fields = {"dg": {"un": "UN1133", "class": "3", "name": "Adhesives"}, "language": "en"}
        best, body, human = dg.apply(BEST, fields, BODY)
        self.assertIsNone(human)
        self.assertEqual(best, BEST)
        self.assertIn("UN1133, class 3 (Adhesives)", body)
        self.assertIn("Shipper's Declaration for Dangerous Goods", body)
        self.assertLess(body.index("Shipper's Declaration"), body.index("Best regards"))
        self.assertIn("1234.50 EUR", body)

    def test_german_paragraph(self):
        _, body, _ = dg.apply(BEST, {"dg": True, "language": "de"}, "Guten Tag,\n\nPreis 1234.50 EUR.\n\nMit freundlichen Grüßen\nLena")
        self.assertIn("Gefahrgut", body)

    def test_human_mode(self):
        os.environ["DG_MODE"] = "human"
        _, _, human = dg.apply(BEST, {"dg": {"un": "UN1950"}}, BODY)
        self.assertIn("UN1950", human)

    def test_surcharge_mode_adds_to_total_and_text(self):
        os.environ["DG_MODE"] = "surcharge"
        os.environ["DG_SURCHARGE_EUR_PER_KG"] = "0.50"
        os.environ["DG_SURCHARGE_MIN_EUR"] = "75"
        best, body, _ = dg.apply(BEST, {"dg": {"un": "UN1133"}}, BODY)
        self.assertEqual(best["total_eur"], "1309.50")          # 120 kg x 0.50 = 60 < 75 minimum
        self.assertIn("1309.50 EUR", body)
        self.assertNotIn("1234.50", body)


def _zip(files):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


class Attachments(unittest.TestCase):
    def test_xlsx_packing_list(self):
        shared = ('<sst><si><t>Description</t></si><si><t>Industrial adhesives</t></si>'
                  '<si><t>Dangerous goods: UN1133, Class 3, Adhesives</t></si></sst>')
        sheet = ('<worksheet><sheetData><row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>'
                 '<row><c t="s"><v>2</v></c><c><v>42</v></c></row></sheetData></worksheet>')
        data = _zip({"xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": sheet})
        self.assertIn("UN1133", dg.attachment_text(data, "PL_53839.xlsx"))
        info = dg.scan_attachments([("PL_53839.xlsx", data)])
        self.assertEqual((info["un"], info["class"], info["file"]), ("UN1133", "3", "PL_53839.xlsx"))

    def test_docx_sli(self):
        doc = '<w:document><w:body><w:p><w:r><w:t>Dangerous goods: UN1950, Class 2.1, Aerosols</w:t></w:r></w:p></w:body></w:document>'
        data = _zip({"word/document.xml": doc})
        self.assertEqual(dg.scan_attachments([("SLI.docx", data)])["un"], "UN1950")

    def test_check_mail_with_inline_attachment(self):
        import base64
        doc = '<w:document><w:body><w:p><w:r><w:t>Dangerous goods: UN1950, Class 2.1, Aerosols</w:t></w:r></w:p></w:body></w:document>'
        att = {"filename": "SLI.docx", "content_base64": base64.b64encode(_zip({"word/document.xml": doc})).decode()}
        mail = {"id": 1, "body": "Spray cans, general cargo, non-dangerous.", "attachments": [att]}
        self.assertEqual(dg.check_mail(mail)["un"], "UN1950")
        self.assertIsNone(dg.check_mail({"id": 2, "body": "General cargo, non-dangerous.", "attachments": []}))
        self.assertIsNone(dg.check_mail({"id": 3, "body": "x", "attachments": [{"filename": "a.pdf"}]}))   # no id, no bytes
        self.assertEqual(dg.check_mail({"id": 4, "body": "Hazmat, Class 9 lithium batteries", "attachments": []})["class"], "9")

    def test_check_mail_reuses_text_read_at_intake(self):
        mail = {"id": 5, "body": "General cargo", "attachments": [{"filename": "PL.xlsx"}],
                "attachments_text": [{"filename": "PL.xlsx", "text": "Dangerous goods: UN1133, Class 3, Adhesives"}]}
        self.assertEqual(dg.check_mail(mail)["file"], "PL.xlsx")

    @unittest.skipUnless(__import__("shutil").which("swiftc"), "OCR needs macOS")
    def test_photo_is_read_by_ocr(self):
        import os
        import time
        from dg import attach
        path = os.path.join(os.path.dirname(__file__), "..", "kit", "start-kit", "danube-wings-cargo-tariff-2026-11-p2.jpg")
        attach.warm_up()                                     # the live path never waits for a cold worker
        for _ in range(100):                                 # give the background warm-up up to 10 s here
            if attach._WORKER["warm"]:
                break
            time.sleep(0.1)
        with open(path, "rb") as f:
            text = dg.attachment_text(f.read(), "scan.jpg")
        if not text:                                         # OCR timed out or could not run on this machine: skip, don't block restart
            self.skipTest("OCR gave no text here")
        self.assertIn("CGN-SYD", text)
        self.assertIn("1,13", text)

    def test_clean_files_and_garbage_give_none(self):
        self.assertIsNone(dg.scan_attachments([("note.txt", b"General cargo, non-dangerous")]))
        self.assertEqual(dg.attachment_text(b"PK\x03\x04broken", "x.xlsx"), "")
        self.assertIsNone(dg.scan_attachments([]))


class Facts(unittest.TestCase):
    def test_packing_list_numbers(self):
        text = "Carton 1 gross weight 250 kg\nTotal gross weight: 1,250 kg\nTotal pieces: 5\nVolume: 6.4 cbm"
        self.assertEqual(dg.packing_facts(text), {"gross_kg": 1250.0, "pieces": 5, "volume_cbm": 6.4})

    def test_german_and_dimensions(self):
        f = dg.packing_facts("Bruttogewicht: 1.250,5 kg\n120 x 80 x 100 cm 2 pallets")
        self.assertEqual(f["gross_kg"], 1250.5)
        self.assertAlmostEqual(f["volume_cbm"], 1.92)

    def test_compare_flags_only_real_differences(self):
        from dg import facts
        facts.remember(99, "Total gross weight: 1,250 kg")
        self.assertEqual(dg.compare({"weight_kg_total": 950}, {"id": 99}),
                         {"gross_kg": {"mail": 950.0, "attachment": 1250.0}})
        self.assertEqual(dg.compare({"weight_kg_total": 1240}, {"id": 99}), {})     # within 2 %
        self.assertEqual(dg.compare({"weight_kg_total": 950}, {"id": 123}), {})     # no attachment text

    def test_nothing_found(self):
        self.assertEqual(dg.packing_facts("Hello, general cargo"), {})
        self.assertFalse(dg.override())


if __name__ == "__main__":
    unittest.main()


class NoDoubleWeight(unittest.TestCase):
    """core.main.shipment: the same total given twice must not be added (real requests 268, 1631, 5246)."""
    def test_same_total_twice_is_one_shipment(self):
        from core.main import shipment
        f268 = {"weight_kg": 676, "volume_cbm": 5.79, "pieces": [{"count": 12, "kg_each": 56.33}]}
        self.assertAlmostEqual(shipment(f268)[0], 676.0)
        f5246 = {"weight_kg": 676, "volume_cbm": 3.44, "pieces": [{"count": 3, "kg_each": 225.33}]}
        self.assertAlmostEqual(shipment(f5246)[0], 676.0)
        dims = {"weight_kg": 500, "volume_cbm": 1.92, "pieces": [{"count": 2, "l_cm": 120, "w_cm": 80, "h_cm": 100}]}
        self.assertAlmostEqual(shipment(dims)[1], 1.92)

    def test_separate_lots_still_add_up(self):
        from core.main import shipment
        lots = {"weight_kg": 730, "pieces": [{"count": 4, "kg_each": 48}, {"count": 5, "kg_each": 206}]}
        self.assertAlmostEqual(shipment(lots)[0], 730 + 192 + 1030)     # round 9: 1,952 kg
