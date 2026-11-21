"""Reply quality gate: the last look at a quote before it goes out. Code only, $0, no gateway call.

    reasons = check(body, lang, best, fields, customer)     # [] = good to send

A reply that fails is replaced by one of our own human templates (llm/extract.py HUMAN): same price, no risk.
Why: the model once replied in German to an English mail, once signed with the customer's name, and once
wrote "drop off before the latest time provided by us" although nobody had given a time.
"""
import re
from . import lang as langmod

MAX_WORDS = 90

# Things we cannot know or promise from our data (airline, transit days, price, route, weight, pickup).
DENY = re.compile(
    r"\b(deadline\w*|drop[\s-]?off|dropped off|latest time|at the latest|cut[\s-]?off|closing time|customs|duty|duties|"
    r"insur\w+|packag\w+|packing|label\w*|paperwork|documents? (?:are|is|will)|guarante\w+|on time|by tomorrow|"
    r"frist\w*|spätestens|anlieferung\w*|anliefern|annahmeschluss|zoll\w*|verzoll\w*|versicher\w+|verpack\w+|"
    r"garanti\w+|pünktlich|dogan\w*|douane\w*|aduana\w*|assicura\w+|assurance\w*|imballa\w+|emballage\w*|"
    r"scadenza|délai|plazo)\b", re.I)

# Phrases people do not write and language models do.
AI_PHRASES = re.compile(
    r"i hope this (e-?mail|message) finds you|as an ai\b|language model|i'?d be happy to (assist|help)|happy to assist|"
    r"do not hesitate|don'?t hesitate|thank you for reaching out|feel free to reach out|valued customer|"
    r"rest assured|i trust this|kindly note|please be advised|delighted to|zögern sie nicht|"
    r"ich hoffe,? diese (e-?mail|nachricht) erreicht sie|non esiti a|n'hésitez pas|no dude en", re.I)

_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_MONEY = re.compile(r"\d[\d.,]*\s?(?:EUR|USD|CHF|GBP|€|\$|£)|(?:EUR|USD|CHF|GBP|€|\$|£)\s?\d[\d.,]*", re.I)
_PLACE = re.compile(r"\{[A-Za-z_]+\}")


def _digits(s):
    return re.sub(r"\D", "", str(s))


def numbers(text):
    """Every number in a text as bare digits ("1,234.50" -> "123450"). Used for the customer's own numbers."""
    return sorted({_digits(n) for n in _NUM.findall(text or "")})


def customer_lines(body):
    """The customer's sign-off lines (name, company): they must never show up as OUR signature."""
    lines = [l.strip(" ,.-") for l in (body or "").strip().split("\n") if l.strip()]
    return [l for l in lines[-3:] if 3 < len(l) <= 60 and len(l.split()) <= 6]


def _allowed_numbers(best, fields):
    ok = set(fields.get("customer_numbers") or [])
    try:                                                   # the weight we bill (next bracket / volume weight) is our own number too
        chargeable = max(float(fields.get("weight_kg_total") or fields.get("weight_kg") or 0),
                         float(fields.get("volume_cbm_total") or fields.get("volume_cbm") or 0) * 167)
    except (TypeError, ValueError):
        chargeable = 0
    for v in (best.get("total"), best.get("transit_days"), fields.get("weight_kg_total"), fields.get("weight_kg"),
              fields.get("volume_cbm_total"), fields.get("volume_cbm"), fields.get("pickup_postcode"), best.get("billed_kg"),
              chargeable or None, round(chargeable) if chargeable else None):
        if v in (None, ""):
            continue
        ok.add(_digits(v))
        try:
            f = float(v)
            ok.update({_digits("%.2f" % f), _digits("%.1f" % f), _digits("%g" % f)})
            if f == int(f):
                ok.add(str(int(f)))
        except (TypeError, ValueError):
            pass
    return ok


def check(body, lang, best, fields, customer="", signer="", extra_names=()):
    """-> list of reasons the reply must not go out as it is. Empty list = send it."""
    reasons, text = [], body or ""
    parts = text.rstrip().split("\n")
    main = "\n".join(parts[:-3]) if signer and len(parts) > 3 else text      # without our 3 signature lines

    if _PLACE.search(text):
        reasons.append("unfilled placeholder %s" % _PLACE.search(text).group(0))

    said = langmod.detect(main)
    if said and lang and said != lang:
        reasons.append("reply is in %s, customer wrote %s" % (said, lang))

    if signer and parts[-2:-1] != [signer]:
        reasons.append("not signed by %s" % signer)
    theirs = [l.lower() for l in list(fields.get("customer_lines") or []) + list(extra_names)]
    for line in main.split("\n")[1:]:                                         # line 0 is the greeting: their name belongs there
        l = line.strip(" ,.-").lower()
        if l and len(l.split()) <= 6 and any(l == t or (len(l) > 3 and l in t) for t in theirs):
            reasons.append("customer's own sign-off in our reply: %r" % line.strip())
            break

    price = "%s %s" % (best.get("total"), best.get("currency"))
    money = _MONEY.findall(text)
    if len(money) != 1 or price not in text:
        reasons.append("needs exactly one price (%s), found %d" % (price, len(money)))
    if str(best.get("airline") or "\0") not in text:
        reasons.append("airline %s missing" % best.get("airline"))
    # transit days are nice to have, not required: the brief only asks for one all-in total with its currency.

    words = len(main.split())
    if words > MAX_WORDS:
        reasons.append("too long: %d words" % words)

    m = DENY.search(main)
    if m:
        reasons.append("says something we cannot know: %r" % m.group(0))
    m = AI_PHRASES.search(main)
    if m:
        reasons.append("machine phrase: %r" % m.group(0))

    allowed = _allowed_numbers(best, fields)
    strange = [n for n in _NUM.findall(main) if _digits(n) not in allowed]
    if strange:
        reasons.append("number not from our data: %s" % ", ".join(strange[:3]))
    return reasons
