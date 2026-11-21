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


DATE = r"\b(20\d\d)-(\d\d)-(\d\d)\b"
READY_WORDS = r"ready|pick ?up|pickup|collect|collection|available|bereit|abhol|abholung|fertig"
DEADLINE_WORDS = r"arriv\w*|deliver\w*|by|before|latest|no later|deadline|until|spätestens|bis|benötigt|needed|must"


def _dates_near(text, words, before=90, whole_word=True):
    """Dates whose preceding text (same sentence, up to `before` chars) contains one of `words`."""
    out, prev_end = [], 0
    for m in re.finditer(DATE, text or ""):
        ctx = (text or "")[max(prev_end, m.start() - before):m.start()]   # only words AFTER the previous date
        ctx = re.split(r"[.!?\n]", ctx)[-1]                    # stay inside the sentence
        after = re.split(r"[.!?\n,;]|\b20\d\d-", (text or "")[m.end():m.end() + 25])[0]
        ctx = ctx + " " + after                              # German puts it after: "am 2026-11-28 abholbereit"
        prev_end = m.end()
        if re.search(r"\b(?:" + words + r")" + (r"\b" if whole_word else ""), ctx, re.I):
            try:
                out.append(datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            except ValueError:
                pass
    return out


def _ready_date(text):
    """The date the goods are READY (a date next to ready / pickup / available...). None if unsure: then we say
    nothing about arrival, a deadline must never be read as the ready date (Kai's review of #24)."""
    ready = _dates_near(text, READY_WORDS, whole_word=False)   # "abholbereit", "pickup-ready"
    return ready[0] if ready else None


def _deadline(text):
    """An arrival deadline the customer states ('must arrive by 2026-11-24'), or None."""
    ready = set(_dates_near(text, READY_WORDS, whole_word=False))
    dl = [d for d in _dates_near(text, DEADLINE_WORDS) if d not in ready]
    return min(dl) if dl else None


def _city(text, code):
    """'JFK (New York, US)' -> 'New York'; else the airport code."""
    m = re.search(re.escape(code or "") + r"\s*\(([^,()]+)", text or "") if code else None
    return m.group(1).strip() if m else (code or "the destination")


def _day(d, lang):
    if lang == "de":                                         # "28. November": no "28.11." that looks like an amount
        return "%d. %s" % (d.day, ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
                                   "Oktober", "November", "Dezember"][d.month - 1])
    return d.strftime("%a %-d %b")


def _sentences(body, fields, best, mail, lang):
    low_mail, low_body = (mail or "").lower(), body.lower()
    out = []
    asks_arrival = re.search(r"\barriv|\beta\b|\bland(?:s|ed|ing)?\b|ankunft|ankommen|eintreff|liefertermin|"
                             r"\bwann\b[^.?\n]*\ban\b|\bwhen\b[^.?\n]*\b(?:there|delivered)\b", low_mail)
    asks_departure = re.search(r"(?:earliest|next|first|when\b[^.?\n]*)\s*(?:possible\s+)?(?:departure|depart|flight)\b(?!\s+airport)|"
                               r"departure date|abflugdatum|wann\b[^.?\n]*abflug", low_mail)   # not "departure airport"
    has_date = (re.search(r"\b\d{1,2}(?:\.\d{1,2}\.| (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec))\b", body)
                or re.search(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri)\b", body, re.I)
                or re.search(r"\b20\d\d-\d\d-\d\d\b", body))
    days = best.get("transit_days") if isinstance(best, dict) else None
    if (asks_arrival or asks_departure) and not has_date and days:
        ready = _ready_date(mail)
        if ready:
            arrive = ready + datetime.timedelta(days=int(round(float(days))))
            deadline = _deadline(mail)
            city = _city(mail, fields.get("destination"))
            if deadline and arrive > deadline:
                pass                                         # we would miss their deadline: promise nothing
            elif lang == "de":
                when = f", also vor Ihrem Termin am {_day(deadline, lang)}" if deadline else ""
                out.append(f"Wenn die Ware am {_day(ready, lang)} bereitsteht, kann sie kurz danach abfliegen und "
                           f"wäre voraussichtlich um den {_day(arrive, lang)} in {city}{when}.")
            else:
                when = f", ahead of your {_day(deadline, lang)} deadline" if deadline else ""
                out.append(f"With the goods ready on {_day(ready, lang)}, it should depart soon after and arrive in "
                           f"{city} around {_day(arrive, lang)}{when}.")
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
    blocks = body.rstrip().split("\n\n")                    # no closing line: keep the signature block last
    last = blocks[-1].strip().splitlines()
    if len(blocks) > 1 and len(last) <= 3 and not re.search(r"[.!?:]\s*$", blocks[-1].strip()):
        return "\n\n".join(blocks[:-1]) + "\n\n" + sentence + "\n\n" + blocks[-1].strip()
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
