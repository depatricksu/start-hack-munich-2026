"""The ONE gateway call per RFQ: read the customer's mail and write the reply text.

The model never does math and never invents a price. It returns:
  - the shipment fields as JSON (code computes weight, volume and price from them)
  - a reply text with placeholders {PRICE} {AIRLINE} {TRANSIT_DAYS}, which code fills in later
"""
import http.client, json, os, re, time, zlib
from core import config, mailbox
from . import lang as langmod, quality, human

SIGNER = os.environ.get("SIGNER", "Lena Hofmann")   # the person who signs our mails (jury: most human email)

SYSTEM_HEAD = """You work at an air freight forwarder in Germany. Read the customer's email and answer with JSON only:
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
 "customer_city": the city the customer is based in (from their signature, company address or pickup address), in English, or null,
 "language": ISO 639-1 code of the language the customer wrote in ("en", "de", ...),
 "missing": list of fields you could not find,
 "reply": the reply email body
}
Do not calculate anything. Copy numbers as written (convert units to cm and kg only).
Several "lots" or pieces that the customer wants ONE combined all-in price for, as a single consignment, are ONE shipment: add their weights and volumes into weight_kg/volume_cbm (or list them in pieces), multi_shipment stays false. multi_shipment is only true when the customer wants separate quotes for different origin/destination routes.
"""

# The voice of the reply. V1 is the text that ran until 21 Nov 18:00 (clean, but every mail had the same shape and the
# jury never picked it). V2 answers the person, not only the data. HUMAN_VOICE=0 goes back to V1.
VOICE_V1 = """The reply: write it in the language of the customer's email, never any other (an English email gets an English reply, a German email a German reply). Greet with the sender's FIRST name only (from how they signed, e.g. "Hi Anna", "Hallo Katrin"); never add Frau, Herr, Mr or Ms. If they signed only with a company name, a role, initials, or gave no name, greet warmly WITHOUT a name ("Hi there" / "Hello" / "Guten Tag") - NEVER greet with the company name (never "Hi Auer" for "Auer Maschinenbau").
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
Write the one email a busy human forwarder would actually send - warm, specific, effortless. Open by engaging with THEIR situation (their cargo, their route, their timeline or ready date, the tone they used), not a stock opener. If they were friendly, be friendly back; if they gave a lot of detail, show you read it. One light, genuine human touch is good (e.g. "happy to help get these moving", "good timing, space is open on this lane") - but only if it is true and natural, never filler. The goal: a neutral reader comparing many quotes should feel a real person wrote ours. Still: no gush, no exclamation stacks, one all-in price, and nothing we cannot know.
Never use: "I hope this email finds you well", "Thank you for reaching out", "Certainly", "delighted", "Please do not hesitate", "valued customer", exclamation marks in a row, emojis.
State one all-in price using exactly the placeholder {PRICE}. Mention {AIRLINE} and {TRANSIT_DAYS} days transit.
End with one easy next step: they can simply reply to book it.
If there are several shipments, do NOT use {PRICE}, {AIRLINE} or {TRANSIT_DAYS}: put {PRICE_TABLE} on its own line where the per-shipment prices go and state the all-in total with {TOTAL}.
Never write a number for the price yourself. Do NOT write any closing or signature (no "Best regards", no name): our system adds it. Never use the customer's name or signature as ours.
Only state facts that are in the customer's email or behind our placeholders. Never mention deadlines, cut-off or drop-off times, customs, insurance, packaging, documents or dates of your own, and write no number the customer did not write."""

