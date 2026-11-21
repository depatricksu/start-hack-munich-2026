"""The ONE gateway call per RFQ: read the customer's mail and write the reply text.

The model never does math and never invents a price. It returns:
  - the shipment fields as JSON (code computes weight, volume and price from them)
  - a reply text with placeholders {PRICE} {AIRLINE} {TRANSIT_DAYS}, which code fills in later
"""
import http.client, json, os, re, time, zlib
from core import config, mailbox
from . import lang as langmod, quality

SIGNER = os.environ.get("SIGNER", "Lena Hofmann")   # the person who signs our mails (jury: most human email)

SYSTEM = """You work at an air freight forwarder in Germany. Read the customer's email and answer with JSON only:
{
 "origin": IATA code of the departure airport (usually FRA, MUC, DUS, HAM, STR or CGN, but use whatever airport the customer names) or null if not given,
 "destination": IATA code of the destination airport or null,
 "pickup_postcode": German postcode if the customer wants pickup at their door, else null,
 "weight_kg": total gross weight in kg if stated as a total, else null,
 "volume_cbm": total volume in cubic meters if stated directly, else null,
 "pieces": [{"count": n, "l_cm": n, "w_cm": n, "h_cm": n, "kg_each": n or null}] if dimensions are given, else [],
 "prefer": "fastest" if the customer asks for the fastest/most urgent option, "cheapest" if they ask for the cheapest/lowest price, else "none",
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
Several "lots" or pieces that the customer wants ONE combined all-in price for, as a single consignment, are ONE shipment: add their weights and volumes into weight_kg/volume_cbm (or list them in pieces), multi_shipment stays false. multi_shipment is only true when the customer wants separate quotes for different origin/destination routes.
The reply: write it in the language of the customer's email, never any other (an English email gets an English reply, a German email a German reply). Greet with the name exactly as the customer signed (for example "Hi Anna" or "Guten Tag K. Weber"); never add Frau, Herr, Mr or Ms; no name -> "Hello" / "Guten Tag".
Write like an experienced, friendly forwarder answering between two calls: plain words, no lists, no headings.
Mirror the customer: if they wrote one or two lines, answer in two or three sentences; if they wrote a long mail, at most five.
If they wrote casually ("Hi", "Hey", first name, no greeting), be casual and use contractions; if formal ("Dear Sir or Madam",
"Sehr geehrte"), stay formal. In German always use "Sie". Never start with a thank-you formula; start with their shipment.
Two examples of the voice we want (placeholders as in your reply; do not copy the wording):
  Customer: "Hi, price for 300 kg MUC to JFK please, cheapest. Tom"
  Reply: "Hi Tom,\n\n{ROUTE} for your {WEIGHT}: {AIRLINE} is the cheapest right now at {PRICE} all-in, about {TRANSIT_DAYS} days.\n\nJust reply and I'll book it."
  Customer: "Sehr geehrte Damen und Herren, wir benötigen ein Angebot für 2 Paletten Maschinenteile, 640 kg, Abholung 70565, nach Shanghai, möglichst schnell."
  Reply: "Guten Tag,\n\nfür Ihre zwei Paletten Maschinenteile ({WEIGHT}) {ROUTE} ist {AIRLINE} die schnellste Option: {PRICE} all-in inklusive Abholung, Laufzeit rund {TRANSIT_DAYS} Tage.\n\nWenn das passt, genügt eine kurze Antwort und ich buche."
Refer to THEIR shipment in their own words (what it is, where from and to, a detail they mentioned) so it is clearly not a form letter. Use {ROUTE} and {WEIGHT} if you want, code fills them in.
Never use: "I hope this email finds you well", "Thank you for reaching out", "Certainly", "delighted", "Please do not hesitate", "valued customer", exclamation marks in a row, emojis.
State one all-in price using exactly the placeholder {PRICE}. Mention {AIRLINE} and {TRANSIT_DAYS} days transit.
End with one easy next step: they can simply reply to book it.
If there are several shipments, do NOT use {PRICE}, {AIRLINE} or {TRANSIT_DAYS}: put {PRICE_TABLE} on its own line where the per-shipment prices go and state the all-in total with {TOTAL}.
Never write a number for the price yourself. Do NOT write any closing or signature (no "Best regards", no name): our system adds it. Never use the customer's name or signature as ours.
Only state facts that are in the customer's email or behind our placeholders. Never mention deadlines, cut-off or drop-off times, customs, insurance, packaging, documents or dates of your own, and write no number the customer did not write."""

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
    "it": [
        "{HELLO}\n\ngrazie per la richiesta {ROUTE}. Per i vostri {WEIGHT} possiamo offrire {PRICE} tutto incluso con {AIRLINE}, "
        "tempo di transito circa {TRANSIT_DAYS} giorni.\n\nSe va bene, basta una breve risposta e prenoto subito.\n\n"
        "Cordiali saluti\n{SIGNER}\nAir Export",
    ],
    "fr": [
        "{HELLO}\n\nmerci pour votre demande {ROUTE}. Pour vos {WEIGHT}, nous pouvons proposer {PRICE} tout compris avec {AIRLINE}, "
        "transit d'environ {TRANSIT_DAYS} jours.\n\nSi cela vous convient, répondez simplement à ce mail et je réserve tout de suite.\n\n"
        "Cordialement\n{SIGNER}\nAir Export",
    ],
    "es": [
        "{HELLO}\n\ngracias por su solicitud {ROUTE}. Para sus {WEIGHT} podemos ofrecer {PRICE} todo incluido con {AIRLINE}, "
        "tránsito de unos {TRANSIT_DAYS} días.\n\nSi le parece bien, responda a este correo y lo reservo enseguida.\n\n"
        "Saludos cordiales\n{SIGNER}\nAir Export",
    ],
}
ROUTE_FMT = {"en": "%s to %s", "de": "von %s nach %s", "it": "da %s a %s", "fr": "de %s à %s", "es": "de %s a %s"}
NO_ROUTE = {"en": "for your shipment", "de": "für Ihre Sendung", "it": "per la vostra spedizione", "fr": "pour votre envoi",
            "es": "para su envío"}
