"""The ONE gateway call per RFQ: read the customer's mail and write the reply text.

The model never does math and never invents a price. It returns:
  - the shipment fields as JSON (code computes weight, volume and price from them)
  - a reply text with placeholders {PRICE} {AIRLINE} {TRANSIT_DAYS}, which code fills in later
"""
import json, os, re, zlib
from core import config, mailbox

SIGNER = os.environ.get("SIGNER", "Lena Hofmann")   # the person who signs our mails (jury: most human email)

SYSTEM = """You work at an air freight forwarder in Germany. Read the customer's email and answer with JSON only:
{
 "origin": IATA code of the German departure airport (FRA, MUC, DUS, HAM, STR, CGN) or null if not given,
 "destination": IATA code of the destination airport or null,
 "pickup_postcode": German postcode if the customer wants pickup at their door, else null,
 "weight_kg": total gross weight in kg if stated as a total, else null,
 "volume_cbm": total volume in cubic meters if stated directly, else null,
 "pieces": [{"count": n, "l_cm": n, "w_cm": n, "h_cm": n, "kg_each": n or null}] if dimensions are given, else [],
 "prefer": "fastest" if the customer asks for the fastest/most urgent option, else "cheapest",
 "kind": "new_request" if the customer asks for a price for a shipment, "accept" if they accept an offer, "question" if they only ask something, else "other",
 "multi_shipment": true if the email asks prices for more than one separate shipment (different routes or separate consignments), else false,
 "shipments": if multi_shipment is true, one object per shipment with the same keys as above: [{"origin", "destination", "pickup_postcode", "weight_kg", "volume_cbm", "pieces", "prefer"}], else [],
 "dangerous_goods": true if dangerous goods, hazmat, DGR, UN numbers or lithium batteries are mentioned, else false,
 "currency": currency code if the customer asks for a specific currency, else null,
 "language": ISO 639-1 code of the language the customer wrote in ("en", "de", ...),
 "missing": list of fields you could not find,
 "reply": the reply email body
}
Do not calculate anything. Copy numbers as written (convert units to cm and kg only).
The reply: write it in the language of the customer's email, never any other (an English email gets an English reply, a German email a German reply). Greet with the name exactly as the customer signed (for example "Hi Anna" or "Guten Tag K. Weber"); never add Frau, Herr, Mr or Ms; no name -> "Hello" / "Guten Tag".
Write like an experienced, friendly forwarder answering between two calls: 3 to 5 short sentences, plain words, no lists, no headings.
Refer to THEIR shipment in their own words (what it is, where from and to, a detail they mentioned) so it is clearly not a form letter. Use {ROUTE} and {WEIGHT} if you want, code fills them in.
Never use: "I hope this email finds you well", "Thank you for reaching out", "Certainly", "delighted", "Please do not hesitate", "valued customer", exclamation marks in a row, emojis.
State one all-in price using exactly the placeholder {PRICE}. Mention {AIRLINE} and {TRANSIT_DAYS} days transit.
End with one easy next step: they can simply reply to book it.
If there are several shipments, do NOT use {PRICE}, {AIRLINE} or {TRANSIT_DAYS}: put {PRICE_TABLE} on its own line where the per-shipment prices go and state the all-in total with {TOTAL}.
Never write a number for the price yourself. Do NOT write any closing or signature (no "Best regards", no name): our system adds it. Never use the customer's name or signature as ours."""

# USD per 1M tokens (input, output). Only used for our own log; 5U measures the real cost.
PRICES = {"gpt-4o-mini": (0.15, 0.60)}

FALLBACK_REPLY = ("Hello,\n\nthank you for your request. Our all-in price is {PRICE} with {AIRLINE}, "
                  "transit time {TRANSIT_DAYS} days.\n\nBest regards\nYour forwarding team")