VOICE = """The reply: write it in the language of the customer's email, never any other (an English email gets an English reply, a German email a German reply). Greet with the sender's FIRST name only (from how they signed, e.g. "Hi Anna", "Hallo Katrin"); never add Frau, Herr, Mr or Ms. If they signed only with a company name, a role, initials, or gave no name, greet warmly WITHOUT a name ("Hi there" / "Hello" / "Guten Tag") - NEVER greet with the company name (never "Hi Auer" for "Auer Maschinenbau").
You are an experienced, friendly forwarder typing ONE answer to THIS person between two calls. A jury compares many quotes for the same request and picks the one a real person clearly wrote; a form letter loses. Plain words, no lists, no headings.
- Show you read it, but do not read their data back to them. Name the goods in their words and pick up ONE or TWO things they told you: the ready date the way people say it ("the 28th", "am 2. Dezember", never "2026-11-28"), that they bring the goods to the airport themselves (only if they say so), one air waybill for all lots. If they ask for pickup at their site, WE send the truck: say our truck collects there and it is in the price, never that they arrange it. Never list weight, volume and piece count in a row. If they ask something the price does not answer (a departure date, for example), say in one clause that you will check and come back on it.
- Their small talk ("hope your week is going well", "have a lovely day", greetings from their town) is answered by our system in its own line: do not answer it yourself and do not wish them anything.
- Sound like speech. Do not open with "For your shipment of ..." and do not squeeze everything into one long sentence: two or three short sentences of different shape. Never start with a thank-you formula; start with their shipment or with the answer.
- Mirror the customer: if they wrote one or two lines, answer in two or three sentences; if they wrote a long mail, at most five. Stay under 75 words. If they wrote casually ("Hi", "Hey", first name, no greeting), be casual and use contractions; if formal ("Dear Sir or Madam", "Sehr geehrte"), stay formal but warm.
- Write as a native of their language would. English, French, Spanish: the first word after the greeting line has a capital. German: always "Sie", lower case after the greeting line, everyday business German ("Laufzeit", "Abholung", "all-in"). Italian: "voi" for the company, "tutto incluso", "giorni di transito". French: "vous", "tout compris", "jours de transit". Spanish: "usted", "todo incluido", "días de tránsito".
Three examples of the voice (placeholders as in your reply; never copy the wording, every mail gets its own):
  Customer: "Hi, price for 300 kg MUC to JFK please, cheapest. Tom"
  Reply: "Hi Tom,\n\n{AIRLINE} is the cheapest on {ROUTE} right now: {PRICE} all-in for your {WEIGHT}, about {TRANSIT_DAYS} days.\n\nShall I book it?"
  Customer: "Hey, we've got 4 crates of pump spares, 410 kg, ready on 2026-12-03, and we'd drive them to HAM ourselves. What's the fastest way to Chicago? Thanks a million, Jonas"
  Reply: "Hi Jonas,\n\nYour four crates of pump spares can fly {ROUTE} with {AIRLINE}, the fastest I can get: around {TRANSIT_DAYS} days, {PRICE} all-in. I've noted the 3rd as the ready date and that you bring them to the airport yourselves.\n\nA quick yes from you and I'll book it."
  Customer: "Sehr geehrte Damen und Herren, wir benötigen ein Angebot für 2 Paletten Maschinenteile, 640 kg, Abholung 70565, nach Shanghai, möglichst schnell."
  Reply: "Guten Tag,\n\nIhre zwei Paletten Maschinenteile ({WEIGHT}) bekommen wir am schnellsten mit {AIRLINE} nach Shanghai: {PRICE} all-in, die Abholung bei Ihnen ist enthalten, Laufzeit rund {TRANSIT_DAYS} Tage.\n\nWenn das für Sie passt, genügt eine kurze Antwort und ich buche."
State one all-in price using exactly the placeholder {PRICE}, and name {AIRLINE} and {TRANSIT_DAYS} days transit: all three placeholders must be in the reply. {ROUTE} (filled as "Munich to New York") and {WEIGHT} (filled as "300 kg", the unit is included, never write "kg" after it) are optional.
End with one easy next step: they can simply reply to book it. A line in square brackets under the customer's mail gives the shape for THIS reply; follow it in your own words.
If there are several shipments, do NOT use {PRICE}, {AIRLINE} or {TRANSIT_DAYS}: put {PRICE_TABLE} on its own line where the per-shipment prices go and state the all-in total with {TOTAL}.
Never write a number for the price yourself. Do NOT write any closing or signature (no "Best regards", no name): our system adds it. Never use the customer's name or signature as ours.
Never use: "I hope this email finds you well", "Thank you for reaching out", "Certainly", "delighted", "Please do not hesitate", "valued customer", exclamation marks in a row, emojis.
Only state facts that are in the customer's email or behind our placeholders. Never mention deadlines, cut-off or drop-off times, customs, insurance, packaging, documents or dates of your own, never promise space, a direct flight or a departure, and write no number the customer did not write."""

