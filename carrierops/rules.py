"""Read carrier and customer mails with rules (no LLM, no network).

classify(), own_text(), dates_in(), flight_in(), awb_in(), key_sentence() are a straight port of
ui/lib/carrier-rules.ts, so the UI and this program read a mail the same way (same tests in tests/test_rules.py).
First hit wins, so the worst news is checked first. EN + DE.

On top of the shared classify(), refine() splits what the UI calls "cancelled" into what a forwarder must do
differently: offloaded (still flies later), rebooked (a FLIGHT was cancelled, the shipment flies on another one),
cancel_confirmed (the airline confirms OUR cancellation) and cancelled (the BOOKING is gone: offer a rebook).
"""
import re
from datetime import datetime, timedelta

# ------------------------------------------------------------------ port of ui/lib/carrier-rules.ts
TYPES = ("confirmed", "booked", "delayed", "cancelled", "rebooked", "departed", "arrived", "delivered", "price", "info")

RULES = [
    ("cancelled", re.compile(r"\bcancel|\bstorn|\brefus|unable to accept|cannot accept|can't accept|offload|abgelehnt|nicht annehmen")),
    ("delayed", re.compile(r"\bdelay|verspät|verspaet|verzöger|verzoeger|postpone|new eta|revised eta|neue ankunft|reschedul|verschoben")),
    ("rebooked", re.compile(r"\brebook|re-book|new flight|umgebucht|umbuchung|anderen flug")),
    ("price", re.compile(r"surcharge|price change|rate increase|new price|rate update|tariff|preisänderung|preisaenderung|zuschlag")),
    ("delivered", re.compile(r"\bdelivered\b|proof of delivery|\bpod\b|zugestellt|ausgeliefert")),
    ("arrived", re.compile(r"\barrived\b|\blanded\b|angekommen|gelandet")),
    ("departed", re.compile(r"\bdeparted\b|has left|took off|abgeflogen|on its way|unterwegs")),
    ("confirmed", re.compile(r"\bconfirmed\b|bestätigt|bestaetigt")),
    ("booked", re.compile(r"thank you for your booking|status:\s*booked\b|\bgebucht\b|booking received|buchung erhalten")),
]

_QUOTE_START = re.compile(r"^\s*(on .+wrote:|am .+schrieb.*:|-----\s*original message)", re.I)


def own_text(body):
    """The sender's own words: quoted lines ('>') and everything after 'On ... wrote:' are dropped."""
    out = []
    for line in re.split(r"\r?\n", body or ""):
        if re.match(r"^\s*>", line):
            continue
        if _QUOTE_START.match(line):
            break
        out.append(line)
    return "\n".join(out)


def classify(subject, body):
    t = ("%s\n%s" % (subject or "", own_text(body))).lower()
    for typ, rx in RULES:
        if rx.search(t):
            return typ
    return "info"


MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
MON_DE = {"jan": 0, "januar": 0, "feb": 1, "februar": 1, "mär": 2, "maerz": 2, "märz": 2, "mrz": 2, "apr": 3, "mai": 4,
          "jun": 5, "juni": 5, "jul": 6, "juli": 6, "aug": 7, "sep": 8, "sept": 8, "okt": 9, "oct": 9, "nov": 10,
          "dez": 11, "dec": 11}
# English month names are covered by their first three letters (MON_DE lookup falls back to [:3]).
for _i, _m in enumerate(MON):
    MON_DE.setdefault(_m, _i)


def _fmt(y, m, d):
    return "%02d %s %d" % (d, MON[m].capitalize(), y)


def _ok(y, m, d):
    return 0 <= m < 12 and 1 <= d <= 31 and 2000 < y < 2100


_VALID = re.compile(r"valid (?:until|till|to)[^.\n]*|gültig bis[^.\n]*", re.I)
_RX_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_RX_DE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b")
_RX_WORD = re.compile(r"\b(\d{1,2})\.?\s+([A-Za-zäÄ]{3,9})\.?(?:\s+(20\d\d))?\b")
_RX_TIME = re.compile(r"^[\s,]*(?:at|um|gegen|,)?\s*(\d{1,2}):(\d{2})")


def _month(word):
    w = word.lower()
    return MON_DE.get(w, MON_DE.get(w[:3]))