FALLBACK_REPLY_DE = ("Guten Tag,\n\nvielen Dank für Ihre Anfrage. Unser Gesamtpreis beträgt {PRICE} mit {AIRLINE}, "
                     "Laufzeit {TRANSIT_DAYS} Tage.\n\nViele Grüße\nIhr Forwarding-Team")

# The model writes the reply text, so a customer can talk it into promises. Anything that is not ours to promise,
# or a number we did not compute, sends the reply back to a fixed template (same price, no risk).
_UNSAFE = re.compile(r"https?://|www\.|\S+@\S+\.\w+|\d+\s*%|\d[\d.,]*\s*(eur|€|usd|\$|chf|gbp|£)|(eur|€|usd|\$)\s*\d|"
                     r"\b(guarante\w*|garanti\w*|refund\w*|erstatt\w*|discount\w*|rabatt\w*|free of charge|kostenlos\w*|"
                     r"gratis|promis\w*|versprech\w*|insur\w*|versicher\w*|valid until|gültig bis|compensat\w*|"
                     r"entschädig\w*|liab\w*|haft\w*|no extra|keine zusatz\w*|lowest price|best price guaranteed)\b", re.I)
_PLACEHOLDER = re.compile(r"\{(PRICE|AIRLINE|TRANSIT_DAYS|PRICE_TABLE|TOTAL|ROUTE|WEIGHT|SIGNER)\}")


CITY = {"FRA": "Frankfurt", "MUC": "Munich", "DUS": "Düsseldorf", "HAM": "Hamburg", "STR": "Stuttgart", "CGN": "Cologne",
        "ATL": "Atlanta", "BKK": "Bangkok", "BOG": "Bogotá", "BOM": "Mumbai", "CAI": "Cairo", "DEL": "Delhi",
        "DFW": "Dallas", "DOH": "Doha", "DXB": "Dubai", "EZE": "Buenos Aires", "GRU": "São Paulo", "HKG": "Hong Kong",
        "ICN": "Seoul", "JFK": "New York", "JNB": "Johannesburg", "KUL": "Kuala Lumpur", "LAX": "Los Angeles",
        "LIM": "Lima", "LOS": "Lagos", "MEL": "Melbourne", "MEX": "Mexico City", "MIA": "Miami", "MNL": "Manila",
        "NBO": "Nairobi", "NRT": "Tokyo", "ORD": "Chicago", "PEK": "Beijing", "PVG": "Shanghai", "RUH": "Riyadh",
        "SCL": "Santiago", "SGN": "Ho Chi Minh City", "SIN": "Singapore", "SYD": "Sydney", "TLV": "Tel Aviv",
        "TPE": "Taipei", "YYZ": "Toronto", "ASU": "Asunción", "KTM": "Kathmandu", "PPT": "Papeete",
        "TNR": "Antananarivo", "ULN": "Ulaanbaatar"}
CITY_DE = {"MUC": "München", "CGN": "Köln", "CAI": "Kairo", "MEX": "Mexiko-Stadt", "NRT": "Tokio", "PEK": "Peking",
           "SIN": "Singapur", "RUH": "Riad"}