HUMAN_VOICE = os.environ.get("HUMAN_VOICE", "1") != "0"     # 0 = the reply prompt and shape as before 21 Nov 18:00
SYSTEM_V1 = SYSTEM_HEAD + VOICE_V1
SYSTEM = SYSTEM_HEAD + VOICE


def system_prompt():
    return SYSTEM if HUMAN_VOICE else SYSTEM_V1


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

CITY_LOCAL = {
    "de": CITY_DE,
    "it": {"FRA": "Francoforte", "MUC": "Monaco di Baviera", "HAM": "Amburgo", "STR": "Stoccarda", "CGN": "Colonia",
           "PEK": "Pechino", "MEX": "Città del Messico", "ICN": "Seul", "GRU": "San Paolo", "RUH": "Riad"},
    "fr": {"FRA": "Francfort", "HAM": "Hambourg", "PEK": "Pékin", "MEX": "Mexico", "SIN": "Singapour", "ICN": "Séoul",
           "DXB": "Dubaï", "RUH": "Riyad"},
    "es": {"FRA": "Fráncfort", "MUC": "Múnich", "HAM": "Hamburgo", "CGN": "Colonia", "PEK": "Pekín", "JFK": "Nueva York",
           "MEX": "Ciudad de México", "SIN": "Singapur", "ICN": "Seúl", "NRT": "Tokio", "DXB": "Dubái",
           "JNB": "Johannesburgo", "RUH": "Riad", "DEL": "Nueva Delhi"},
}

# Our own mails, used when the model's text fails the gate. One opening + one closing, picked separately per thread,
# so two requests rarely read the same. Written the way a native writes: German starts lower case after the greeting,
# English, French and Spanish with a capital; {ROUTE} always follows a word it fits behind ("von A nach B").
OPENING = {
    "en": ["I've had a look at {ROUTE} for your {WEIGHT}. {AIRLINE} is the best fit right now: {PRICE} all-in, "
           "about {TRANSIT_DAYS} days in transit.",
           "Good news on {ROUTE}: your {WEIGHT} can go with {AIRLINE} for {PRICE} all-in, roughly {TRANSIT_DAYS} days in transit.",
           "Quick answer on {ROUTE}: {PRICE} all-in for your {WEIGHT} with {AIRLINE}, around {TRANSIT_DAYS} days in transit.",
           "I've compared the options on {ROUTE}. For your {WEIGHT} I'd go with {AIRLINE}: {PRICE} all-in and "
           "about {TRANSIT_DAYS} days in transit."],
    "de": ["für Ihre {WEIGHT} {ROUTE} passt aktuell {AIRLINE} am besten: {PRICE} all-in, Laufzeit rund {TRANSIT_DAYS} Tage.",
           "ich habe die Raten {ROUTE} verglichen: {AIRLINE} liegt für Ihre {WEIGHT} bei {PRICE} all-in, "
           "mit etwa {TRANSIT_DAYS} Tagen Laufzeit.",
           "kurze Rückmeldung zu Ihrer Anfrage {ROUTE}: {AIRLINE} fliegt Ihre {WEIGHT} für {PRICE} all-in, "
           "die Laufzeit liegt bei rund {TRANSIT_DAYS} Tagen."],
    "it": ["ho verificato la tratta {ROUTE} per i vostri {WEIGHT}: al momento la soluzione migliore è {AIRLINE}, "
           "{PRICE} tutto incluso, con circa {TRANSIT_DAYS} giorni di transito.",
           "per i vostri {WEIGHT} {ROUTE} posso proporvi {AIRLINE} a {PRICE} tutto incluso, "
           "con un transito di circa {TRANSIT_DAYS} giorni."],
    "fr": ["J'ai regardé le trajet {ROUTE} pour vos {WEIGHT} : la meilleure option en ce moment est {AIRLINE}, "
           "à {PRICE} tout compris, avec environ {TRANSIT_DAYS} jours de transit.",
           "Pour vos {WEIGHT} {ROUTE}, je peux vous proposer {AIRLINE} à {PRICE} tout compris, "
           "soit environ {TRANSIT_DAYS} jours de transit."],
    "es": ["He revisado la ruta {ROUTE} para sus {WEIGHT}: la mejor opción ahora mismo es {AIRLINE}, por {PRICE} "
           "todo incluido, con unos {TRANSIT_DAYS} días de tránsito.",
           "Para sus {WEIGHT} {ROUTE} le puedo ofrecer {AIRLINE} por {PRICE} todo incluido; el tránsito es de "
           "unos {TRANSIT_DAYS} días."],
}
CLOSING = {
    "en": ["If that works for you, just reply and I'll book it.", "Shall I go ahead? A short yes is enough.",
           "Give me a quick yes and I'll get it booked.", "Happy to book it as soon as you give me the go-ahead."],
    "de": ["Wenn das für Sie passt, genügt eine kurze Antwort und ich buche.", "Soll ich das so buchen? Ein kurzes Ja reicht.",
           "Geben Sie mir einfach kurz Bescheid, dann buche ich direkt."],
    "it": ["Se per voi va bene, basta una riga di conferma e procedo con la prenotazione.",
           "Procedo con la prenotazione? Mi basta un vostro ok.",
           "Fatemi sapere e prenoto subito."],
    "fr": ["Si cela vous convient, un simple retour de mail suffit et je lance la réservation.",
           "Souhaitez-vous que je réserve ? Un simple oui par retour de mail suffit.",
           "Dites-moi si cela vous convient et je réserve tout de suite."],
    "es": ["Si le encaja, basta con que me responda a este correo y lo reservo.",
           "¿Lo reservo? Con un sí por respuesta es suficiente.",
           "Dígame si le parece bien y lo reservo enseguida."],
}
HUMAN = {l: ["{HELLO}\n\n%s\n\n%s" % (o, c) for o in OPENING[l] for c in CLOSING[l]] for l in OPENING}


