"""The last touch on a quote mail, right before it is sent. Owner: Riky.

The board pays +10 per round for the most human accepted mail (START Milan 4, us 0 at 18:30). audit/emails.py found
what gives us away; this fixes it deterministically:

  1. greet with the name the customer SIGNED with ("Hi Anna," not "Hi Sonnberg," or "Hi Lindqvist,")
  2. answer the customer's own questions: earliest arrival / departure (ready date + transit days), insurance,
     customs, a USD request: one honest sentence each, in the mail's language (en / de)
  3. remove doubled units ("1,619 kg kg")

    body, changes = humanize.polish(body, fields, best, customer_mail)

Never touches a digit of the price, never makes a gateway call, never raises (any error -> the body unchanged).
"""
import datetime, re

CLOSINGS = r"(?:best|bests|ciao|cheers|thanks|thx|regards|(?:kind |best |warm |many )?(?:regards|greetings|wishes|thanks|thank you(?: in advance)?|cheers|grüße|gruesse|grüßen|mit freundlichen grüßen|viele grüße|best greetings.*|cordiali saluti|saludos|cordialement))"


def signed_name(customer_mail):
    """First name of the person who signed the customer's mail, or None."""
    lines = [l.strip() for l in (customer_mail or "").strip().splitlines() if l.strip()]
    tail = lines[-6:]
    for i, line in enumerate(tail):
        if re.fullmatch(CLOSINGS + r"[ ,.!/a-zA-Z]*", line, re.I) and i + 1 < len(tail):
            m = re.match(r"([A-ZÄÖÜ][a-zäöüß]+)(?: [A-ZÄÖÜ][a-zäöüß\-]+)?$", tail[i + 1])
            if m:
                return m.group(1)
    for line in tail:                                        # no closing line: a lone "Sara" / "Anna Sonnberg" line
        m = re.fullmatch(r"([A-ZÄÖÜ][a-zäöüß]+)(?: [A-ZÄÖÜ][a-zäöüß\-]+)?", line)
        if m and not re.fullmatch(CLOSINGS + r"[ ,.!]*", line, re.I) and \
                not re.search(r"gmbh|ag\b|ltd|inc|medtech|logistics|audio|sport|team", line, re.I):
            return m.group(1)
    return None


def _ready_date(text):
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", text or "")
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _city(text, code):
    """'JFK (New York, US)' -> 'New York'; else the airport code."""
    m = re.search(re.escape(code or "") + r"\s*\(([^,()]+)", text or "") if code else None
    return m.group(1).strip() if m else (code or "the destination")


def _day(d, lang):
    if lang == "de":
        return d.strftime("%d.%m.")
    return d.strftime("%a %-d %b")


def _sentences(body, fields, best, mail, lang):
    low_mail, low_body = (mail or "").lower(), body.lower()
    out = []
    asks_arrival = re.search(r"\barriv|\beta\b|\bland(?:s|ed|ing)?\b|ankunft|ankommen|\bwhen\b[^.?\n]*\b(?:there|delivered)\b",
                             low_mail)
    asks_departure = re.search(r"departure|abflug|depart", low_mail)
    has_date = (re.search(r"\b\d{1,2}(?:\.\d{1,2}\.| (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))\b", body)
                or re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri)\b", body, re.I)
                or re.search(r"\b20\d\d-\d\d-\d\d\b", body))
    days = best.get("transit_days") if isinstance(best, dict) else None
    if (asks_arrival or asks_departure) and not has_date and days:
        ready = _ready_date(mail) or datetime.date.today()
        arrive = ready + datetime.timedelta(days=int(round(float(days))))
        city = _city(mail, fields.get("destination"))
        if lang == "de":
            out.append(f"Wenn die Ware am {_day(ready, lang)} bereitsteht, fliegt sie direkt danach ab und ist "
                       f"voraussichtlich am {_day(arrive, lang)} in {city}.")
        else:
            out.append(f"If it's ready on {_day(ready, lang)}, it can fly right away and should arrive in {city} "
                       f"around {_day(arrive, lang)}.")
    if re.search(r"insur|versicher", low_mail) and not re.search(r"insur|versicher", low_body):
        out.append("Die Transportversicherung ist im Preis nicht enthalten, die ergänzen wir gern." if lang == "de" else
                   "Cargo insurance isn't included in this price; happy to add it if you need it.")
    if re.search(r"customs|zoll|clearance", low_mail) and not re.search(r"customs|zoll|clearance", low_body):
        out.append("Die Verzollung ist nicht enthalten, sagen Sie einfach Bescheid, wenn wir sie übernehmen sollen."
                   if lang == "de" else
                   "Customs clearance isn't included; just let me know if you'd like us to take care of it.")
    if re.search(r"\b(?:in|im) usd\b|us dollars?", low_mail) and "usd" not in low_body:
        out.append("Unsere Tarife sind in EUR, daher ist der Gesamtpreis in EUR." if lang == "de" else
                   "Our rates are in EUR, so I've quoted the total in EUR.")
    return out


def _insert_before_signoff(body, sentence):
    m = re.search(r"\n\s*(?:best|kind|warm|many)?\s*(?:regards|wishes|greetings|cheers|thanks|mit freundlichen|"
                  r"viele grüße|beste grüße|herzliche grüße)\b", body, re.I)
    if m:
        return body[:m.start()].rstrip() + "\n\n" + sentence + "\n\n" + body[m.start():].lstrip("\n")
    return body.rstrip() + "\n\n" + sentence


def polish(body, fields=None, best=None, customer_mail=""):
    """-> (body, changes). changes lists what was done, for the event log."""
    if not body:
        return body, []
    try:
        fields, best = fields or {}, best or {}
        changes, text = [], body or ""
        lang = "de" if (fields.get("language") or "").startswith("de") else "en"
        name = signed_name(customer_mail)
        m = re.match(r"(\s*(?:hi|hello|dear|hallo|guten tag)\s+)([^,\n]+)(,)", text, re.I)
        if m and name and name not in m.group(2) and not re.search(r"sir|madam|team|damen|herr|frau", m.group(2), re.I):
            text = text[:m.start(2)] + name + text[m.end(2):]
            changes.append("greeting_name")
        fixed = re.sub(r"\b(kg|cbm|EUR|USD)(\s+\1\b)+", r"\1", text)
        if fixed != text:
            text = fixed
            changes.append("doubled_unit")
        for s in _sentences(text, fields, best, customer_mail, lang):
            text = _insert_before_signoff(text, s)
            changes.append("answered_ask")
        return text, changes
    except Exception:
        return body, []