HUMAN = {
    "en": [
        "{HELLO}\n\nthanks for sending the details for {ROUTE}. For your {WEIGHT} we can do {PRICE} all-in with {AIRLINE}, "
        "around {TRANSIT_DAYS} days in transit.\n\nIf that works for you, just reply to this mail and I'll book it right away.\n\n"
        "Best regards\n{SIGNER}\nAir Export",
        "{HELLO}\n\nI've checked {ROUTE} for your {WEIGHT}: the best option right now is {AIRLINE} at {PRICE} all-in, "
        "with about {TRANSIT_DAYS} days in transit.\n\nShall I go ahead? A short reply is enough and I'll take care of the booking.\n\n"
        "Kind regards\n{SIGNER}\nAir Export",
        "{HELLO}\n\ngood news on {ROUTE}: we can move your {WEIGHT} with {AIRLINE} for {PRICE} all-in, "
        "transit roughly {TRANSIT_DAYS} days.\n\nLet me know and I'll get it booked for you.\n\n"
        "Best wishes\n{SIGNER}\nAir Export",
    ],
    "de": [
        "{HELLO}\n\ndanke für Ihre Anfrage {ROUTE}. Für Ihre {WEIGHT} können wir {PRICE} all-in mit {AIRLINE} anbieten, "
        "Laufzeit etwa {TRANSIT_DAYS} Tage.\n\nWenn das für Sie passt, antworten Sie einfach kurz und ich buche direkt.\n\n"
        "Viele Grüße\n{SIGNER}\nLuftfracht Export",
        "{HELLO}\n\nich habe {ROUTE} für Ihre {WEIGHT} geprüft: Am besten passt aktuell {AIRLINE} mit {PRICE} all-in, "
        "rund {TRANSIT_DAYS} Tage Laufzeit.\n\nSoll ich das so buchen? Eine kurze Antwort genügt.\n\n"
        "Beste Grüße\n{SIGNER}\nLuftfracht Export",
    ],
}


def _route(fields, lang):
    o, d = (fields.get("origin") or "").upper(), (fields.get("destination") or "").upper()
    names = dict(CITY, **CITY_DE) if lang == "de" else CITY
    if not (o and d):
        return "your shipment" if lang != "de" else "Ihre Sendung"
    return ("von %s nach %s" if lang == "de" else "%s to %s") % (names.get(o, o), names.get(d, d))


def _weight(fields, lang):
    w = fields.get("weight_kg_total") or fields.get("weight_kg")
    if not w:
        return "shipment" if lang != "de" else "Sendung"
    txt = ("{:,.0f}".format(float(w)) if float(w) == int(float(w)) else "{:,.1f}".format(float(w)))
    return (txt.replace(",", "X").replace(".", ",").replace("X", ".") + " kg") if lang == "de" else (txt + " kg")


SIGN_OFF = {"en": ["Best regards", "Kind regards", "Best wishes"], "de": ["Viele Grüße", "Beste Grüße", "Freundliche Grüße"]}
_CLOSING = re.compile(r"^\s*(best|kind|warm)?\s*(regards|wishes)|^\s*(many\s+)?thanks|^\s*cheers|^\s*sincerely|^\s*yours|"
                      r"^\s*(viele|beste|freundliche|herzliche|liebe)\s+grüße|^\s*mit\s+freundlichen|^\s*\{SIGNER\}", re.I)


def _own_signature(body, lang, thread_id):
    """Cut whatever sign-off the model wrote (it once signed with the CUSTOMER's name) and add ours."""
    lines = body.rstrip().split("\n")
    for i in range(len(lines) - 1, max(len(lines) - 6, 0) - 1, -1):
        if _CLOSING.search(lines[i]):
            lines = lines[:i]
            break
    sign = SIGN_OFF[lang][zlib.crc32(str(thread_id).encode()) % len(SIGN_OFF[lang])]
    team = "Luftfracht Export" if lang == "de" else "Air Export"
    return "\n".join(lines).rstrip() + "\n\n%s\n%s\n%s" % (sign, SIGNER, team)


def fill_reply(template, best, fields, customer="", thread_id=0):
    """Fill our placeholders. No usable model reply (or one with an unknown placeholder) -> a human fallback."""
    lang = "de" if (fields.get("language") or "").lower() == "de" else "en"
    if not template or "{PRICE}" not in template:
        variants = HUMAN[lang]
        template = variants[zlib.crc32(str(thread_id).encode()) % len(variants)]
    from booking.replies import first_name
    name = first_name(customer)
    hello = ("Hallo %s," % name if lang == "de" else "Hi %s," % name) if name else ("Guten Tag," if lang == "de" else "Hello,")
    vals = {"PRICE": "%s %s" % (best["total"], best["currency"]), "AIRLINE": best["airline"],
            "TRANSIT_DAYS": str(best["transit_days"]), "ROUTE": _route(fields, lang), "WEIGHT": _weight(fields, lang),
            "SIGNER": SIGNER, "HELLO": hello}
    body = re.sub(r"\{(PRICE|AIRLINE|TRANSIT_DAYS|ROUTE|WEIGHT|SIGNER|HELLO)\}", lambda m: vals[m.group(1)], template)
    if re.search(r"\{[A-Z_]+\}", body):                      # unknown placeholder from the model: use our own text
        return fill_reply("", best, fields, customer, thread_id)
    return _own_signature(body, lang, thread_id)