def own_template(lang, thread_id):
    """Opening and closing picked by two different hashes of the thread: same thread, same mail; next thread, another one."""
    o = human.mix("open", thread_id) % len(OPENING[lang])
    c = human.mix("close", thread_id) % len(CLOSING[lang])
    return HUMAN[lang][o * len(CLOSING[lang]) + c]


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
    names = dict(CITY, **CITY_LOCAL.get(lang, {}))
    if not (o and d):
        return "your shipment" if lang == "en" else "Ihre Sendung" if lang == "de" else NO_ROUTE[lang]
    return ROUTE_FMT[lang] % (names.get(o, o), names.get(d, d))


def _weight(fields, lang):
    w = fields.get("weight_kg_total") or fields.get("weight_kg")
    if not w:
        return NO_WEIGHT[lang]
    txt = ("{:,.0f}".format(float(w)) if float(w) == int(float(w)) else "{:,.1f}".format(float(w)))
    if lang == "fr":                                         # "1 805 kg" would read as two numbers: no separator
        return txt.replace(",", "").replace(".", ",") + " kg"
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
        rest = [l for l in lines[i + 1:] if l.strip()]
        # a sign-off is short and only a name or a team follows it. "Thanks, all good here ..." at the top or a
        # "Viele Grüße zurück nach Kiel." in the text is not one.
        if (_CLOSING.search(lines[i]) and len(lines[i].split()) <= 4 and len(rest) <= 2
                and all(len(l.split()) <= 4 for l in rest)
                and not re.search(r"\b(back|zurück|too|auch|ebenfalls)\b", lines[i], re.I)):
            lines = lines[:i]
            break
    sign = SIGN_OFF[lang][zlib.crc32(str(thread_id).encode()) % len(SIGN_OFF[lang])]
    team = TEAM.get(lang, "Air Export")
    return "\n".join(lines).rstrip() + "\n\n%s\n%s\n%s" % (sign, SIGNER, team)