NO_WEIGHT = {"en": "shipment", "de": "Sendung", "it": "colli", "fr": "colis", "es": "bultos"}
HELLO = {"en": ("Hi %s,", "Hello,"), "de": ("Hallo %s,", "Guten Tag,"), "it": ("Buongiorno %s,", "Buongiorno,"),
         "fr": ("Bonjour %s,", "Bonjour,"), "es": ("Hola %s,", "Buenos días,")}
TEAM = {"de": "Luftfracht Export"}


def reply_lang(fields):
    """The language we answer in: the customer's, when we have our own texts for it, else English."""
    l = (fields.get("language") or "").lower()[:2]
    return l if l in HUMAN else "en"


def _route(fields, lang):
    o, d = (fields.get("origin") or "").upper(), (fields.get("destination") or "").upper()
    names = dict(CITY, **CITY_DE) if lang == "de" else CITY
    if not (o and d):
        return "your shipment" if lang == "en" else "Ihre Sendung" if lang == "de" else NO_ROUTE[lang]
    return ROUTE_FMT[lang] % (names.get(o, o), names.get(d, d))


def _weight(fields, lang):
    w = fields.get("weight_kg_total") or fields.get("weight_kg")
    if not w:
        return NO_WEIGHT[lang]
    txt = ("{:,.0f}".format(float(w)) if float(w) == int(float(w)) else "{:,.1f}".format(float(w)))
    return (txt.replace(",", "X").replace(".", ",").replace("X", ".") + " kg") if lang != "en" else (txt + " kg")


SIGN_OFF = {"en": ["Best regards", "Kind regards", "Best wishes"], "de": ["Viele Grüße", "Beste Grüße", "Freundliche Grüße"],
            "it": ["Cordiali saluti", "Un cordiale saluto"], "fr": ["Cordialement", "Bien cordialement"],
            "es": ["Saludos cordiales", "Un cordial saludo"]}
