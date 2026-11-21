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
