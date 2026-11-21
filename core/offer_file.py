"""The quote as a file attached to our reply. Standard library only.

5U, 21 Nov 23:36 (round 76, rejected no_pdf_offer): "Please attach your offer as a PDF to your reply, as our
purchasing department needs it for filing." We answered in the mail text only and the customer wrote back "I did not
receive a PDF with your price in it. We will therefore not go ahead."

Every quote now carries the offer as a PDF (a forwarder's normal offer sheet: route, shipment, airline, transit time,
the all-in price, then the text of the mail). If the customer asks for another format (Word, text file) that one is
attached too. A customer who says "no attachments please" gets none.

    files, asked = offer_file.build(tid, session, best, fields, body, request_text)
    mailbox.send(..., attachments=files)
"""
import base64, datetime, io, re, textwrap, zipfile

# "attach YOUR offer as a PDF" and "attach THE offer as a PDF when you reply" (round 78 said "the": the file went out,
# but the mail did not mention it). "Our request is attached as a PDF file" has neither an offer word nor a reply word.
OURS = (r"(?:your|the|an?|ihr\w*|das|ein|votre|vos|l'|une?|vostr\w+|la|un[ao]?|tu[ao]?|su|sus|uw|de|een|您的|贵司|貴社)\s*(?:\w+\s+){0,2}?(?:offer|quot\w*|price|reply|answer|response|"
        r"angebot\w*|preis\w*|antwort|offre|devis|prix|tarif|r[ée]ponse|offerta|preventivo|prezzo|risposta|oferta|cotizaci[óo]n|"
        r"precio|respuesta|offerte|prijs)|报价|報價|見積")
# A sentence about THEIR file is never a wish for ours: "please find our request for an air freight quotation attached,
# as a Word document (quotation-request.docx)".
THEIRS = re.compile(r"(?:our|my|unsere?\w*|meine?\w*|notre|nos|nostr\w+|nuestr\w+)\s+(?:\w+\s+){0,2}?(?:request|rfq|inquiry|enquiry|"
                    r"anfrage|demande|richiesta|solicitud)|please find|find (?:the )?attached|i recorded|anbei|im anhang finden|"
                    r"ci-joint|veuillez trouver|in allegato trov|adjunt[oa] (?:encontrar|le env)", re.I)
FORMATS = (("docx", re.compile(r"(?<![a-z])(?:word|docx?)(?![a-z])", re.I)),
           ("txt", re.compile(r"\btext[\s-]?(?:file|datei)\b|\btextdatei\b|\b\.?txt\b|fichier texte|file di testo|archivo de texto", re.I)),
           ("pdf", re.compile(r"(?<![a-z])pdf(?![a-z])", re.I)))     # no \b: in 以PDF附件 the neighbours are letters too
NO_FILES = re.compile(r"\bno attachments?\b|without (?:any )?attachments?|do not (?:send|attach) (?:any )?(?:files?|attachments?)|"
                      r"\bkeine? (?:anh[äa]nge?|dateien?)\b|\bohne anhang\b|sans pi[èe]ce[\s-]jointe|pas de pi[èe]ce[\s-]jointe|"
                      r"senza allegat\w+|nessun allegato|sin (?:archivos? )?adjuntos?", re.I)
ATTACHED = {"en": "Our offer is attached as %s for your files.", "de": "Unser Angebot finden Sie als %s im Anhang.",
            "fr": "Vous trouverez notre offre en pièce jointe (%s).", "it": "In allegato trova la nostra offerta (%s).",
            "es": "Adjunto encontrará nuestra oferta (%s)."}
