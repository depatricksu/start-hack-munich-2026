"""Several lots listed line by line: the totals are added up by code, not by the model.

5U, 22 Nov 10:27 (request 55122, rejected 'too high'):
    Lot 1: 2 cartons, each 474 kg gross (445 kg net), each 120 x 80 x 119 cm
    Lot 2: 7 drums, each 32 kg gross (28 kg net), each 110 x 110 x 103 cm
    Lot 3: 2 pallets, together 726 kg gross (646 kg net), together 4.33 cbm
That is 1,898 kg and 15.34 cbm (volume weight 2,562 kg decides). The model listed all three lots as pieces AND put
1,014 kg into weight_kg; main.shipment() added both: 2,912 kg, 13.7 % too high. The same shape cost accuracy before:
round 62 (1,587 instead of 1,122 kg, 37.5 of 45), round 158 (2,587 instead of 1,797 kg, 38.9 of 45), and round 9
was rejected 'too low' (730 instead of 1,952 kg).

The lot lines themselves are exact: a count, 'each' or 'together', the GROSS weight, and the size or the cbm. When the
mail's own text (not a forwarded old message below it) has two or more such lines and every one can be read fully,
these totals win. Anything else (pounds, inches, a lot without a weight, no 'each' or 'together' on several pieces)
returns None and the model's reading stays, as before.
"""
import re

CHAIN = re.compile(r"^[ \t]*-{2,}\s*(?:Original Message|Urspr[üu]ngliche Nachricht|Forwarded message|Weitergeleitete Nachricht)|"
                   r"^[ \t]*(?:From|Von|De)\s*:.*\n[ \t]*(?:Sent|Gesendet|Date|Datum|Enviado)\s*:|"
                   r"^[ \t]*On .{5,90} wrote:|^[ \t]*Am .{5,90} schrieb", re.I | re.M)
LOT = re.compile(r"^[ \t*\-•]*(?:Lot|Los|Position|Pos\.?|Partie|Parti|Lote|Lotto)\s*(?:no\.?|nr\.?|#)?\s*(\d+)\s*[:.)\-–][ \t]*(.+)$", re.I | re.M)
OTHER_UNITS = re.compile(r"\b(?:lbs?|pounds?|inch(?:es)?|cubic f(?:ee|oo)t|cu\.? ?ft|ft3|feet|foot)\b|\d\s*(?:\"|in\b)", re.I)
EACH = ("each", "je", "jeweils", "per piece", "pro stück", "pro stueck")
SUM = ("together", "zusammen", "insgesamt", "total", "in total", "gesamt", "combined")
PER = r"(?:\b(each|je|jeweils|per piece|pro st[üu]e?ck|together|zusammen|insgesamt|in total|total|gesamt|combined)\s+)?"
WEIGHT = re.compile(PER + r"(\d[\d.,]*)\s*kg\b[ \t]*(gross|brutto|net|netto)?", re.I)
DIMS = re.compile(PER + r"(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(cm|mm|m)\b", re.I)
CBM = re.compile(PER + r"(\d[\d.,]*)\s*(?:cbm|m3|m³|cubic met(?:er|re)s?)\b", re.I)
COUNT = re.compile(r"\s*(\d+)\s*(?:x\s*)?[A-Za-zÄÖÜäöü]")


def _num(s, weight=False):
    s = s.strip().rstrip(".,")
    if weight and re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):         # 1,200 kg / 1.200 kg: thousands, never 1.2 kg
        return float(re.sub(r"[.,]", "", s))
    if s.count(",") and s.count("."):                                # 1,234.5 or 1.234,5
        last = max(s.rfind(","), s.rfind("."))
        return float(re.sub(r"[.,]", "", s[:last]) + "." + s[last + 1:])
    return float(s.replace(",", "."))


def _times(per, count):
    """How often the figure counts: 'each' -> per piece, 'together' -> once, nothing said -> only clear for one piece."""
    per = (per or "").lower().replace("stueck", "stück")
    if per in EACH:
        return count
    if per in SUM or count == 1:
        return 1
    return None


def one(line):
    """(kg, cbm) of one lot line, or None when it cannot be read fully."""
    if OTHER_UNITS.search(line):
        return None
    m = COUNT.match(line)
    count = int(m.group(1)) if m else 1
    if count < 1:
        return None
    weights = [w for w in WEIGHT.finditer(line) if (w.group(3) or "").lower() not in ("net", "netto")]
    gross = [w for w in weights if w.group(3)] or weights             # the one marked gross; else the only weight given
    if not gross:
        return None
    w = gross[0]
    times = _times(w.group(1), count)
    if times is None:
        return None
    kg = _num(w.group(2), weight=True) * times
    d, v = DIMS.search(line), CBM.search(line)
    if d:
        unit = {"cm": 1e6, "mm": 1e9, "m": 1.0}[d.group(5).lower()]
        each = _num(d.group(2)) * _num(d.group(3)) * _num(d.group(4)) / unit
        cbm = each * (1 if (d.group(1) or "").lower() in SUM else count)   # a size is one piece unless it says 'together'
    elif v:
        times = _times(v.group(1), count)
        if times is None:
            return None
        cbm = _num(v.group(2)) * times
    else:
        return None
    return (kg, cbm) if kg > 0 and cbm > 0 else None


def totals(body):
    """(kg, cbm) added up from the lot lines of the customer's own text; None unless there are two or more lots and
    every one is read fully."""
    text = CHAIN.split(body or "", maxsplit=1)[0]
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(">"))
    found = LOT.findall(text)
    if len(found) < 2 or len({n for n, _ in found}) != len(found):
        return None
    parts = [one(line) for _, line in found]
    if any(p is None for p in parts):
        return None
    return round(sum(p[0] for p in parts), 3), round(sum(p[1] for p in parts), 4)
