"""Reply mails for the booking flow: $0 LLM cost, but never the same text twice in a row.

Every mail = greeting + body + closing + sign-off. Each part has several variants per mail kind and language,
so one kind has dozens of combinations. The choice is seeded by the thread (the same thread always reads
consistently, e.g. a re-run gives the same text), and we skip the combination we used last time for that kind,
so two customers in a row never get identical mails. The customer's first name comes from the address
(anna.schmidt@... -> "Anna"); role addresses (info@, sales@, logistics@ ...) get a neutral greeting.

    render("booked", "de", values, thread_id=123, customer="anna.schmidt@x.mail")
values: ROUTE, AIRLINE, PRICE, REF, TRANSIT, SLOTS, FORWARDER
"""
import random, re
from core import db

ROLE = {"info", "sales", "logistics", "ops", "operations", "export", "import", "buyer", "procurement", "purchasing",
        "shipping", "office", "contact", "orders", "admin", "team", "cargo", "freight", "einkauf", "versand", "mail"}

GREET = {
    "en": {"name": ["Hi {NAME},", "Hello {NAME},", "Dear {NAME},", "Good day {NAME},"],
           "anon": ["Hello,", "Hi there,", "Good day,", "Dear customer,"]},
    "de": {"name": ["Hallo {NAME},", "Guten Tag {NAME},", "Liebe/r {NAME},", "Hallo {NAME}, danke für Ihre Nachricht."],
           "anon": ["Guten Tag,", "Hallo,", "Sehr geehrte Damen und Herren,"]},
}
GREET["de"]["name"][2] = "Guten Tag {NAME},"          # no gendered forms (team rule: never Frau/Herr)

SIGN = {
    "en": ["Best regards\nYour forwarding team", "Kind regards\nYour forwarding team", "Cheers\nYour forwarding team",
           "Many thanks and best wishes\nYour forwarding team"],
    "de": ["Viele Grüße\nIhr Forwarding-Team", "Beste Grüße\nIhr Forwarding-Team", "Freundliche Grüße\nIhr Forwarding-Team",
           "Herzliche Grüße\nIhr Forwarding-Team"],
}

