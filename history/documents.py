"""Documents in the old data: PDFs, Word and Excel files, photos and SCANNED PAPER. Owner: Patrick.

Text comes from the file's own text layer when it has one (PDF, Word, Excel, text) and from OCR when it does not
(a scan, a phone photo, an image-only PDF): macOS Vision through Riky's dg/ocr.swift, about 1 s a page, on this
machine, nothing uploaded anywhere. Each document gets a kind (forwarding order, booking confirmation, invoice, air
waybill, packing list, delivery receipt, ...) and the facts a case needs (references, e-mail, lane, weight, price).
"""
import hashlib, os, re, subprocess, tempfile

from . import importer

IMAGE = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".bmp", ".gif")
DOC = (".pdf", ".docx", ".txt") + IMAGE
KINDS = [   # first match wins: the most specific papers first
    ("forwarding_order", r"speditionsauftrag|forwarding order|shipping order|booking (?:form|request form)|transportauftrag|auftrag nr"),
    ("delivery_receipt", r"proof of delivery|\bpod\b|delivery receipt|empfangsbestätigung|ablieferbeleg|received in good order"),
    ("air_waybill", r"air ?waybill|luftfrachtbrief|^\s*awb\b"),
    ("booking_confirmation", r"booking (?:\S+ )?confirm|buchungsbestätigung|is confirmed|confirmed"),
    ("packing_list", r"packing ?list|packliste"),
    ("dg_declaration", r"dangerous goods declaration|shipper'?s declaration|\bdgd\b|gefahrguterklärung"),
    ("invoice", r"invoice|rechnung|amount due|zahlbar|total due"),
    ("sli", r"shipper'?s letter of instruction|\bsli\b"),
    ("request", r"anfrage|request for (?:a )?quot|quote request|rfq|angebotsanfrage"),
]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_OCR_TIMEOUT = 90


def _ocr_file(path):
    """One file through macOS Vision, via Riky's long-lived worker (the model loads once, then ~1 s a page).
    "" when OCR is not available here (not a Mac, no swiftc). A batch import may wait; the live clerk never calls this."""
    try:
        from dg import attach
        with attach._LOCK:
            text = attach._ask(path, _OCR_TIMEOUT)
        if text is None:                                          # the worker died: one more try with a fresh one
            binary = attach.ocr_binary()
            text = subprocess.run([binary, path], capture_output=True, text=True, timeout=_OCR_TIMEOUT).stdout if binary else ""
        return (text or "").strip()
    except Exception:
        return ""


def _is_text(text):
    """Real words, not the bytes of a scanned page read as letters."""
    t = (text or "").strip()
    if len(t) < 20:
        return False
    good = sum(1 for ch in t if ch.isalnum() or ch in " \n\t.,:;-/()€%@+#'\"&")
    return good >= len(t) * 0.85 and len(re.findall(r"[A-Za-z]{3,}", t)) >= 3