def date_hits(text, year=None):
    """Every date in the sender's own text: [(pos, 'YYYY-MM-DD', 'HH:MM' or None)], in text order.
    Validity dates of offers ('valid until ...') are not news and are skipped."""
    year = year or datetime.utcnow().year
    t = _VALID.sub(lambda m: " " * len(m.group(0)), own_text(text))
    hits = []

    def add(pos, end, y, m, d):
        if not _ok(y, m, d):
            return
        try:
            datetime(y, m + 1, d)
        except ValueError:
            return
        tm = _RX_TIME.match(t[end:end + 16])
        hhmm = "%02d:%s" % (int(tm.group(1)), tm.group(2)) if tm and int(tm.group(1)) < 24 else None
        hits.append((pos, "%04d-%02d-%02d" % (y, m + 1, d), hhmm))

    for m in _RX_ISO.finditer(t):
        add(m.start(), m.end(), int(m.group(1)), int(m.group(2)) - 1, int(m.group(3)))
    for m in _RX_DE.finditer(t):
        add(m.start(), m.end(), int(m.group(3)), int(m.group(2)) - 1, int(m.group(1)))
    for m in _RX_WORD.finditer(t):
        mo = _month(m.group(2))
        if mo is None:
            continue
        add(m.start(), m.end(), int(m.group(3)) if m.group(3) else year, mo, int(m.group(1)))
    seen, out = set(), []
    for h in sorted(hits):
        if h[0] not in seen:
            seen.add(h[0])
            out.append(h)
    return out


def dates_in(text, year=None):
    """Port of datesIn: up to 3 distinct dates as '27 Nov 2026', in the UI's order (ISO, then dotted, then words)."""
    year = year or datetime.utcnow().year
    t = _VALID.sub("", own_text(text))
    out = []

    def add(y, m, d):
        if _ok(y, m, d):
            s = _fmt(y, m, d)
            if s not in out:
                out.append(s)
    for m in _RX_ISO.finditer(t):
        add(int(m.group(1)), int(m.group(2)) - 1, int(m.group(3)))
    for m in _RX_DE.finditer(t):
        add(int(m.group(3)), int(m.group(2)) - 1, int(m.group(1)))
    for m in _RX_WORD.finditer(t):
        mo = _month(m.group(2))
        if mo is not None:
            add(int(m.group(3)) if m.group(3) else year, mo, int(m.group(1)))
    return out[:3]


def flight_in(text, airline_code=None):
    """Port of flightIn: the flight named after 'flight'/'Flug', else '<code> 1234' for a known airline code."""
    t = own_text(text)
    ctx = re.search(r"\b(?:flight|flug)(?:\s*(?:no\.?|number|nr\.?))?\s*:?\s*([A-Z0-9]{2}\s?\d{2,4})\b", t, re.I)
    if ctx:
        return re.sub(r"\s", " ", ctx.group(1).upper(), count=1)
    if airline_code and re.match(r"^[A-Z0-9]{2}$", airline_code):
        m = re.search(r"\b%s\s?(\d{3,4})\b" % re.escape(airline_code), t)
        if m:
            return "%s %s" % (airline_code, m.group(1))
    return None


def awb_in(text):
    m = re.search(r"\b(\d{3}-\d{8})\b", own_text(text))
    return m.group(1) if m else None


_GREETING = re.compile(r"^(hello|hi|dear|good (morning|day|afternoon)|guten|sehr geehrte|hallo|liebe)\b", re.I)


def first_sentence(body):
    lines = [l.strip() for l in re.split(r"\r?\n", own_text(body)) if l.strip()]
    lines = [l for l in lines if not _GREETING.match(l) or len(l) > 40]
    joined = re.sub(r"^(hello|hi|dear [^,]+|hallo)[,!]?\s*", "", " ".join(lines), flags=re.I)
    s = (re.split(r"(?<=[.!?])\s", joined)[0] if joined else "").strip()
    return s[:147] + "…" if len(s) > 150 else s


def key_sentence(body, rx):
    """The sentence that carries the news (e.g. the one that says 'delay'), else the opening sentence."""
    if isinstance(rx, str):
        rx = re.compile(rx, re.I)
    parts = re.split(r"(?<=[.!?])\s", re.sub(r"\s+", " ", own_text(body)))
    s = next((x.strip() for x in parts if rx.search(x)), None)
    if not s:
        return first_sentence(body)
    t = re.sub(r"^(hello|hi|dear|hallo|guten tag)( there| team| [A-Z][a-z]+)?[,!]?\s*", "", s, flags=re.I)
    return t[:147] + "…" if len(t) > 150 else t