BODY = {
    "booked": {
        "en": ["thank you for your order. Your shipment {ROUTE} is booked with {AIRLINE} at {PRICE} all-in, booking reference {REF}.",
               "great, it's done: {ROUTE} is booked with {AIRLINE} for {PRICE} all-in. Your reference is {REF}.",
               "thanks for the go-ahead. We have booked {ROUTE} on {AIRLINE} at the quoted {PRICE} all-in (ref. {REF}).",
               "your booking is in. {AIRLINE} will carry your shipment {ROUTE}, total {PRICE} all-in, reference {REF}."],
        "de": ["vielen Dank für Ihren Auftrag. Ihre Sendung {ROUTE} ist bei {AIRLINE} zum Gesamtpreis von {PRICE} gebucht, Buchungsnummer {REF}.",
               "erledigt: {ROUTE} ist bei {AIRLINE} für {PRICE} all-in gebucht. Ihre Referenz lautet {REF}.",
               "danke für die Freigabe. Wir haben {ROUTE} bei {AIRLINE} zum angebotenen Preis von {PRICE} gebucht (Ref. {REF}).",
               "Ihre Buchung steht. {AIRLINE} übernimmt Ihre Sendung {ROUTE}, Gesamtpreis {PRICE}, Referenz {REF}."]},
    "requested": {
        "en": ["thank you for your order. We have sent the booking for {ROUTE} to {AIRLINE} at {PRICE} all-in (our reference {REF}).",
               "thanks, we are on it: the booking request for {ROUTE} has gone to {AIRLINE}, {PRICE} all-in, reference {REF}.",
               "great, we have asked {AIRLINE} to book {ROUTE} at {PRICE} all-in. Our reference is {REF}."],
        "de": ["vielen Dank für Ihren Auftrag. Die Buchung {ROUTE} zum Gesamtpreis von {PRICE} ist bei {AIRLINE} angefragt (Referenz {REF}).",
               "danke, wir kümmern uns: Die Buchungsanfrage für {ROUTE} ist an {AIRLINE} raus, {PRICE} all-in, Referenz {REF}.",
               "prima, wir haben {AIRLINE} gebeten, {ROUTE} zu {PRICE} all-in zu buchen. Unsere Referenz: {REF}."]},
    "confirmed": {
        "en": ["good news: {AIRLINE} has confirmed your shipment {ROUTE}, booking {REF}. It is ready to ship, expected transit {TRANSIT} days.",
               "{AIRLINE} just confirmed booking {REF} for {ROUTE}. Everything is set, transit should be about {TRANSIT} days.",
               "your shipment {ROUTE} is confirmed by {AIRLINE} (booking {REF}) and ready to go. Expected transit: {TRANSIT} days."],
        "de": ["gute Nachrichten: {AIRLINE} hat Ihre Sendung {ROUTE} bestätigt, Buchung {REF}. Sie ist versandbereit, Laufzeit ca. {TRANSIT} Tage.",
               "{AIRLINE} hat die Buchung {REF} für {ROUTE} soeben bestätigt. Alles steht, die Laufzeit liegt bei etwa {TRANSIT} Tagen.",
               "Ihre Sendung {ROUTE} ist von {AIRLINE} bestätigt (Buchung {REF}) und startklar. Voraussichtliche Laufzeit: {TRANSIT} Tage."]},
    "cheaper_option": {
        "en": ["thanks for the feedback. We can offer {ALT_AIRLINE} for {ROUTE} at {ALT_PRICE} all-in instead of {PRICE}, transit about {ALT_TRANSIT} days.",
               "good news on price: with {ALT_AIRLINE} we can do {ROUTE} for {ALT_PRICE} all-in (transit about {ALT_TRANSIT} days), down from {PRICE}.",
               "we had another look. {ALT_AIRLINE} can take {ROUTE} for {ALT_PRICE} all-in, a bit slower at about {ALT_TRANSIT} days."],
        "de": ["danke für Ihr Feedback. Statt {PRICE} können wir {ROUTE} mit {ALT_AIRLINE} für {ALT_PRICE} all-in anbieten, Laufzeit ca. {ALT_TRANSIT} Tage.",
               "gute Nachrichten zum Preis: Mit {ALT_AIRLINE} geht {ROUTE} für {ALT_PRICE} all-in (Laufzeit ca. {ALT_TRANSIT} Tage), statt {PRICE}.",
               "wir haben noch einmal geschaut. {ALT_AIRLINE} übernimmt {ROUTE} für {ALT_PRICE} all-in, etwas langsamer mit ca. {ALT_TRANSIT} Tagen."]},
    "best_rate": {
        "en": ["thanks for the feedback. We compared all airlines on {ROUTE}, and {PRICE} all-in with {AIRLINE} is the best rate available right now.",
               "we understand. {PRICE} all-in is honestly the sharpest rate we can get for {ROUTE} today, after checking every carrier on the lane.",
               "thanks for asking. We already quoted the lowest rate on {ROUTE}: {AIRLINE} at {PRICE} all-in."],
        "de": ["danke für Ihr Feedback. Wir haben alle Airlines für {ROUTE} verglichen, {PRICE} all-in mit {AIRLINE} ist aktuell die beste Rate.",
               "verstehen wir. {PRICE} all-in ist ehrlich gesagt die beste Rate, die wir heute für {ROUTE} bekommen, nach Prüfung aller Carrier.",
               "danke für die Nachfrage. Wir haben bereits die günstigste Rate für {ROUTE} angeboten: {AIRLINE} zu {PRICE} all-in."]},
    "meeting": {
        "en": ["thank you for the feedback on the price. Our quote of {PRICE} is already based on the best rate we found for {ROUTE}, "
               "but we are happy to look at the options together (dates, routing, volume). {FORWARDER} from our team can call you at:\n\n{SLOTS}",
               "understood, price matters. {PRICE} is the best rate we found for {ROUTE} today, but there may be room with other dates or "
               "routings. {FORWARDER} would be glad to talk it through with you. Free times:\n\n{SLOTS}",
               "thanks for your honest feedback. Let's see what we can do on {ROUTE}: {FORWARDER} from our team can go through the options "
               "with you in a short call. Would one of these times work?\n\n{SLOTS}"],
        "de": ["vielen Dank für Ihre Rückmeldung zum Preis. Unser Angebot über {PRICE} basiert bereits auf der besten Rate für {ROUTE}, "
               "aber wir schauen uns die Möglichkeiten gerne gemeinsam an (Termine, Routing, Volumen). {FORWARDER} kann Sie anrufen am:\n\n{SLOTS}",
               "verstanden, der Preis ist wichtig. {PRICE} ist heute die beste Rate für {ROUTE}, mit anderen Terminen oder Routings ist "
               "eventuell mehr drin. {FORWARDER} bespricht das gerne mit Ihnen. Freie Termine:\n\n{SLOTS}",
               "danke für das offene Feedback. Schauen wir gemeinsam, was bei {ROUTE} möglich ist: {FORWARDER} aus unserem Team geht die "
               "Optionen gerne in einem kurzen Gespräch mit Ihnen durch. Passt einer dieser Termine?\n\n{SLOTS}"]},
}
CLOSE = {
    "booked": {"en": ["We will let you know as soon as the airline has confirmed it.", "You'll hear from us once the airline confirms.",
                      "We'll send the confirmation as soon as it arrives."],
               "de": ["Sobald die Airline bestätigt hat, melden wir uns.", "Die Bestätigung der Airline schicken wir Ihnen umgehend weiter.",
                      "Wir melden uns, sobald die Bestätigung da ist."]},
    "requested": {"en": ["You will hear from us as soon as it is confirmed.", "We'll be back in touch once the airline confirms."],
                  "de": ["Sobald sie bestätigt ist, melden wir uns.", "Wir melden uns, sobald die Airline bestätigt."]},
    "confirmed": {"en": ["Just reply here if you need a status update.", "If you need anything else, simply reply to this mail.",
                         "Questions about the shipment? Reply here any time."],
                  "de": ["Für einen Status antworten Sie einfach hier.", "Wenn Sie noch etwas brauchen, antworten Sie einfach auf diese Mail.",
                         "Fragen zur Sendung? Antworten Sie jederzeit hier."]},
    "cheaper_option": {"en": ["Just reply 'book it' and we'll take care of the rest.", "Shall we book it? A short yes is enough.",
                              "Reply with a go-ahead and we book it right away."],
                       "de": ["Antworten Sie einfach mit 'buchen', den Rest erledigen wir.", "Sollen wir buchen? Ein kurzes Ja genügt.",
                              "Mit Ihrer Freigabe buchen wir sofort."]},
    "best_rate": {"en": ["The offer stays valid for today, just reply 'book it' if you'd like to go ahead.",
                         "If it works for you, a short 'yes, book it' is all we need.",
                         "Happy to book it whenever you are ready."],
                  "de": ["Das Angebot gilt heute weiter, antworten Sie einfach mit 'buchen', wenn Sie möchten.",
                         "Wenn es für Sie passt, genügt ein kurzes 'Ja, bitte buchen'.",
                         "Wir buchen gerne, sobald Sie bereit sind."]},
    "meeting": {"en": ["Just reply with the time that suits you best.", "Simply reply with your preferred slot.",
                       "Let us know which one works, or suggest another time."],
                "de": ["Antworten Sie einfach mit dem Termin, der Ihnen am besten passt.", "Nennen Sie uns einfach Ihren Wunschtermin.",
                       "Sagen Sie uns, welcher passt, oder schlagen Sie eine andere Zeit vor."]},
}


