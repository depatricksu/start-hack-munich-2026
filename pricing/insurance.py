"""Cargo insurance the customer asks us to put INTO the all-in price.

5U, 22 Nov 01:07 (round 91, rejected too_low): "Please include cargo insurance in the all-in price, on the terms of
our frame agreement: goods value 22000 EUR, insured at 110 % of that value, premium rate 0.40 %." We quoted 927.95 EUR
and wrote that insurance was not included. The customer: "That seems too low to be right." The premium is
22000 x 1.10 x 0.004 = 96.80 EUR, so the all-in price was 1024.75 EUR.

Code only. All three numbers must be in the mail (value in EUR, insured share, premium rate); otherwise nothing is
added and the reply says, as before, that insurance is not included.
"""
import re
from decimal import Decimal, ROUND_HALF_UP

WORD = r"(?:insur\w*|versicher\w*|assur\w*|assicur\w*|asegur\w*|seguro)"
ASKED = re.compile(r"(?:includ\w*|incl\.?|add\w*|inklusive|einschlie[ßs]lich|inbegriffen|enthalten|y compris|inclu\w*|compr\w+|incluid\w*|a[ñn]ad\w+)"
                   r"[^.!?\n]{0,90}" + WORD + "|" + WORD + r"[^.!?\n]{0,90}(?:includ\w*|in (?:the|your) all-in|im all-in|inklusive|inbegriffen|"
                   r"enthalten|inclu\w*|compr\w+|incluid\w*)", re.I)
REFUSED = re.compile(r"\b(?:no|not|without|ohne|kein\w*|sans|senza|sin)\s+(?:\w+\s+){0,3}" + WORD, re.I)
VALUE = re.compile(r"(?:value|warenwert|wert|valeur|valore|valor)[^0-9\n]{0,40}?(\d[\d.,\s]*\d)\s*(?:EUR|€|euros?)", re.I)
PERCENT = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
TEXT = {"en": "This includes the cargo insurance you asked for: %s EUR (%s%% of the goods value of %s EUR at a premium of %s%%).",
        "de": "Darin enthalten ist die gewünschte Transportversicherung: %s EUR (%s %% des Warenwerts von %s EUR, Prämie %s %%).",
        "fr": "Ce prix comprend l'assurance transport demandée : %s EUR (%s %% de la valeur de %s EUR, prime de %s %%).",
        "it": "Il prezzo include l'assicurazione merci richiesta: %s EUR (%s %% del valore di %s EUR, premio dello %s %%).",
        "es": "El precio incluye el seguro de carga solicitado: %s EUR (%s %% del valor de %s EUR, prima del %s %%)."}


def _num(x):
    x = x.replace(" ", " ").replace(" ", "").rstrip(".,")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", x):
        x = x.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", x):
        x = x.replace(".", "").replace(",", ".")
    else:
        x = x.replace(",", ".")
    return Decimal(x)


def _plain(d):
    """22000 and 110, not 2.2E+4 and 1.1E+2; 22000.50 stays."""
    return format(d.quantize(Decimal(1)) if d == d.to_integral() else d, "f")


AMOUNT = re.compile(r"(\d[\d.,\s]*\d)\s*(?:EUR|€|euros?)\b", re.I)


def wanted(mail_text):
    """-> {"value", "pct", "rate", "premium"} (strings) when the customer gives the terms of a cargo insurance:
    a goods value in EUR, the insured share and the premium rate. None otherwise.

    The WORDING is free (round 91: "include cargo insurance in the all-in price ... goods value 22000 EUR, insured at
    110 % of that value, premium rate 0.40 %"; round 92: "we also need cargo insurance inside your all-in price: the
    goods are worth 81000 EUR, cover is 110 % of the value and the premium rate is 0.30 %"; round 92 was missed by a
    rule that looked for the words "include" and "value"). What counts is the paragraph that talks about insurance
    and carries exactly these three numbers. A customer who only asks whether insurance is available gives none."""
    text = (mail_text or "").split("\n--- attached file:")[0]
    for part in re.split(r"\n\s*\n", text):
        if not re.search(WORD, part, re.I) or REFUSED.search(part):
            continue
        amounts = [_num(a) for a in AMOUNT.findall(part)]
        shares = [_num(x) for x in PERCENT.findall(part)]
        pct = [p for p in shares if p >= 50]                  # "insured at 110 %", "cover is 110 % of the value"
        rate = [p for p in shares if p < 5]                   # "premium rate 0.40 %"
        if len(amounts) != 1 or len(pct) != 1 or len(rate) != 1 or amounts[0] <= 0:
            continue
        premium = (amounts[0] * pct[0] / 100 * rate[0] / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {"value": _plain(amounts[0]), "pct": _plain(pct[0]), "rate": str(rate[0]), "premium": str(premium)}
    return None


def add(best, ins):
    """The option with the premium inside its all-in total. The flight price stays in flight_total (the portal books
    the flight at that price)."""
    out = dict(best)
    out.setdefault("flight_total", best.get("flight_total") or best["total"])
    for k in ("total", "total_eur"):
        if out.get(k) is not None:
            out[k] = str((Decimal(str(out[k])) + Decimal(ins["premium"])).quantize(Decimal("0.01")))
    out["insurance"] = ins
    return out


def sentence(ins, lang):
    return TEXT.get(lang, TEXT["en"]) % (ins["premium"], ins["pct"], ins["value"], ins["rate"])