# ------------------------------------------------------------------ carrierops additions
_OFFLOAD = re.compile(r"offload|ausgeladen|nicht verladen|nicht mitgenommen")
_REBOOK = re.compile(r"\brebook|re-book|protected on|umgebucht|umbuchung|new flight|neuer flug|moved (?:from \S+ \S+ )?to|now on|"
                     r"anderen flug|auf flug")
_BOOKING_CANCEL = re.compile(r"\b(?:booking|buchung|reservation|reservierung|shipment|sendung)\b[^.\n]{0,40}"
                             r"(?:\bcancel|\bstorn|annull)|(?:\bcancel\w*|\bstorn\w*)[^.\n]{0,20}\b(?:booking|buchung)\b")
_REFUSED = re.compile(r"\brefus|unable to accept|cannot accept|can't accept|abgelehnt|nicht annehmen")
_AS_REQUESTED = re.compile(r"as requested|as per your request|per your request|at your request|wie gewünscht|"
                           r"auf ihren wunsch|ihrem wunsch entsprechend")


def refine(typ, subject, body):
    """Split the shared 'cancelled' (and the rebook wording) into what the forwarder must do."""
    t = ("%s\n%s" % (subject or "", own_text(body))).lower()
    if typ == "cancelled":
        if _AS_REQUESTED.search(t):
            return "cancel_confirmed"
        if _OFFLOAD.search(t):
            return "offloaded"
        if _REBOOK.search(t) and not _BOOKING_CANCEL.search(t) and not _REFUSED.search(t):
            return "rebooked"            # 'flight YT 880 cancelled, shipment rebooked on YT 884': still flies
        return "cancelled"
    return typ


UPDATE_TYPES = ("confirmed", "booked", "picked_up", "handed_over", "departed", "delayed", "offloaded", "rebooked",
                "cancelled", "cancel_confirmed", "arrived", "delivered", "price", "info")


def classify_carrier(subject, body):
    """-> (type, ui_type). ui_type is exactly what the UI shows; type is the refined one we act on."""
    ui = classify(subject, body)
    return refine(ui, subject, body), ui


# Truckers: "delivered to the airline terminal" is OUR pickup leg finishing, never the consignee's POD.
TRUCKER_RULES = [
    ("cancelled", re.compile(r"\bcancel|\bstorn|cannot (?:do|pick|collect)|unable to (?:pick|collect)|nicht möglich|absage")),
    ("delayed", re.compile(r"\bdelay|verspät|verspaet|verzöger|\blater\b|später|verschoben|postpone")),
    ("handed_over", re.compile(r"delivered (?:it |them |the goods )?(?:to|at) (?:the )?(?:[\w-]+ ){0,3}(?:airport|airline|terminal|warehouse|cargo)|"
                               r"handed (?:it |them )?over|"
                               r"übergeben|angeliefert|am flughafen abgegeben|dropped off at")),
    ("picked_up", re.compile(r"picked up|collected|abgeholt|\bloaded\b|geladen")),
    ("confirmed", re.compile(r"\bconfirm|bestätig|bestaetig|\baccept|we will (?:pick|collect)|wir holen")),
]


def classify_trucker(subject, body):
    t = ("%s\n%s" % (subject or "", own_text(body))).lower()
    for typ, rx in TRUCKER_RULES:
        if rx.search(t):
            return typ
    return "info"


KEY = {
    "delayed": r"delay|verspät|verzöger|new eta|neue ankunft|postpone",
    "offloaded": r"offload|ausgeladen",
    "rebooked": r"rebook|protected|umgebucht|new flight|neuer flug",
    "cancelled": r"cancel|storn|refus|unable|cannot",
    "cancel_confirmed": r"cancel|storn",
    "price": r"surcharge|price|rate|tariff|zuschlag|preis",
    "delivered": r"deliver|pod|zugestellt",
    "arrived": r"arriv|landed|angekommen|gelandet",
    "departed": r"depart|left|took off|abgeflogen|unterwegs",
    "picked_up": r"picked|collected|abgeholt",
    "handed_over": r"deliver|handed|übergeben|angeliefert",
    "confirmed": r"confirm|bestätig",
}

# --- flights: the NEW flight is the one after 'to / on / new flight / protected on', not the one after 'from'
_FLIGHT_TOKEN = re.compile(r"\b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{2,4})\b")
_NEW_BEFORE = re.compile(r"(?:\bto|\bon|new flight|neuer flug|flight|flug|protected on|rebooked on|umgebucht auf|auf|mit|"
                         r"offer|anbieten|now on)\W{0,3}$", re.I)