def _fill(template, best, fields, customer, thread_id, lang):
    if not template or "{PRICE}" not in template:
        template = own_template(lang, thread_id)
    from booking.replies import first_name
    name = fields.get("customer_first_name") or first_name(customer)     # the name they signed with, never the company
    hello = HELLO[lang][0] % name if name else HELLO[lang][1]
    vals = {"PRICE": "%s %s" % (best["total"], best["currency"]), "AIRLINE": best["airline"],
            "TRANSIT_DAYS": str(best["transit_days"]), "ROUTE": _route(fields, lang), "WEIGHT": _weight(fields, lang),
            "SIGNER": SIGNER, "HELLO": hello}
    body = re.sub(r"\{(PRICE|AIRLINE|TRANSIT_DAYS|ROUTE|WEIGHT|SIGNER|HELLO)\}", lambda m: vals[m.group(1)], template)
    if re.search(r"\{[A-Z_]+\}", body):                      # unknown placeholder from the model: use our own text
        return _fill("", best, fields, customer, thread_id, lang)
    body = human.polish(body, lang, hello, fields.get("customer_first_name"))
    body = _add_expert_note(body, expert_note(best, fields, lang), vals["PRICE"])
    return _own_signature(body, lang, thread_id)


def _kg(x, lang):
    txt = "{:,.0f}".format(float(x))
    return txt if lang == "en" else txt.replace(",", "") if lang == "fr" else txt.replace(",", ".")


# The expert note in the customer's language (an English sentence in an Italian mail is a robot tell).
# Per language: (the next weight break was used: billed kg, chargeable kg; volume decides: cbm, chargeable kg)
NOTE = {
    "en": ("I've billed it at %s kg rather than %s kg, since the next weight bracket is cheaper per kilo "
           "and that brings your total down.",
           "Because of the volume (%s cbm), the chargeable weight here is %s kg."),
    "de": ("Ich habe mit %s kg statt %s kg gerechnet, weil die nächste Gewichtsstufe pro Kilo günstiger ist "
           "und es für Sie so insgesamt billiger wird.",
           "Wegen des Volumens (%s cbm) zählt hier das Volumengewicht von %s kg."),
    "it": ("Ho calcolato su %s kg anziché %s kg: lo scaglione di peso superiore costa meno al chilo "
           "e così il vostro totale si abbassa.",
           "Dato il volume (%s cbm), qui conta il peso tassabile di %s kg."),
    "fr": ("J'ai calculé sur %s kg au lieu de %s kg : la tranche de poids supérieure est moins chère au kilo, "
           "ce qui fait baisser votre total.",
           "Vu le volume (%s cbm), c'est le poids taxable de %s kg qui s'applique."),
    "es": ("Lo he calculado con %s kg en lugar de %s kg: el siguiente tramo de peso sale más barato por kilo "
           "y así baja su total.",
           "Por el volumen (%s cbm), aquí se aplica el peso tasable de %s kg."),
}


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
    breaks, bulky = NOTE.get(lang, NOTE["en"])
    if billed > chargeable + 0.5:
        return breaks % (_kg(billed, lang), _kg(chargeable, lang))
    if volume * 167 > actual * 1.15:
        return bulky % (("%.2f" % volume) if lang == "en" else ("%.2f" % volume).replace(".", ","), _kg(chargeable, lang))
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
    if (fields.get("language") or "en").lower()[:2] != lang:  # a language we have no texts for (Polish...): one
        template = ""                                        # clean English mail, never their text + our English lines
    if fields.get("reply_ok") is False:                      # safe_reply already replaced the model's text: let the
        template = ""                                        # thread pick one of our own mails, not always the first
    names = [n for n in re.split(r"[._\-+]", (customer or "").split("@")[0]) if len(n) > 3]
    plain = _fill(template, best, fields, customer, thread_id, lang)
    reasons = quality.check(plain, lang, best, fields, customer, SIGNER, names)
    if reasons:
        plain = _fill("", best, fields, customer, thread_id, lang)
    try:                                                     # personal touch (llm/human.py): any error -> plain mail
        style = human.choose(fields, lang, thread_id)
        if HUMAN_VOICE and fields.get("personal_cues") and human.HUMAN_STYLE not in human.STYLES:
            # they wrote something personal: answering THAT is the touch, and no second line on top of it
            body, style = human.mirror(plain, fields["personal_cues"], lang, thread_id), "mirror"
        else:                                                # (apply only here: it uses up a line in human.fresh)
            body = human.apply(plain, style, fields, lang, thread_id=thread_id)
        if body != plain and quality.check(body, lang, best, fields, customer, SIGNER, names):
            body, style = plain, "control"                   # the touch must never cost us a clean mail
        fields["human_style"] = style
        _log("human_style", thread_id, style=style, city=human.customer_city(fields))
        try:
            human.record(thread_id, style)
        except Exception as e:                               # learning is optional, the mail is not
            _log("human_learn_error", thread_id, error=str(e)[:200])
    except Exception as e:
        body = plain
        _log("human_touch_error", thread_id, error=str(e)[:200])
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
    l = reply_lang({"language": lang})                       # one of our own mails, same price
    return HUMAN[l][0] + "\n\n%s\n{SIGNER}\n%s" % (SIGN_OFF[l][0], TEAM.get(l, "Air Export")), False


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


