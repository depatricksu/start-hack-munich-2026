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


OTHER_FEE = re.compile(r"customs|clearance|zoll\w*|verzoll\w*|d[ée]douan\w*|douan\w*|sdogan\w*|dogan\w*|aduan\w*", re.I)
SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n")


def _own(part):
    """The paragraph without the sentences about another fee (customs clearance: pricing/customs.py reads those).
    Kai, 22 Nov: insurance terms and a customs fee in ONE paragraph gave two EUR amounts, so nothing was added."""
    return " ".join(x for x in SENTENCE.split(part) if re.search(WORD, x, re.I) or not OTHER_FEE.search(x))


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
        part = _own(part)
        amounts = [_num(a) for a in AMOUNT.findall(part)]
        shares = [_num(x) for x in PERCENT.findall(part)]
        pct = [p for p in shares if p >= 50]                  # "insured at 110 %", "cover is 110 % of the value"
        rate = [p for p in shares if p < 5]                   # "premium rate 0.40 %"
        if len(amounts) != 1 or len(pct) != 1 or len(rate) != 1 or amounts[0] <= 0:
            continue
        premium = (amounts[0] * pct[0] / 100 * rate[0] / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {"value": _plain(amounts[0]), "pct": _plain(pct[0]), "rate": str(rate[0]), "premium": str(premium)}
    return None


BLOCK = re.compile(r"(?m)^[ \t]*(\d{1,2})[.)][ \t]+(.*(?:\n(?![ \t]*\d{1,2}[.)][ \t]|[ \t]*\n).*)*)")   # "1. GRU ...", "2) TLV ..."
EACH = re.compile(r"\b(each|per shipment|for both|for all|je sendung|jeweils|pro sendung|chacun\w*|par envoi|ciascun\w*|per spedizione|cada)\b", re.I)
UNCLEAR = "unclear"


def _terms(value, pct, rate):
    premium = (value * pct / 100 * rate / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"value": _plain(value), "pct": _plain(pct), "rate": str(rate), "premium": str(premium)}


ORDINAL = (r"first|1st|shipment 1|erste\w*|sendung 1|premi[eè]re?|prim[ao]", r"second|2nd|shipment 2|zweite\w*|sendung 2|deuxi[eè]me|second[ao]|segund[ao]",
           r"third|3rd|shipment 3|dritte\w*|sendung 3|troisi[eè]me|terz[ao]|tercer[ao]?")


def _by_name(text, n, names):
    """[value per shipment] when every EUR amount in the text belongs to one shipment by name (its airport code, or
    'first' / 'second'), each shipment once. The name stands after the amount ('52000 EUR for GRU and 18000 EUR for
    RUH') or before it ('the second shipment is worth 52000 EUR, the first 18000 EUR'). None when neither reading
    gives every shipment exactly one value, or when the two readings disagree."""
    found = list(AMOUNT.finditer(text))
    if len(found) != n:
        return None
    pats = []
    for i in range(n):
        keys = ([ORDINAL[i]] if i < len(ORDINAL) else []) + [re.escape(x) for x in (names[i] if names and i < len(names) else []) if x]
        pats.append(re.compile(r"\b(?:%s)\b" % "|".join(keys), re.I) if keys else None)

    def read(side):
        out = [None] * n
        for k, m in enumerate(found):
            if side == "before":
                near = text[found[k - 1].end() if k else max(0, m.start() - 60):m.start()][-60:]
            else:
                near = text[m.end():found[k + 1].start() if k + 1 < len(found) else m.end() + 40][:40]
            hit = [i for i in range(n) if pats[i] and pats[i].search(near)]
            if len(hit) != 1 or out[hit[0]] is not None:
                return None
            out[hit[0]] = _num(m.group(1))
        return out

    readings = [r for r in (read("after"), read("before")) if r]
    return readings[0] if readings and all(r == readings[0] for r in readings) else None


def wanted_many(mail_text, n, names=None):
    """Insurance terms for a request with n shipments, in the customer's order.
    -> a list of n dicts, or None when the mail states no insurance terms, or UNCLEAR when it asks for insurance but
    the goods values cannot be matched to the shipments (one value for two shipments, with no word like 'each').
    names: per shipment, what the customer calls it (airport code, city).
    Values are taken from each numbered shipment line when every line has one, else from the insurance paragraph when
    it lists as many amounts as there are shipments (matched by name, else in order); the insured share and the
    premium rate are stated once for all."""
    text = (mail_text or "").split("\n--- attached file:")[0]
    if n <= 1:
        one = wanted(text)
        return [one] if one else None
    blocks = {int(m.group(1)): m.group(2) for m in BLOCK.finditer(text)}
    paras = [_own(p) for p in re.split(r"\n\s*\n", text) if re.search(WORD, p, re.I)]
    if not paras or any(REFUSED.search(p) for p in paras):
        return None
    lines_ = [blocks.get(i, "") for i in range(1, n + 1)]
    scope = "\n".join(paras + [b for b in lines_ if AMOUNT.search(b)])
    shares = {_num(x) for x in PERCENT.findall(scope)}
    pct, rate = [p for p in shares if p >= 50], [p for p in shares if p < 5]
    in_blocks = [[_num(a) for a in AMOUNT.findall(b)] for b in lines_]
    about = "\n".join(BLOCK.sub("", p) for p in paras)         # the insurance text without the shipment lines
    listed = [_num(a) for a in AMOUNT.findall(about)]
    if not pct and not rate and not listed and not any(in_blocks):
        return None                                           # "is insurance available?": nothing to price
    if len(pct) != 1 or len(rate) != 1:
        return UNCLEAR
    if all(len(b) == 1 for b in in_blocks) and not listed:
        values = [b[0] for b in in_blocks]
    elif len(listed) == n:
        values = _by_name(about, n, names) or listed
    elif len(listed) == 1 and EACH.search(about):
        values = listed * n
    else:
        return UNCLEAR
    if any(v <= 0 for v in values):
        return UNCLEAR
    return [_terms(v, pct[0], rate[0]) for v in values]


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