_OLD_BEFORE = re.compile(r"(?:\bfrom|\bvon|offloaded from|instead of|statt|was)\W{0,3}$", re.I)


def flights(text, airline_code=None):
    """-> (new_flight, old_flight). Flight numbers like 'YT 4412'. The new one is the last one named after
    to/on/new flight/protected on; the old one is named after from/was."""
    t = own_text(text)
    toks = []
    for m in _FLIGHT_TOKEN.finditer(t):
        code, num = m.group(1), m.group(2)
        if code in ("BK", "PO", "NR", "NO"):
            continue
        before = t[max(0, m.start() - 20):m.start()]
        toks.append(("%s %s" % (code, num), before))
    if not toks:
        f = flight_in(text, airline_code)
        return f, None
    old = next((f for f, b in toks if _OLD_BEFORE.search(b)), None)
    new = [f for f, b in toks if _NEW_BEFORE.search(b) and not _OLD_BEFORE.search(b)]
    if new:
        return new[-1], old
    rest = [f for f, b in toks if f != old]
    return (rest[-1] if rest else None), old


def offer_in(text, airline_code=None):
    """An alternative the airline offers after a cancellation: ('YT 890', '2026-11-28') or (None, None)."""
    t = own_text(text)
    m = re.search(r"(?:we can offer|we could offer|alternative|können .{0,20}anbieten|angebot)[^.\n]{0,80}", t, re.I)
    if not m:
        return None, None
    seg = m.group(0)
    f = _FLIGHT_TOKEN.search(seg)
    d = date_hits(seg)
    return ("%s %s" % (f.group(1), f.group(2)) if f else None), (d[0][1] if d else None)


_ETA_NEW = re.compile(r"\b(?:new eta|revised eta|new arrival|neue ankunft|neuer ankunftstermin|now arriv\w*)", re.I)
_ETA_ANY = re.compile(r"\b(?:eta|arriv\w*|ankunft|ankommen|landet|landing)\b", re.I)


def eta_in(text, year=None):
    """The (new) arrival date in the text: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM', else None.
    Takes the first date after 'new ETA / neue Ankunft', else after 'ETA / arrival / Ankunft' (within 60 chars).
    '(was 25 Nov)' after the new date is ignored because the first date after the keyword wins."""
    t = own_text(text)
    hits = date_hits(t, year)
    if not hits:
        return None
    for rx in (_ETA_NEW, _ETA_ANY):
        for k in rx.finditer(t):
            for pos, iso, hhmm in hits:
                if k.end() <= pos <= k.end() + 60:
                    return iso + (" " + hhmm if hhmm else "")
    return None


_WORDNUM = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "einen": 1, "ein": 1, "zwei": 2, "drei": 3}


def delay_by_hours(text):
    """'delayed by 24 hours', 'one day later', '2 Tage später' -> hours (float) or None."""
    t = own_text(text).lower()
    m = re.search(r"(?:delayed|postponed|verspätet|verschoben)\s+(?:by|um)\s+(\d+|one|two|three|a|an|einen|zwei|drei)\s*"
                  r"(hours?|hrs?|h\b|days?|stunden?|tage?n?)", t)
    if not m:
        m = re.search(r"(\d+|one|two|three|a|an|einen|ein|zwei|drei)\s*(hours?|hrs?|days?|stunden?|tage?n?)\s+"
                      r"(?:later|delay\w*|späte\w*|verspät\w*)", t)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _WORDNUM.get(m.group(1), 1)
    unit = m.group(2)
    return float(n * 24 if unit.startswith(("day", "tag")) else n)


def tracking_url_in(text):
    m = re.search(r"https?://[^\s<>\"')]+", own_text(text))
    return m.group(0).rstrip(".,;") if m else None


_PRICE = re.compile(r"(?:price|rate|amount|total|preis|betrag)\s*:?\s*(?:EUR|€|USD|\$)?\s*([0-9][0-9.,]*)\s*(EUR|€|USD|\$)?", re.I)