FORMAT_NAME = {"pdf": "PDF", "docx": "Word", "txt": "TXT"}
MIME = {"pdf": "application/pdf", "txt": "text/plain; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def own_words(request_text):
    """The customer's own mail, without the text of files we appended (core/attachments.inline_request)."""
    return (request_text or "").split("\n--- attached file:")[0]


def requested(request_text):
    """Formats the customer asks OUR offer in: {"pdf"}, {"docx"}, ... Empty when they did not ask."""
    out, ours = set(), re.compile(OURS, re.I)
    for sentence in re.split(r"(?<=[.!?。！？])\s+|\n", own_words(request_text)):
        if ours.search(sentence) and not THEIRS.search(sentence):
            out |= {name for name, rx in FORMATS if rx.search(sentence)}
    return out


def refused(request_text):
    return bool(NO_FILES.search(own_words(request_text)))


def _latin(s):
    """Text a standard PDF font can show. Anything else (Chinese, Polish ł) becomes '?': callers pass English then."""
    return (s or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"') \
        .replace("–", "-").replace("—", "-").replace("→", "->").replace(" ", " ")


def showable(s):
    try:
        _latin(s).encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def lines(tid, session, best, fields, body, today=None):
    """The offer as plain lines: head, facts, the all-in price, then the mail text."""
    day = (today or datetime.date.today()).strftime("%d %b %Y")
    route = "%s - %s" % (best.get("origin") or fields.get("origin") or "?", best.get("destination") or fields.get("destination") or "?")
    kg, cbm = fields.get("weight_kg_total"), fields.get("volume_cbm_total")
    out = ["OFFER GOOGLE-%s" % tid, "Date: %s" % day, "From: Lena Hofmann, Air Export, google@hackloop.mail",
           "To: %s" % (session.get("customer") or ""), "Your request: %s" % _latin(session.get("subject") or ""), "",
           "Route: %s (air freight)" % route]
    if fields.get("pickup_postcode") and best.get("trucker"):
        out.append("Pickup: by truck from postcode %s to %s airport, included" % (fields["pickup_postcode"], route.split(" - ")[0]))
    if kg:
        out.append("Shipment: %s kg gross%s" % (("%g" % kg), (", %g cbm" % cbm) if cbm else ""))
    if best.get("billed_kg") or best.get("chargeable_kg"):
        out.append("Chargeable weight: %s kg" % (best.get("billed_kg") or best.get("chargeable_kg")))
    out.append("Airline: %s" % (best.get("airline") or ""))
    if best.get("transit_days") is not None:
        out.append("Transit time: about %s day%s" % (best["transit_days"], "" if str(best["transit_days"]) == "1" else "s"))
    out += ["", "ALL-IN PRICE: %s %s" % (best.get("total"), best.get("currency") or "EUR"), ""]
    if fields.get("dg"):
        out += ["Dangerous goods: yes, documents required before booking", ""]
    out += ["-" * 60, ""]
    text = body if showable(body) else ""                       # a mail in another script: the facts above carry the offer
    for para in _latin(text).split("\n"):
        out += textwrap.wrap(para, 92) or [""]
    return out


def pdf(text_lines):
    """A plain A4 PDF, Helvetica, uncompressed (any reader and any text extractor finds the price)."""
    def esc(s):
        return _latin(s).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    per_page = 52
    pages = [text_lines[i:i + per_page] for i in range(0, len(text_lines), per_page)] or [[]]
    objs = [None, None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for n, page in enumerate(pages):
        parts = ["BT", "56 786 Td", "14 TL"]
        for i, line in enumerate(page):
            head = n == 0 and i == 0
            price = line.startswith("ALL-IN PRICE")
            parts.append("/F2 %s Tf" % (15 if head else 12) if head or price else "/F1 10.5 Tf")
            parts.append("(%s) Tj T*" % esc(line))
        parts.append("ET")
        stream = "\n".join(parts).encode("cp1252", "replace")
        content_no = len(objs) + 2
        objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                    b"/Contents %d 0 R >>" % content_no)
        kids.append(len(objs))
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids).encode(), len(kids))
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + o + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def docx(text_lines):
    def x(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    paras = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % x(line) for line in text_lines)
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
           'wordprocessingml/2006/main"><w:body>%s</w:body></w:document>' % paras)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
                   'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
    return buf.getvalue()


def build(tid, session, best, fields, body, request_text):
    """-> (attachments for mailbox.send, the formats the customer asked for). ([], set()) when they want no files."""
    if refused(request_text):
        return [], set()
    asked = requested(request_text)
    text_lines = lines(tid, session, best, fields, body)
    files = []
    for fmt in sorted(asked | {"pdf"}):
        data = pdf(text_lines) if fmt == "pdf" else docx(text_lines) if fmt == "docx" else "\n".join(text_lines).encode("utf-8")
        files.append({"filename": "offer-GOOGLE-%s.%s" % (tid, fmt), "content_type": MIME[fmt],
                      "content_base64": base64.b64encode(data).decode()})
    return files, asked


def say_so(body, asked, lang):
    """One sentence before the sign-off: 'Our offer is attached as PDF for your files.' Only when they asked for it."""
    if not asked:
        return body
    name = " + ".join(FORMAT_NAME[f] for f in sorted(asked))
    line = ATTACHED.get((lang or "en")[:2], ATTACHED["en"]) % name
    head, sep, sign = body.rstrip().rpartition("\n\n")
    return (head + "\n\n" + line + "\n\n" + sign) if sep else body.rstrip() + "\n\n" + line
