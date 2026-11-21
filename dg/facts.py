"""Shipment facts in the attachments vs the mail. Owner: Riky.

5U's 17:00 change hid dangerous goods in the attachment while the mail said "non-dangerous". The same trick works for
weight, pieces or size: the packing list says 1,250 kg, the mail 950 kg. This module reads the packing list's numbers
and compares them with what the gateway call took from the mail.

    facts = dg.packing_facts(text)                 # {"gross_kg", "pieces", "volume_cbm"} (keys only when found)
    diff  = dg.compare(fields, mail)              # what disagrees by more than 2 %, or {}

dg.check_mail() already downloads the attachments; it keeps their text in a small cache, so compare() costs nothing.
ATTACH_OVERRIDE=1 (env, default 0) lets the attachment's gross weight / volume win in core (see core/main.py hook);
default is: log the difference only.
"""
import os, re

_TEXT = {}  # mail id -> attachment text (filled by attach.check_mail), at most 200 mails

KG = r"(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(?:kg|kgs|kilos?)\b"
GROSS = re.compile(r"(?:total\s+)?(?:gross\s*(?:weight)?|g\.?\s?w\.?|brutto(?:gewicht)?|chargeable\s+weight|total\s+weight|"
                   r"poids\s+brut|peso\s+(?:bruto|lordo))\s*[:=]?\s*" + KG, re.I)
PIECES = re.compile(r"(?:total\s+)?(?:pieces|pcs|packages|colli|cartons|pallets|packstücke|anzahl)\s*[:=]?\s*(\d{1,4})\b", re.I)
VOLUME = re.compile(r"(?:total\s+)?(?:volume|vol\.?|cbm|m3|m³)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(?:cbm|m3|m³)?", re.I)
DIMS = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*[x×*]\s*(\d{1,3}(?:[.,]\d+)?)\s*[x×*]\s*(\d{1,3}(?:[.,]\d+)?)\s*cm"
                  r"(?:[^\n\d]{0,20}(\d{1,3})\s*(?:pcs|pieces|x|colli|cartons|pallets)?)?", re.I)


def _num(s):
    s = s.strip().replace(" ", "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):                # 1.250 or 1,250 = thousands
        return float(re.sub(r"[.,]", "", s))
    if re.fullmatch(r"\d{1,3}(,\d{3})+\.\d+", s):              # 1,250.50
        return float(s.replace(",", ""))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", s):              # 1.250,50
        return float(s.replace(".", "").replace(",", "."))
    return float(s.replace(",", "."))


def packing_facts(text):
    """Numbers a packing list / SLI states. Takes the LARGEST gross weight it sees (the total line, not a carton)."""
    if not text:
        return {}
    out = {}
    weights = [_num(m.group(1)) for m in GROSS.finditer(text)]
    if weights:
        out["gross_kg"] = max(weights)
    pieces = [int(m.group(1)) for m in PIECES.finditer(text)]
    if pieces:
        out["pieces"] = max(pieces)
    vols = [_num(m.group(1)) for m in VOLUME.finditer(text) if _num(m.group(1)) < 500]
    if vols:
        out["volume_cbm"] = max(vols)
    elif DIMS.search(text):
        cbm = 0.0
        for m in DIMS.finditer(text):
            l, w, h = (_num(m.group(i)) for i in (1, 2, 3))
            cbm += l * w * h / 1e6 * (int(m.group(4)) if m.group(4) else 1)
        out["volume_cbm"] = round(cbm, 3)
    return out


def remember(mail_id, text):
    if len(_TEXT) > 200:
        _TEXT.clear()
    _TEXT[mail_id] = text


def compare(fields, mail, tolerance=0.02):
    """{fact: {"mail": x, "attachment": y}} for every number that differs by more than the tolerance. Never raises."""
    try:
        facts = packing_facts(_TEXT.get(mail.get("id"), ""))
        mail_vals = {"gross_kg": fields.get("weight_kg_total") or fields.get("weight_kg"),
                     "volume_cbm": fields.get("volume_cbm_total") or fields.get("volume_cbm")}
        diff = {}
        for k, att in facts.items():
            m = mail_vals.get(k)
            if k in mail_vals and m and att and abs(float(att) - float(m)) > tolerance * max(float(att), float(m)):
                diff[k] = {"mail": float(m), "attachment": float(att)}
        return diff
    except Exception:
        return {}


def override():
    return os.environ.get("ATTACH_OVERRIDE", "0") == "1"