def price_in(text):
    """'Price: 1191.40 EUR' -> 1191.40 (float) or None."""
    m = _PRICE.search(own_text(text))
    if not m:
        return None
    s = m.group(1).rstrip(".,")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def refs_in(text):
    """Booking references in a text: {'bk': [...], 'google': [thread ids]}."""
    t = text or ""
    return {"bk": [x.upper() for x in re.findall(r"\b(BK-[A-Z0-9]{4,})\b", t, re.I)],
            "google": [int(x) for x in re.findall(r"\bGOOGLE-(\d+)\b", t, re.I)]}


def lane_in(text):
    """'FRA-ORD', 'FRA to ORD', 'FRA nach ORD' -> ('FRA', 'ORD') or None."""
    m = re.search(r"\b([A-Z]{3})\s*(?:-|–|to|nach|->|/)\s*([A-Z]{3})\b", text or "")
    return (m.group(1), m.group(2)) if m else None


# ------------------------------------------------------------------ customer mails (only in a booked thread)
# Copied from booking/invoice.py (PAID / NOT_PAID) so we read "we have paid" the same way, without importing the clerk.
PAID = re.compile(
    r"\b(we(?: have|'ve)? (?:just |now |already |today )?(?:paid|settled|transferred|wired|remitted)|"
    r"(?:payment|transfer|remittance|bank transfer|wire) (?:has |have )?(?:been |was |is )?(?:just |now |already )?"
    r"(?:made|sent|done|completed|initiated|executed|released|processed|on (?:its|the) way)|"
    r"(?:invoice|amount|balance) (?:has been |was |is )?(?:now |already )?(?:paid|settled)|"
    r"paid (?:the|your|this|our|in full)|proof of payment|payment confirmation attached|"
    r"zahlung (?:ist |wurde )?(?:heute |bereits )?(?:erfolgt|veranlasst|angewiesen|ausgeführt|raus)|"
    r"(?:haben|wurde|ist|wird) (?:\w+ ){0,3}(?:überwiesen|bezahlt|beglichen))", re.I)
NOT_PAID = re.compile(r"\b(not(?: yet)?|n't|never|noch nicht|nicht|kein\w*|once|as soon as|when|will|going to|werden|"
                      r"sobald|wenn)\b[^.!?\n]{0,25}\b(paid|pay|transfer\w*|settled|überwies\w*|bezahl\w*|zahl\w*)", re.I)
STATUS_Q = re.compile(r"\b(where|status|update|news|eta|arriv\w*|when will|track\w*|wo ist|wo befindet|wann|stand|"
                      r"neuigkeiten|ankunft|ankommen|sendungsverfolgung|any word)\b", re.I)
REBOOK_YES = re.compile(r"\b(yes|ja|ok|okay|go ahead|please (?:do|rebook|book)|bitte (?:umbuchen|buchen)|"
                        r"einverstanden|take it|agreed?|fine|passt|gerne)\b", re.I)
REBOOK_NO = re.compile(r"\b(no|nein|cancel|storn\w*|do not|don't|nicht)\b", re.I)


def customer_intent(subject, body, status=None):
    """-> 'paid' | 'rebook_yes' | 'rebook_no' | 'status_question' | None (not ours: the clerk handles it)."""
    t = own_text(body)
    if PAID.search(t) and not NOT_PAID.search(t):
        return "paid"
    if status == "cancelled_by_airline":
        if REBOOK_YES.search(t) and not REBOOK_NO.search(t):
            return "rebook_yes"
        if REBOOK_NO.search(t) and not STATUS_Q.search(t):
            return "rebook_no"
    if STATUS_Q.search(t) or "?" in t and re.search(r"shipment|sendung|cargo|ware|flight|flug", t, re.I):
        return "status_question"
    return None


# ------------------------------------------------------------------ dates
def parse_eta(s):
    """'YYYY-MM-DD[ HH:MM]' -> datetime (noon when no time is given, so day deltas round sensibly) or None."""
    if not s:
        return None
    try:
        if len(s) > 10:
            return datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(hour=12)
    except ValueError:
        return None


def hours_between(old, new):
    a, b = parse_eta(old), parse_eta(new)
    if not a or not b:
        return None
    if len(old) <= 10 or len(new) <= 10:          # one side is a date only: compare whole days
        return float((b.date() - a.date()).days * 24)
    return round((b - a).total_seconds() / 3600.0, 1)


def add_hours(eta, hours):
    d = parse_eta(eta)
    if not d or hours is None:
        return None
    n = d + timedelta(hours=hours)
    return n.strftime("%Y-%m-%d %H:%M") if len(eta) > 10 else n.strftime("%Y-%m-%d")