_LB = re.compile(r"(\d[\d,.]*)\s*(?:lbs?|pounds?)\b", re.I)
_TONNES = re.compile(r"(\d[\d,.]*)\s*(?:t|tons?|tonnes?|tonnen)\b", re.I)
_MM = re.compile(r"(\d+(?:[.,]\d+)?)\s*[x\u00d7*]\s*(\d+(?:[.,]\d+)?)\s*[x\u00d7*]\s*(\d+(?:[.,]\d+)?)\s*mm\b", re.I)
_NET = re.compile(r"\bnet(?:to)?(?:\s*weight|gewicht)?\s*[:=]?\s*(\d[\d,.]*)\s*kgs?\b|(\d[\d,.]*)\s*kgs?\s*net(?:to)?\b", re.I)
_GROSS = re.compile(r"\b(?:gross|brutto)(?:\s*weight|gewicht)?\s*[:=]?\s*(\d[\d,.]*)\s*kgs?\b|(\d[\d,.]*)\s*kgs?\s*(?:gross|brutto)\b", re.I)
_EXW = re.compile(r"\b(?:EXW|ex[ -]works|ab werk)\b", re.I)
_INCHES = re.compile(r"(\d+(?:\.\d+)?)\s*[x\u00d7*]\s*(\d+(?:\.\d+)?)\s*[x\u00d7*]\s*(\d+(?:\.\d+)?)\s*"
                     r"(?:in\b|inch(?:es)?\b|\"|'')", re.I)


def _same(a, b):
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) <= 0.005 * max(float(b), 1)
    except (TypeError, ValueError):
        return False


def fix_units(fields, mail):
    """US shippers write pounds and inches. A small model copies '2,200 lbs' into weight_kg and '48 x 40 x 50 in'
    into l_cm/w_cm/h_cm (red-team run 21 Nov: priced 2,200 kg instead of 998 kg). Code converts every number the
    model copied unchanged from a lb / inch value. A number the model already converted matches nothing and stays."""
    from shared.rfq import _num
    text = "%s\n%s" % (mail.get("subject") or "", mail.get("body") or "")
    lbs = []
    for m in _LB.finditer(text):
        try:
            lbs.append(_num(m.group(1).rstrip(".,")))
        except ValueError:
            pass
    dims = [tuple(float(m.group(i)) for i in (1, 2, 3)) for m in _INCHES.finditer(text)]
    tonnes = []
    for m in _TONNES.finditer(text):
        try:
            n = _num(m.group(1).rstrip(".,"))
        except ValueError:
            continue
        if 0 < n < 200:                                  # "2.4 t"; a 5-digit number before "t" is no tonnage
            tonnes.append(n)
    mm = [tuple(float(m.group(i).replace(",", ".")) for i in (1, 2, 3)) for m in _MM.finditer(text)]
    nums = lambda rx: {_num(a or b) for a, b in (m.groups() for m in rx.finditer(text))}   # noqa: E731
    try:
        net, gross = nums(_NET), nums(_GROSS)
    except ValueError:
        net, gross = set(), set()
    if not (lbs or dims or tonnes or mm or (net and len(gross) == 1)):
        return []
    fixed = []
    for f in [fields] + list(fields.get("shipments") or []):
        if any(_same(f.get("weight_kg"), n) for n in lbs):
            fixed.append("weight_kg %s lb" % f["weight_kg"])
            f["weight_kg"] = round(float(f["weight_kg"]) * 0.45359237, 1)
        if any(_same(f.get("weight_kg"), n) for n in tonnes):
            fixed.append("weight_kg %s t" % f["weight_kg"])
            f["weight_kg"] = round(float(f["weight_kg"]) * 1000, 1)
        if f is fields and len(gross) == 1 and any(_same(f.get("weight_kg"), n) for n in net):
            g = next(iter(gross))                        # "net 640 kg, gross 712 kg": air freight bills the gross
            if not _same(g, f["weight_kg"]):
                fixed.append("weight_kg net %s -> gross %s" % (f["weight_kg"], g))
                f["weight_kg"] = g
        for p in f.get("pieces") or []:
            got = (p.get("l_cm"), p.get("w_cm"), p.get("h_cm"))
            if all(got) and any(all(_same(g, d) for g, d in zip(got, dim)) for dim in mm):
                fixed.append("dims %sx%sx%s mm" % got)
                p["l_cm"], p["w_cm"], p["h_cm"] = (round(float(x) / 10, 1) for x in got)
            if any(_same(p.get("kg_each"), n) for n in lbs):
                fixed.append("kg_each %s lb" % p["kg_each"])
                p["kg_each"] = round(float(p["kg_each"]) * 0.45359237, 1)
            got = (p.get("l_cm"), p.get("w_cm"), p.get("h_cm"))
            if all(got) and any(all(_same(g, d) for g, d in zip(got, dim)) for dim in dims):
                fixed.append("dims %sx%sx%s in" % got)
                p["l_cm"], p["w_cm"], p["h_cm"] = (round(float(x) * 2.54, 1) for x in got)
    if fixed:
        fields.setdefault("filled_by_code", []).append("units")
        fields["unit_fix"] = fixed
    return fixed