_CLOSING = re.compile(r"^\s*(best|kind|warm)?\s*(regards|wishes)|^\s*(many\s+)?thanks|^\s*cheers|^\s*sincerely|^\s*yours|"
                      r"^\s*(viele|beste|freundliche|herzliche|liebe)\s+grüße|^\s*mit\s+freundlichen|^\s*\{SIGNER\}|"
                      r"^\s*best\s*,?\s*$|^\s*(cordiali|distinti)\s+saluti|^\s*(bien\s+)?cordialement|^\s*saludos|^\s*atentamente|"
                      r"^\s*(lg|vg|mfg|gruß|gruss|grüße|gruesse)\b", re.I)


def _own_signature(body, lang, thread_id):
    """Cut whatever sign-off the model wrote (it once signed with the CUSTOMER's name) and add ours."""
    lines = body.rstrip().split("\n")
    for i in range(len(lines) - 1, max(len(lines) - 6, 0) - 1, -1):
        if _CLOSING.search(lines[i]):
            lines = lines[:i]
            break
    sign = SIGN_OFF[lang][zlib.crc32(str(thread_id).encode()) % len(SIGN_OFF[lang])]
    team = TEAM.get(lang, "Air Export")
    return "\n".join(lines).rstrip() + "\n\n%s\n%s\n%s" % (sign, SIGNER, team)


def _fill(template, best, fields, customer, thread_id, lang):
    if not template or "{PRICE}" not in template:
        variants = HUMAN[lang]
        template = variants[zlib.crc32(str(thread_id).encode()) % len(variants)]
    from booking.replies import first_name
    name = first_name(customer)
    hello = HELLO[lang][0] % name if name else HELLO[lang][1]
    vals = {"PRICE": "%s %s" % (best["total"], best["currency"]), "AIRLINE": best["airline"],
            "TRANSIT_DAYS": str(best["transit_days"]), "ROUTE": _route(fields, lang), "WEIGHT": _weight(fields, lang),
            "SIGNER": SIGNER, "HELLO": hello}
    body = re.sub(r"\{(PRICE|AIRLINE|TRANSIT_DAYS|ROUTE|WEIGHT|SIGNER|HELLO)\}", lambda m: vals[m.group(1)], template)
    if re.search(r"\{[A-Z_]+\}", body):                      # unknown placeholder from the model: use our own text
        return _fill("", best, fields, customer, thread_id, lang)
    body = _add_expert_note(body, expert_note(best, fields, lang), vals["PRICE"])
    return _own_signature(body, lang, thread_id)


def _kg(x, lang):
    txt = "{:,.0f}".format(float(x))
    return txt.replace(",", ".") if lang == "de" else txt


def expert_note(best, fields, lang):
    """One TRUE detail only a forwarder would add, computed by code from our own pricing (never by the model).
    Weight break used -> say which weight we billed and why; volume decides -> say the chargeable weight."""
    try:
        actual = float(fields.get("weight_kg_total") or fields.get("weight_kg") or 0)
        volume = float(fields.get("volume_cbm_total") or fields.get("volume_cbm") or 0)
        billed = float(best.get("billed_kg") or 0)
    except (TypeError, ValueError):
        return ""
    if actual <= 0:
        return ""
    chargeable = max(actual, volume * 167)
    if billed > chargeable + 0.5:
        if lang == "de":
            return ("Ich habe mit %s kg statt %s kg gerechnet, weil die nächste Gewichtsstufe pro Kilo günstiger ist "
                    "und es für Sie so insgesamt billiger wird." % (_kg(billed, lang), _kg(chargeable, lang)))
        return ("I've billed it at %s kg rather than %s kg, since the next weight bracket is cheaper per kilo "
                "and that brings your total down." % (_kg(billed, lang), _kg(chargeable, lang)))
    if volume * 167 > actual * 1.15:
        if lang == "de":
            return "Wegen des Volumens (%s cbm) zählt hier das Volumengewicht von %s kg." % (
                ("%.2f" % volume).replace(".", ","), _kg(chargeable, lang))
        return "Because of the volume (%.2f cbm), the chargeable weight here is %s kg." % (volume, _kg(chargeable, lang))
    return ""