def safe_reply(text, lang="en", multi=False):
    """Return the model's reply if it only uses our placeholders and promises nothing; else a fixed template."""
    t = text or ""
    if t and not _UNSAFE.search(_PLACEHOLDER.sub("", t)):
        return t, True
    if multi:
        return "", False                                    # pricing/multi.py uses its own fallback
    return HUMAN["de" if (lang or "").lower() == "de" else "en"][0], False   # human fallback, same price


def _fill_places(fields, mail):
    """The model sometimes returns null for a city it knows in another language: fill from our own city list."""
    if fields.get("origin") and fields.get("destination"):
        return
    from shared.rfq import extract_rfq
    r = extract_rfq(mail.get("subject") or "", mail.get("body") or "")
    for k in ("origin", "destination"):
        if not fields.get(k) and getattr(r, k):
            fields[k] = getattr(r, k)
            fields.setdefault("filled_by_code", []).append(k)


def _clip(body, head=3000, tail=3000):
    """Same token budget as before, but the end of a long mail (where the request often is) is kept too."""
    body = body or ""
    return body if len(body) <= head + tail else body[:head] + "\n[...]\n" + body[-tail:]


def extract(mail):
    """Returns (fields dict, usage dict). Exactly one gateway call."""
    if config.LLM_FAKE:
        return _fake(mail), {"fake": True}
    status, data = mailbox.api("POST", "/v1/gateway/chat/completions", timeout=45, body={
        "model": config.LLM_MODEL,
        "max_completion_tokens": config.LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": "Subject: %s\n\n%s" % (mail["subject"], _clip(mail["body"]))}],
    })
    if status != 200:
        raise RuntimeError("gateway %s: %s" % (status, str(data)[:300]))
    fields = json.loads(data["choices"][0]["message"]["content"])
    _fill_places(fields, mail)
    fields["reply"], fields["reply_ok"] = safe_reply(fields.get("reply"), fields.get("language"),
                                                     multi=len(fields.get("shipments") or []) > 1)
    u = data.get("usage") or {}
    usage = {"model": config.LLM_MODEL, "in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}
    if config.LLM_MODEL in PRICES and usage["in"] is not None:
        pi, po = PRICES[config.LLM_MODEL]
        usage["cost_usd"] = round((usage["in"] * pi + usage["out"] * po) / 1e6, 6)
    return fields, usage


def _fake(mail):
    """No network. Crude regex so everyone can test the loop without a key."""
    text = mail["subject"] + " " + mail["body"]
    codes = re.findall(r"\b[A-Z]{3}\b", text)
    kg = re.search(r"([\d.]+)\s*kg", text, re.I)
    cbm = re.search(r"([\d.]+)\s*(?:cbm|m3)", text, re.I)
    return {"origin": codes[0] if codes else None, "destination": codes[1] if len(codes) > 1 else None,
            "pickup_postcode": None, "weight_kg": float(kg.group(1)) if kg else None,
            "volume_cbm": float(cbm.group(1)) if cbm else None, "pieces": [],
            "prefer": "fastest" if re.search(r"fastest|urgent|schnell", text, re.I) else "cheapest",
            "kind": "new_request", "multi_shipment": False,
            "dangerous_goods": bool(re.search(r"dangerous|hazmat|dgr|lithium|UN ?\d{4}", text, re.I)),
            "currency": None, "missing": [], "reply": FALLBACK_REPLY}