def fix_incoterm(fields, mail):
    """'Incoterm EXW, our factory 70565 Stuttgart': ex works means WE collect at their door, even when the mail never
    says pickup or truck. The model then leaves pickup_postcode empty and we quote airport to airport without the truck
    leg (red-team round 2). Code takes the first German postcode of a known pickup zone from the mail."""
    if fields.get("pickup_postcode") or len(fields.get("shipments") or []) > 1:
        return None
    text = "%s\n%s" % (mail.get("subject") or "", mail.get("body") or "")
    if not _EXW.search(text):
        return None
    from shared.rfq import PICKUP_ZONES
    for m in re.finditer(r"(?<![\d+/-])(?:D-)?(\d{5})\b(?![\d/-])", text):
        if m.group(1)[:2] in PICKUP_ZONES:
            fields["pickup_postcode"] = m.group(1)
            fields.setdefault("filled_by_code", []).append("pickup_postcode")
            return m.group(1)
    return None


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
    fields["customer_dates"] = quality.date_forms(_text(mail))
    fields["self_delivery"] = quality.self_delivery(human.own_text(mail.get("body") or ""))
    fields["personal_cues"] = human.cues(mail.get("body") or "", reply_lang(fields))    # what they wrote as a person
    fields["customer_first_name"] = human.signed_name(mail.get("body") or "")           # humanize/'s reading, chain cut
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
    deadline, tid = _budget(mail), mail.get("thread_id")
    hint = " ".join(x for x in (langmod.hint(detected), human.style_card(tid) if HUMAN_VOICE else "") if x)
    user = "Subject: %s\n\n%s" % (mail["subject"], _clip(mail["body"]))
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": user + ("\n\n[%s]" % hint if hint else "")}]
    fields, data = _call_and_parse(messages, config.LLM_MAX_TOKENS, deadline, tid)
    if fields is None:                                   # truncated/invalid JSON: retry once with more room (rare; logged)
        fields, data2 = _call_and_parse(messages, config.LLM_MAX_TOKENS * 2, deadline, tid)
        if fields is None:
            raise RuntimeError("gateway returned unparsable JSON twice: %s" % str(data2)[:300])
        data = _merge_usage(data, data2)
    _fill_places(fields, mail)
    if fix_units(fields, mail):                          # lb / inch / t / mm / net copied raw: fixed in code
        _log("unit_fix", tid, fixed=fields["unit_fix"])
    if fix_incoterm(fields, mail):                       # EXW = door pickup, even without the word "pickup"
        _log("exw_pickup", tid, postcode=fields["pickup_postcode"])
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