def first_name(address):
    """anna.schmidt@x -> Anna; j.doe@x -> None (initial only); sales@x -> None."""
    local = (address or "").split("@")[0].lower()
    part = re.split(r"[._\-+]", local)[0]
    if part in ROLE or len(part) < 2 or not part.isalpha():
        return None
    return part.capitalize()


def combos(kind, lang):
    lang = lang if lang in BODY[kind] else "en"
    return lang, (len(GREET[lang]["name"]), len(BODY[kind][lang]), len(CLOSE[kind][lang]), len(SIGN[lang]))


def render(kind, lang, values, thread_id=0, customer=""):
    lang, sizes = combos(kind, lang)
    rng = random.Random("%s:%s" % (thread_id, kind))
    pick = [rng.randrange(n) for n in sizes]
    key, last = "reply_variant:%s:%s" % (kind, lang), None
    try:
        last = db.get_state(key)
    except Exception:
        pass
    if last == ",".join(map(str, pick)):                     # same as the previous mail of this kind: rotate the body
        pick[1] = (pick[1] + 1) % sizes[1]
        pick[0] = (pick[0] + 1) % sizes[0]
    try:
        db.set_state(key, ",".join(map(str, pick)))
    except Exception:
        pass
    name = first_name(customer)
    greet = (GREET[lang]["name"][pick[0]].replace("{NAME}", name) if name
             else GREET[lang]["anon"][pick[0] % len(GREET[lang]["anon"])])
    body = BODY[kind][lang][pick[1]]
    body = body[:1].upper() + body[1:] if body[:1] != "{" else body
    text = "%s\n\n%s\n\n%s\n\n%s" % (greet, body, CLOSE[kind][lang][pick[2]], SIGN[lang][pick[3]])
    for k, v in values.items():
        text = text.replace("{%s}" % k, str(v))
    return text, ",".join(map(str, pick))
