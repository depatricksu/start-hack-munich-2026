"""Shipment facts in the attachments vs the mail. Owner: Riky.

5U's 17:00 change hid dangerous goods in the attachment while the mail said "non-dangerous". The same trick works for
weight, pieces or size: the packing list says 1,250 kg, the mail 950 kg. This module reads the packing list's numbers
and compares them with what the gateway call took from the mail.

    facts = dg.packing_facts(text)                 # {"gross_kg", "pieces", "volume_cbm"} (keys only when found)
    diff  = dg.compare(fields, mail)              # what disagrees by more than 2 %, or {}

dg.check_mail() already downloads the attachments; it keeps their text in a small cache, so compare() costs nothing.
The attachment's gross weight / volume win in core (see core/main.py hook) since 5U round 57; ATTACH_OVERRIDE=0
turns that off (log the difference only). dg.note() tells the customer which number we priced on.
"""
import os, re

_TEXT = {}  # mail id -> attachment text (filled by attach.check_mail), at most 200 mails

KG = r"(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\s*(?:kg|kgs|kilos?)\b"
GROSS = re.compile(r"(?:total\s+)?(?:gross\s*(?:weight)?|g\.?\s?w\.?|brutto(?:gewicht)?|chargeable\s+weight|total\s+weight|"
                   r"poids\s+brut|peso\s+(?:bruto|lordo))\s*[:=]?\s*" + KG, re.I)
# Unit in brackets before the value, no unit after it (5U round 57: "Total gross weight (kg): 1729").
GROSS_UNIT_FIRST = re.compile(r"(?:gross\s*(?:weight)?|g\.?\s?w\.?|brutto(?:gewicht)?|total\s+weight|poids\s+brut|"
                              r"peso\s+(?:bruto|lordo))[ \t]*\((?:kg|kgs)\)[ \t]*[:=]?[ \t]*\|?[ \t]*"   # xlsx cells come as "label: | value"
                              r"(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)\b", re.I)
VOLUME_UNIT_FIRST = re.compile(r"(?:volume|vol\.?|volumen)[ \t]*\((?:cbm|m3|m³)\)[ \t]*[:=]?[ \t]*\|?[ \t]*(\d+(?:[.,]\d+)?)\b", re.I)
# The number must be on the label's own line: a table header "Pieces" above a row "1729 80 140" is not 1729 pieces.
PIECES = re.compile(r"(?:total[ \t]+)?(?:pieces|pcs|packages|colli|cartons|pallets|packstücke|anzahl)[ \t]*[:=]?[ \t]*\|?[ \t]*(\d{1,4})\b", re.I)
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
    weights = [_num(m.group(1)) for m in GROSS.finditer(text)] + [_num(m.group(1)) for m in GROSS_UNIT_FIRST.finditer(text)]
    if weights:
        out["gross_kg"] = max(weights)
    pieces = [int(m.group(1)) for m in PIECES.finditer(text)]
    if pieces:
        out["pieces"] = max(pieces)
    vols = [_num(m.group(1)) for m in list(VOLUME.finditer(text)) + list(VOLUME_UNIT_FIRST.finditer(text))
            if _num(m.group(1)) < 500]
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
    """The packing list beats the mail text. Default ON since 5U round 57 (21 Nov 21:40): the mail said 1210 kg, the
    attached packing list 1729 kg, we priced 1210 and were rejected too_low. ATTACH_OVERRIDE=0 turns it off."""
    return os.environ.get("ATTACH_OVERRIDE", "1") == "1"


def winner(d):
    """Which number to price on: the attachment's, unless it is so far from the mail that we probably misread it."""
    try:
        a, m = float(d["attachment"]), float(d["mail"])
        return a if m > 0 and 0.5 <= a / m <= 3 else m
    except Exception:
        return d.get("mail")


NOTE = {
    "en": "One note: your packing list shows {att} {unit} gross, while your mail says {mail} {unit}. I have priced on the packing list.",
    "de": "Ein Hinweis: Ihre Packliste nennt {att} {unit} brutto, in Ihrer Mail stehen {mail} {unit}. Ich habe mit der Packliste gerechnet.",
    "it": "Una nota: la packing list indica {att} {unit} lordi, mentre nella mail sono {mail} {unit}. Ho calcolato sulla packing list.",
    "fr": "Une remarque : votre liste de colisage indique {att} {unit} brut, alors que votre mail mentionne {mail} {unit}. J'ai calculé sur la liste de colisage.",
    "es": "Una nota: su packing list indica {att} {unit} brutos, mientras que su correo dice {mail} {unit}. He calculado con la packing list.",
}
NOTE_VOL = {
    "en": "One note: your packing list shows {att} cbm, while your mail says {mail} cbm. I have priced on the packing list.",
    "de": "Ein Hinweis: Ihre Packliste nennt {att} cbm, in Ihrer Mail stehen {mail} cbm. Ich habe mit der Packliste gerechnet.",
    "it": "Una nota: la packing list indica {att} cbm, mentre nella mail sono {mail} cbm. Ho calcolato sulla packing list.",
    "fr": "Une remarque : votre liste de colisage indique {att} cbm, alors que votre mail mentionne {mail} cbm. J'ai calculé sur la liste de colisage.",
    "es": "Una nota: su packing list indica {att} cbm, mientras que su correo dice {mail} cbm. He calculado con la packing list.",
}


def note(fields, body):
    """Tell the customer which number we priced on when the packing list replaced the mail's weight or volume."""
    used = fields.get("attachment_used") or {}
    if not used:
        return body
    from .quote import _insert_before_signoff
    lang = (fields.get("language") or "en")[:2].lower()
    g = lambda x: ("%g" % float(x))                                # noqa: E731  1729.0 -> 1729
    if "gross_kg" in used:
        text = NOTE.get(lang, NOTE["en"]).format(att=g(used["gross_kg"]["attachment"]), mail=g(used["gross_kg"]["mail"]), unit="kg")
    else:
        text = NOTE_VOL.get(lang, NOTE_VOL["en"]).format(att=g(used["volume_cbm"]["attachment"]), mail=g(used["volume_cbm"]["mail"]))
    return _insert_before_signoff(body, text)