def read_text(data, filename):
    """-> (text, how): how is 'text' (own text layer), 'ocr' (read from the image) or '' (nothing readable)."""
    name = (filename or "").lower()
    ext = os.path.splitext(name)[1] or (".pdf" if data[:5] == b"%PDF-" else "")
    text = ""
    if ext not in IMAGE:
        try:
            from dg import attach
            if ext == ".pdf" or data[:5] == b"%PDF-":
                text = attach._pdf(data)                       # text layer only; scans go to OCR below
            else:
                text = attach.attachment_text(data, name)
        except Exception:
            text = ""
        if _is_text(text):
            return text.strip(), "text"
    if ext in IMAGE or ext == ".pdf":
        with tempfile.NamedTemporaryFile(suffix=ext or ".jpg", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            text = _ocr_file(path)
        finally:
            os.unlink(path)
        if len(text.strip()) > 10:
            return text, "ocr"
    return (text or "").strip(), ""


def kind_of(text, filename=""):
    hay = (filename or "") + "\n" + (text or "")[:1500]
    return next((k for k, rx in KINDS if re.search(rx, hay, re.I)), "other")


def facts(text, filename=""):
    """What a case needs from one document. Code only (shared/rfq.py extractor + a few patterns)."""
    from shared import rfq
    r = rfq.extract_rfq(filename or "", text or "")
    try:
        r = rfq.normalize(r)
    except Exception:
        pass
    lane = re.search(r"\b(?:von|from|origin)\s*:?\s*([A-Z]{3})\b.{0,40}?\b(?:nach|to|destination)\s*:?\s*([A-Z]{3})\b", text or "", re.S | re.I)
    origin = (lane.group(1).upper() if lane else None) or r.origin
    destination = (lane.group(2).upper() if lane else None) or r.destination
    w = re.search(r"(?:gewicht|weight|gross)\D{0,20}(\d[\d.,]*)\s*kg", text or "", re.I)
    price = re.search(r"(?:preis|price|total|amount|betrag|summe)[^\n\d]{0,30}(\d[\d.,]*\d)\s*(EUR|€|USD)", text or "", re.I) \
        or importer.MONEY.search(text or "")
    amount, cur = (None, None)
    if price:
        g = [x for x in price.groups() if x]
        num = next((x for x in g if re.match(r"\d", x)), None)
        amount = importer._num(num) if num else None
        cur = next((x.upper().replace("€", "EUR") for x in g if not re.match(r"\d", x)), "EUR")
    airline = next((a for a in importer.AIRLINES if a.lower() in (text or "").lower()), None)
    emails = [e.lower() for e in EMAIL.findall(text or "")]
    company = re.search(r"(?:versender|shipper|absender|customer|kunde)\s*:?\s*([^\n,]{3,60})", text or "", re.I)
    return {"refs": sorted({x.upper().replace(" ", "") for x in importer.REF.findall(text or "")}),
            "emails": emails, "company": company.group(1).strip() if company else None,
            "origin": origin, "destination": destination,
            "weight_kg": importer._num(w.group(1)) if w else r.weight_kg, "volume_cbm": r.volume_cbm,
            "pieces": r.pieces, "price": amount, "currency": cur, "airline": airline}


DATE = re.compile(r"\b(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b")


def date_in(text):
    """The first date written on the paper (order date, pickup date): the case's date."""
    m = DATE.search(text or "")
    return importer._date(m.group(1)) if m else None


def from_file(path):
    with open(path, "rb") as f:
        data = f.read()
    return from_bytes(data, os.path.basename(path), source=path)


def from_bytes(data, filename, source=""):
    text, how = read_text(data, filename)
    return {"id": hashlib.sha1(data).hexdigest()[:16], "filename": filename, "source": source, "bytes": len(data),
            "text": text, "how": how, "kind": kind_of(text, filename), "facts": facts(text, filename)}


def case_from_paper(d, date=None):
    """A paper forwarding order with a lane and a weight is a shipment of its own (a phone order typed on paper)."""
    f = d["facts"]
    if d["kind"] not in ("forwarding_order", "air_waybill") or not (f["origin"] and f["destination"] and f["weight_kg"]):
        return None
    st = "confirmed" if d["kind"] == "air_waybill" else "booked" if any(r.startswith("BK-") for r in f["refs"]) else "quoted" \
        if f["price"] else "open"
    return {"key": "doc:" + d["id"], "customer": (f["emails"] or [None])[0], "company": f["company"],
            "subject": "%s (%s)" % (d["filename"], d["kind"].replace("_", " ")), "origin": f["origin"],
            "destination": f["destination"], "weight_kg": f["weight_kg"], "volume_cbm": f["volume_cbm"],
            "pieces": f["pieces"], "commodity": None, "pickup_postcode": None, "ready_date": None, "price": f["price"],
            "currency": f["currency"], "airline": f["airline"],
            "booking_reference": next((r for r in f["refs"] if r.startswith("BK-")), None), "refs": f["refs"],
            "status": st, "first_at": date, "last_at": date, "n_mails": 0, "sources": [d["filename"]], "mids": [],
            "quoted_at": None}


def link(d, cases):
    """-> (case, how) for a document: its reference first, then the e-mail address in it, then company + lane."""
    f = d["facts"]
    by_ref = [c for c in cases if set(f["refs"]) & set(c["refs"])]
    if by_ref:
        return by_ref[0], "reference"
    for e in f["emails"]:
        hits = [c for c in cases if (c["customer"] or "").lower() == e]
        if len(hits) == 1 or (hits and f["origin"]):
            same_lane = [c for c in hits if c["origin"] == f["origin"] and c["destination"] == f["destination"]]
            if len(same_lane) == 1 or len(hits) == 1:
                return (same_lane or hits)[0], "e-mail address"
    if f["company"] and f["origin"]:
        word = f["company"].split()[0].lower()
        hits = [c for c in cases if word in ((c["customer"] or "") + " " + (c["company"] or "")).lower()
                and c["origin"] == f["origin"] and c["destination"] == f["destination"]]
        if len(hits) == 1:
            return hits[0], "company + lane"
    return None, None
