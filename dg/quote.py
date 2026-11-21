"""What an RFQ with dangerous goods (DG) gets from us. Owner: Riky.

5U's hourly change (21 Nov ~17:00): the RFQ mail says "general cargo, non-dangerous", but the attached packing list /
Shipper's Letter of Instruction declares e.g. "Dangerous goods: UN1133, Class 3, Adhesives". Quoting it as general
cargo was rejected with reason `dg_docs_missing`.

Erik's detection reads the attachment and puts what it found in fields["dg"]. This module takes it from there:

    info = dg.read_declaration(text)          # optional helper: UN number, class, name from any text, or None
    best, body, human = dg.apply(best, fields, body)

DG_MODE (env, default "docs") decides, until 5U confirms the rule:
    docs       quote as usual + a short DG paragraph: we name the UN number/class we saw and ask for the
               Shipper's Declaration for Dangerous Goods and the safety data sheet (MSDS) before booking.
    surcharge  the same, plus DG_SURCHARGE_EUR_PER_KG x billed kg (and DG_SURCHARGE_MIN_EUR) on the total.
    human      do not quote: hand to a person (apply() returns human=True with the reason).
    off        do nothing (old behaviour).
Pure functions, no network, no LLM call, no DB: instant and safe to call on every quote.
"""
import os, re
from decimal import Decimal, ROUND_HALF_UP

UN = re.compile(r"\bUN\s?-?(\d{4})\b", re.I)
CLASS = re.compile(r"\b(?:class|klasse|classe|clase)\s*[:.]?\s*(\d(?:\.\d)?)\b", re.I)
NAME_AFTER = re.compile(r"\bUN\s?-?\d{4}\b[\s,;:/-]*(?:(?:class|klasse)\s*[:.]?\s*\d(?:\.\d)?[\s,;:/-]*)?([A-Za-z][A-Za-z ,()-]{2,60})", re.I)
DECLARES = re.compile(r"dangerous goods\s*[:=][ \t]*(?=\S)(?!no\b|none\b|n/?a\b|-)|gefahrgut\s*[:=][ \t]*(?=\S)(?!nein\b|keine?\b)"
                      r"|\bDGR\b|\bhazmat\b"
                      r"|\bUN\s?-?\d{4}\b", re.I)
NOT_DG = re.compile(r"\b(?:non[- ]?dangerous|not dangerous|no dangerous goods|kein gefahrgut|nicht gef[aä]hrlich)\b", re.I)


def mode():
    m = os.environ.get("DG_MODE", "docs").strip().lower()
    return m if m in ("docs", "surcharge", "human", "off") else "docs"


def read_declaration(text):
    """Find a DG declaration in any text (attachment or mail). Returns {"un", "class", "name"} or None.
    A UN number is proof. Without one, an explicit 'Dangerous goods: <something>' line counts; a plain
    'non-dangerous' with no UN number does not."""
    if not text:
        return None
    un = UN.search(text)
    if not un and (NOT_DG.search(text) or not DECLARES.search(text)):
        return None
    cls = CLASS.search(text)
    name = NAME_AFTER.search(text) if un else None
    clean = None
    if name:
        clean = re.split(r"\s{2,}|\b(?:class|klasse|packing|pg|net|gross|qty)\b", name.group(1), flags=re.I)[0]
        clean = clean.strip(" ,;:-()") or None
    return {"un": "UN" + un.group(1) if un else None, "class": cls.group(1) if cls else None, "name": clean}


def describe(info):
    """'UN1133, class 3 (Adhesives)' from whatever we know."""
    parts = [p for p in (info.get("un"), "class " + info["class"] if info.get("class") else None) if p]
    text = ", ".join(parts) or "dangerous goods"
    return text + (f" ({info['name']})" if info.get("name") else "")


PARAGRAPH = {
    "en": ("One thing to note: your shipping documents declare dangerous goods ({what}). We can fly this as "
           "dangerous goods; to confirm the booking we need the Shipper's Declaration for Dangerous Goods and the "
           "safety data sheet (MSDS) for this shipment."),
    "de": ("Ein Hinweis: Laut Ihren Versandunterlagen handelt es sich um Gefahrgut ({what}). Wir können die Sendung "
           "als Gefahrgut befördern; für die Buchung benötigen wir die Shipper's Declaration for Dangerous Goods und "
           "das Sicherheitsdatenblatt (MSDS)."),
    "it": ("Una nota: i documenti di spedizione dichiarano merce pericolosa ({what}). Possiamo trasportarla come "
           "merce pericolosa; per confermare la prenotazione ci servono la Shipper's Declaration for Dangerous Goods "
           "e la scheda di sicurezza (MSDS)."),
    "fr": ("Une remarque : vos documents d'expédition déclarent des marchandises dangereuses ({what}). Nous pouvons "
           "les transporter en tant que telles ; pour confirmer la réservation, il nous faut la Shipper's Declaration "
           "for Dangerous Goods et la fiche de données de sécurité (MSDS)."),
    "es": ("Una nota: sus documentos de envío declaran mercancía peligrosa ({what}). Podemos transportarla como "
           "mercancía peligrosa; para confirmar la reserva necesitamos la Shipper's Declaration for Dangerous Goods "
           "y la hoja de datos de seguridad (MSDS)."),
}


def _money(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def surcharge_eur(best):
    """DG surcharge for the 'surcharge' mode: per kg of billed weight, at least the minimum. 0 if not configured."""
    per_kg = Decimal(os.environ.get("DG_SURCHARGE_EUR_PER_KG", "0") or "0")
    minimum = Decimal(os.environ.get("DG_SURCHARGE_MIN_EUR", "0") or "0")
    kg = Decimal(str(best.get("billed_kg") or best.get("chargeable_kg") or 0))
    return _money(max(per_kg * kg, minimum))


def _insert_before_signoff(body, paragraph):
    """Put our paragraph before the closing ('Best regards', 'Mit freundlichen Grüßen', ...), else at the end."""
    m = re.search(r"\n\s*(best regards|kind regards|regards|best|cheers|mit freundlichen|viele grüße|beste grüße|"
                  r"cordiali saluti|saluti|cordialement|bien à vous|saludos|atentamente)\b", body, re.I)
    if m:
        return body[:m.start()].rstrip() + "\n\n" + paragraph + "\n" + body[m.start():]
    return body.rstrip() + "\n\n" + paragraph


def apply(best, fields, body):
    """Returns (best, body, human). human is None, or the reason to hand the request to a person.
    Does nothing unless fields["dg"] says DG was declared (a dict from Erik's detection, or True)."""
    info = fields.get("dg")
    if not info or mode() == "off":
        return best, body, None
    if info is True:
        info = {}
    if mode() == "human":
        return best, body, "dangerous goods declared: " + describe(info)
    if mode() == "surcharge":
        extra = surcharge_eur(best)
        if extra > 0:
            old = _money(best.get("total_eur") or best.get("total"))
            best = dict(best, dg_surcharge_eur=str(extra), total_eur=str(old + extra))
            if best.get("currency", "EUR") == "EUR":
                best["total"] = best["total_eur"]
            for s in {str(old), f"{old:,.2f}", f"{old:.2f}".replace(".", ",")}:
                body = body.replace(s, str(_money(best["total_eur"])))
    lang = (fields.get("language") or "en")[:2].lower()
    paragraph = PARAGRAPH.get(lang, PARAGRAPH["en"]).format(what=describe(info))
    return best, _insert_before_signoff(body, paragraph), None