def _add_expert_note(body, note, price_text):
    """Append the note to the paragraph that states the price (else before the last paragraph)."""
    if not note:
        return body
    paras = body.split("\n\n")
    idx = next((i for i, p in enumerate(paras) if price_text in p), max(len(paras) - 2, 0))
    paras[idx] = paras[idx].rstrip() + " " + note
    return "\n\n".join(paras)


def final_reply(template, best, fields, customer="", thread_id=0):
    """-> (body, reasons). The filled reply after the quality gate (llm/quality.py).
    reasons == [] : the text went out as written. Otherwise the model's text failed for these reasons and the body
    is one of our own human templates instead (same price). No gateway call."""
    lang = reply_lang(fields)
    names = [n for n in re.split(r"[._\-+]", (customer or "").split("@")[0]) if len(n) > 3]
    body = _fill(template, best, fields, customer, thread_id, lang)
    reasons = quality.check(body, lang, best, fields, customer, SIGNER, names)
    if reasons:
        body = _fill("", best, fields, customer, thread_id, lang)
    return body, reasons


def fill_reply(template, best, fields, customer="", thread_id=0):
    """Fill our placeholders. No usable model reply (or one that fails the quality gate) -> a human fallback."""
    return final_reply(template, best, fields, customer, thread_id)[0]


def safe_reply(text, lang="en", multi=False):
    """Return the model's reply if it only uses our placeholders and promises nothing; else a fixed template."""
    t = text or ""
    if t and not _UNSAFE.search(_PLACEHOLDER.sub("", t)):
        return t, True
    if multi:
        return "", False                                    # pricing/multi.py uses its own fallback
    return HUMAN[reply_lang({"language": lang})][0], False   # human fallback, same price


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


def _text(mail):
    return "%s\n%s" % (mail.get("subject") or "", mail.get("body") or "")


def _annotate(fields, mail, detected):
    """What the reply gate needs later: the customer's language (code wins when it is sure), numbers and sign-off."""
    if detected:
        if (fields.get("language") or "").lower()[:2] != detected:
            fields["language_model"] = fields.get("language")     # kept for the log: what the model had said
        fields["language"] = detected
    fields["language_detected"] = detected
    fields["customer_numbers"] = quality.numbers(_text(mail))[:80]
    fields["customer_lines"] = quality.customer_lines(mail.get("body") or "")
    return fields


def _clip(body, head=3000, tail=3000):
    """Same token budget as before, but the end of a long mail (where the request often is) is kept too."""
    body = body or ""
    return body if len(body) <= head + tail else body[:head] + "\n[...]\n" + body[-tail:]


# A transient gateway failure must not lose the round (about 60 points): retry 429, 5xx and network errors.
# GATEWAY_RETRY_BUDGET_S is the wall clock for ALL attempts of one mail (time score: full under 120 s, zero at 360 s).
GATEWAY_RETRY_BUDGET_S = float(os.environ.get("GATEWAY_RETRY_BUDGET_S", "90"))
GATEWAY_MAX_ATTEMPTS = int(os.environ.get("GATEWAY_MAX_ATTEMPTS", "6"))
GATEWAY_TIMEOUT_S = 45                                   # one attempt; shorter when less budget is left
_BACKOFF_S = (1, 2, 4, 8)                                # pause after the 1st, 2nd, ... failure without a Retry-After
# urlopen timeout / refused / reset / DNS (OSError), a broken response (HTTPException), an undecodable body (ValueError)
_TRANSIENT = (OSError, http.client.HTTPException, ValueError)
_clock, _sleep = time.monotonic, time.sleep              # tests swap these for a fake clock


def _log(kind, thread_id=None, **data):
    try:
        from core import db
        db.event(kind, thread_id, **data)
    except Exception:
        pass


def _budget(mail):
    """Deadline for all gateway attempts of this mail: the retry budget, but never past the RFQ's own expiry."""
    budget = GATEWAY_RETRY_BUDGET_S
    if mail.get("received_at"):
        budget = min(budget, mail["received_at"] + config.RFQ_MAX_AGE_S - time.time())
    return _clock() + max(budget, 0)


