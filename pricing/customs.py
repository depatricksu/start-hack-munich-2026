"""A customs clearance fee the customer asks us to put INTO the all-in price.

Built ahead (22 Nov), after 5U did the same with cargo insurance (rounds 91/92, rejected too_low): "Please include
export customs clearance in the all-in price: our broker charges 45 EUR per declaration." Without this we quote the
flight only and write "customs clearance isn't included".

Code only, and strict: ONE sentence must name customs clearance and carry exactly one flat fee in EUR, and the
customer must ask for it inside the price. Anything else (a percentage, a goods value, a fee per line, no amount)
adds nothing and the reply says, as before, that customs is not included. 0 of the 1206 real mails up to 22 Nov 01:21
mention customs at all.
"""
import re
from decimal import Decimal

from pricing.insurance import AMOUNT, _num

WORD = r"(?:customs|clearance|zoll\w*|verzoll\w*|d[ée]douan\w*|douan\w*|sdogan\w*|dogan\w*|aduan\w*)"
INSIDE = re.compile(r"includ\w*|incl\.|inside|add\w*|all-in|inklusive|einschlie[ßs]lich|inbegriffen|enthalten|im preis|"
                    r"compris\w*|inclu\w*|compres\w*|incluid\w*|a[ñn]ad\w+", re.I)
REFUSED = re.compile(r"\b(?:no|not|without|ohne|kein\w*|sans|senza|sin|ourselves|selbst|our own broker)\b", re.I)
VALUE = re.compile(r"%|value|worth|warenwert|\bwert\b|valeur|valore|valor|dut(?:y|ies)|\bvat\b|steuer|tax", re.I)
PER_OTHER = re.compile(r"(?<!as )\b(?:per|je|pro|each|par)\b(?!\s+(?:declaration|shipment|consignment|awb|entry|sendung|anmeldung|"
                       r"zollanmeldung|d[ée]claration|envoi|dichiarazione|spedizione|declaraci[oó]n|env[ií]o)\b)", re.I)
MAX_FEE = Decimal("1000")                                    # a clearance fee, not a goods value
TEXT = {"en": "This includes the customs clearance you asked for: %s EUR.",
        "de": "Darin enthalten ist die gewünschte Zollabfertigung: %s EUR.",
        "fr": "Ce prix comprend le dédouanement demandé : %s EUR.",
        "it": "Il prezzo include lo sdoganamento richiesto: %s EUR.",
        "es": "El precio incluye el despacho de aduana solicitado: %s EUR."}


def wanted(mail_text):
    """-> {"fee": "45.00"} when the customer asks for customs clearance inside the price and names one flat EUR fee."""
    text = (mail_text or "").split("\n--- attached file:")[0]
    for part in re.split(r"\n\s*\n", text):
        if not re.search(WORD, part, re.I) or not INSIDE.search(part):
            continue
        for s in re.split(r"(?<=[.!?])\s+|\n", part):
            if not re.search(WORD, s, re.I) or REFUSED.search(s) or VALUE.search(s) or PER_OTHER.search(s):
                continue
            amounts = [_num(a) for a in AMOUNT.findall(s)]
            if len(amounts) == 1 and 0 < amounts[0] <= MAX_FEE:
                return {"fee": str(amounts[0].quantize(Decimal("0.01")))}
    return None


def add(best, cus):
    """The option with the fee inside its all-in total; the flight price stays in flight_total (as for insurance).
    Only an EUR quote: an EUR fee is never added to a number in another currency."""
    if (best.get("currency") or "EUR") != "EUR":
        return best
    out = dict(best)
    out.setdefault("flight_total", best.get("flight_total") or best["total"])
    for k in ("total", "total_eur"):
        if out.get(k) is not None:
            out[k] = str((Decimal(str(out[k])) + Decimal(cus["fee"])).quantize(Decimal("0.01")))
    out["customs"] = cus
    return out


def sentence(cus, lang):
    return TEXT.get(lang, TEXT["en"]) % cus["fee"]