def _gateway(body, deadline, thread_id=None):
    """POST to the gateway, status 200 -> the response. Retries 429 (waits its Retry-After), 408, 5xx and
    timeouts/connection errors (backoff 1, 2, 4, 8 s) until `deadline` or GATEWAY_MAX_ATTEMPTS. Any other
    4xx raises at once: the request itself is wrong. The first attempt is always made; a success is never repeated."""
    attempt = 0
    while True:
        attempt += 1
        left = deadline - _clock()
        try:
            status, data = mailbox.api("POST", "/v1/gateway/chat/completions",
                                       timeout=min(GATEWAY_TIMEOUT_S, max(left, 10)), body=body)
        except _TRANSIENT as e:
            status, data = None, "%s: %s" % (type(e).__name__, e)
        if status == 200:
            return data
        err = "gateway %s: %s" % (status if status is not None else "unreachable", str(data)[:300])
        if status is not None and status not in (408, 429) and status < 500:
            raise RuntimeError(err)
        if status == 429 and isinstance(data, dict) and data.get("retry_after") is not None:
            wait = max(float(data["retry_after"]), 0.5)      # the server said when: earlier is another 429
        else:
            wait = _BACKOFF_S[min(attempt, len(_BACKOFF_S)) - 1]
        left = deadline - _clock()
        if attempt >= GATEWAY_MAX_ATTEMPTS or wait >= left:
            raise RuntimeError("%s (gave up after %d attempt(s), %.0f s of budget left, next wait %.1f s)"
                               % (err, attempt, max(left, 0), wait))
        _log("gateway_retry", thread_id, attempt=attempt, status=status, wait_s=wait, error=str(data)[:200])
        _sleep(wait)


def _call_and_parse(messages, max_tokens, deadline=None, thread_id=None):
    """One gateway call (repeated only when it FAILED, see _gateway). Returns (fields or None, raw response).
    None means the JSON could not be parsed (for example truncated because max_tokens was too small for a long reply)."""
    data = _gateway({
        "model": config.LLM_MODEL, "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"},
        "messages": messages,
    }, _clock() + GATEWAY_RETRY_BUDGET_S if deadline is None else deadline, thread_id)
    try:
        return json.loads(data["choices"][0]["message"]["content"]), data
    except (KeyError, IndexError, TypeError, ValueError):
        return None, data


def _merge_usage(first, second):
    """Add the two calls' token usage so the cost we log is the real total."""
    u1, u2 = (first.get("usage") or {}), (second.get("usage") or {})
    merged = dict(second)
    merged["usage"] = {k: (u1.get(k) or 0) + (u2.get(k) or 0) for k in set(u1) | set(u2)}
    return merged


def extract(mail):
    """Returns (fields dict, usage dict). Exactly one gateway call when it works; a failed call (429, 5xx, timeout)
    is retried inside one shared time budget, and only raises (-> needs_human) when that is used up."""
    detected = langmod.detect(_text(mail))                  # counted in code, no call
    if config.LLM_FAKE:
        return _annotate(_fake(mail), mail, detected), {"fake": True}
    hint = langmod.hint(detected)
    user = "Subject: %s\n\n%s" % (mail["subject"], _clip(mail["body"]))
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user + ("\n\n[%s]" % hint if hint else "")}]
    deadline, tid = _budget(mail), mail.get("thread_id")
    fields, data = _call_and_parse(messages, config.LLM_MAX_TOKENS, deadline, tid)
    if fields is None:                                   # truncated/invalid JSON: retry once with more room (rare; logged)
        fields, data2 = _call_and_parse(messages, config.LLM_MAX_TOKENS * 2, deadline, tid)
        if fields is None:
            raise RuntimeError("gateway returned unparsable JSON twice: %s" % str(data2)[:300])
        data = _merge_usage(data, data2)
    _fill_places(fields, mail)
    _annotate(fields, mail, detected)
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
