"""Task 04: book by rate ID when the customer accepts, and keep the customer informed.

Two handlers, registered in core/main.py HANDLERS:
  follow_up             customer answers our quote:
                          accept       -> book -> tell the customer
                          decline      -> status lost, no mail
                          better_price -> cheaper option by mail if we have one; big shipment -> 3 call slots with
                                          our forwarder (calendar + customer time zone); else "best rate" mail
                          unclear      -> needs_human
  booking_confirmation  "Booking BK-... confirmed" from the airline -> mark confirmed -> tell the customer

No LLM call here: answers are read with rules, mails come from rotating templates (replies.py) (an extra gateway call would raise our cost per quote).
Anything unclear goes to needs_human, never a guess.

Booking paths:
  portal airline (option has rate_id) -> POST /v1/portal/bookings. Rate expired (410) -> fresh rate, book that.
  sheet airline (no rate_id)          -> booking request mail to the airline (address from carrier-list.csv).
"""
import csv, json, os, re, time
from decimal import Decimal
from core import config, db, mailbox
from . import crm, meeting, replies

_KIT = os.path.join(config.ROOT, "kit", "start-kit")
AIRLINE_EMAIL = {r["name"].lower(): r["email"] for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv")))
                 if r["kind"] == "airline"}
# A fresh rate may cost more than what we quoted. Above this we do not book on our own.
# Who may confirm a booking: the airlines and truckers of the start kit, nobody else (a customer can fake the subject).
CARRIER_SENDERS = {r["email"].lower() for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv")))}
# The real confirmation sender is not seen yet (first booking after 16:00). If it is a portal address, add it here.
CARRIER_SENDERS |= {x.strip().lower() for x in os.environ.get("CONFIRM_SENDERS", "").split(",") if x.strip()}
_SYSTEM_SENDER = re.compile(r"^(no-?reply|portal|bookings?|confirm\w*|ratedesk)@hackloop\.mail$")
MAX_REPRICE = Decimal(os.environ.get("BOOK_MAX_REPRICE", "1.05"))
# A call with our forwarder costs a person's time: only offer it from this quote size up (EUR). Below: mail only.
MEETING_MIN_EUR = Decimal(os.environ.get("MEETING_MIN_EUR", "1500"))

ACCEPT = re.compile(r"\b(accept\w*|book (it|this|that|the)|please book|go ahead|confirm(ed)?|agreed|deal|"
                    r"sounds good|let'?s do it|approved?|ja\b|buchen|bitte buchen|einverstanden|passt|auftrag|"
                   r"proceed|works for us|(?:ok|okay|fine) for us|we'?ll take it|we will take it|go for it|please arrange|"
                   r"yes,? (?:please|that works|we agree|go)|machen wir so|alles klar|in ordnung|va bene|procedete|procedi|"
                    r"bestätig\w*|d'accord|réserv\w*|acepto|reserv\w*|confermo|prenot\w*)", re.I)
DECLINE = re.compile(r"\b(no,? thanks?|decline\w*|not interested|cancel\w*|we pass|found another|went with another|"
                     r"(?:go|going|decided to go) with (?:another|a different) (?:forwarder|provider|agent|company|offer)|"
                     r"(?:we'?ll|we will|we'?re going to) pass|pass on this|"
                     r"nein|kein interesse|absagen|storn\w*|anderen anbieter|non merci|no gracias)\b", re.I)
# A negated "go ahead / proceed / book" is a DECLINE, not an accept (live bug: "we will not go ahead" was booked).
NEGATED_PROCEED = re.compile(r"\b(won'?t|will not|would not|do(es)?\s*n'?t|did\s*n'?t|cannot|can'?t|"
                             r"not|never|decided (not|against)|rather not|prefer not|hold off|"
                             r"nicht|werden nicht|m[oö]chten? nicht)\b[^.?!]{0,40}?"
                             r"\b(go(ing)? ahead|proceed|book|order|confirm|move forward|buch\w*|fortfahren|best[aä]tig\w*)\b", re.I)
# Italian / French / Spanish "we do not proceed / confirm / book" (red-team #56: "Grazie, ma non procediamo con
# questa offerta." was read as a yes and BOOKED, because ACCEPT's "procedi" matches inside "procediamo"). The verbs
# are spelled out so an English "No problem, please book it" stays a yes.
NEGATED_ROMANCE = re.compile(
    r"\b(?:non|ne|n'|no)\s+(?:\w+\s+){0,2}?(?:procedi\w*|procede\w*|confermi\w*|conferma\w*|confirm(?:ons|erons|amos|aremos)|"
    r"prenoti\w*|prenota\w*|accetti\w*|accetta\w*|acept(?:amos|aremos|o)|reserv(?:amos|aremos)|réserv(?:ons|erons)|"
    r"donn(?:ons|erons)\s+(?:pas\s+)?suite|andiamo\s+avanti|vamos\s+a\s+(?:seguir|reservar|confirmar|proceder))", re.I)
HEDGE = re.compile(r"\b(yet|still|for now|at the moment|right now|checking|review\w*|noch|momentan|gerade|pr[uü]f\w*)\b", re.I)
PRICE = re.compile(r"\b(cheaper|better price|best price|lower( the)? price|discount|too expensive|too high|negotiat\w*|"
                   r"budget|match|günstiger|rabatt|zu teuer|preis\w* (senken|nachlass|verhandeln)|moins cher|"
                   r"do (?:any |a bit |a little )?better|better (?:offer|rate|deal)|lower (?:rate|offer)|"
                   r"más barato|descuento|sconto|prezzo migliore|più economico|meno caro|troppo caro|faire mieux|"
                   r"(?:un peu|trop) cher|meilleur prix|mejor precio|demasiado caro)\b", re.I)
QUESTION = re.compile(r"\?|\b(could you|can you|what about|instead|cheaper|faster|change|könnten sie|anders)\b", re.I)
BK = re.compile(r"\bBK-[A-Za-z0-9]{6,12}\b")
TEAM_REF = re.compile(r"\bGOOGLE-\d+\b")



# A yes with a condition or new facts is not a yes: "but", "next week", "don't book yet", a new weight or price.
CONDITION = re.compile(r"\b(but|however|only if|as long as|unless|later|next week|tomorrow|not yet|don'?t|do not|wait|"
                       r"first|as agreed|you (said|quoted|promised)|aber|nur wenn|sofern|später|nächste woche|morgen|"
                       r"noch nicht|nicht buchen|warten|erst|wie besprochen|vereinbart|mais|pero|però)\b", re.I)
NEW_FACTS = re.compile(r"\d[\d.,]*\s*(kg|kgs|lbs?|t\b|tons?|tonnen|cbm|m3|m³|eur|€|usd|\$|chf|pcs|pieces|pallets?|"
                       r"paletten|colli)|(eur|€|\$|usd)\s*\d", re.I)

# "Good point, we will send the dangerous goods documents shortly": the customer is PROCEEDING after our DG ask,
# not declining and not a clear yes. Acknowledge and await the papers instead of handing it to a human.
_DOCS = (r"(shipper'?s? declaration|safety data sheet|\bmsds\b|\bsds\b|\bdgd\b|dangerous goods?[^.?!]{0,20}"
         r"(document|paper|declaration|sheet)|gefahrgut\w*[^.?!]{0,20}(dokument|papier|erkl[aä]rung)|"
         r"document\w*[^.?!]{0,20}(marchandises dangereuses|peligros)|d[ée]claration[^.?!]{0,40}marchandises dangereuses|"
         r"fiche de donn[ée]es de s[ée]curit[ée]|sicherheitsdatenbl[aä]tt\w*)")
_SEND = (r"(send|provide|forward|share|supply|pass (?:it |them |you )?along|get (?:you |it )?|"
         r"senden|schicken|nachreich\w*|zusenden|zukommen|envoy\w*|enviar\w*|invi\w*)")
SENDING_DOCS = re.compile(_SEND + r"[^.?!]{0,60}?" + _DOCS + r"|" + _DOCS + r"[^.?!]{0,60}?" + _SEND, re.I)


FASTER = re.compile(r"\b(faster|quicker|sooner|earlier|express|speed (it )?up|schneller|früher|eiliger|più veloce|plus rapide|"
                    r"más rápido)\b", re.I)
_QUOTED_START = re.compile(r"\n\s*(?:>|On .+wrote:|Am .+schrieb)")


def own_text(body, subject=""):
    """The customer's own words: above our quoted mail; if they wrote BELOW it (bottom-posting), the lines after the
    quote that are not quoted; if the body is empty, the subject without 'Re:' (a 'YES, BOOK IT' subject)."""
    body = body or ""
    top = _QUOTED_START.split("\n" + body, maxsplit=1)[0].strip()   # "\n": the quote may start on the first line
    if top:
        return top
    m = _QUOTED_START.search("\n" + body)
    if m:
        rest = [l for l in ("\n" + body)[m.end():].splitlines() if not l.lstrip().startswith(">")]
        bottom = "\n".join(rest).strip()
        if bottom:
            return bottom
    return re.sub(r"^\s*((re|aw|fwd?|wg)\s*:\s*)+", "", subject or "", flags=re.I).strip()


SHORT_YES = re.compile(r"^\W*(?:ok(?:ay)?|yes|yep|yeah|ja|jawohl|s[ií]|oui|d'accord|de acuerdo|claro|perfecto|perfect|"
                       r"great|super|top|fine|bitte um buchung|buchung bitte)\b[\s,.!]*(?:(?:please|pls|bitte|thanks|thank you|"
                       r"danke|merci|gracias|grazie|adelante|go ahead|book it|buchen)\b[\s,.!]*)*$", re.I)
AUTO_REPLY = re.compile(r"\b(out of (?:the )?office|automatic reply|auto-?reply|autoreply|abwesenheitsnotiz|"
                        r"bin (?:bis|vom) [^.\n]{0,40}(?:nicht im b[üu]ro|abwesend)|absent until|on (?:annual )?leave until|"
                        r"limited access to e-?mail|r[ée]ponse automatique|fuera de la oficina|fuori ufficio)\b", re.I)
_SIG_LINE = re.compile(r"^(?:[A-ZÄÖÜ][\w.'-]+(?: [A-ZÄÖÜ][\w.'-]+){0,2}|(?:best |kind |many )?(?:regards|thanks|cheers|grüße|gruß|"
                       r"saludos|saluti|cordialement)[\w ,.!]*)$", re.I)


def _answer_lines(text):
    """The customer's answer without a trailing name / sign-off line ('ok\nSara' -> 'ok')."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    while len(lines) > 1 and _SIG_LINE.match(lines[-1]):
        lines.pop()
    return "\n".join(lines)


def _last_sentence(text):
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n", _answer_lines(text)) if p.strip()]
    return parts[-1] if parts else ""


EXTRA_SERVICE = re.compile(r"\b(insur\w*|versicher\w*|assicura\w*|assur\w*|seguro)\b[^.?!\n]{0,60}|"
                           r"\b(?:cargo|goods|commercial|invoice) value\b[^.?!\n]{0,40}|\bwarenwert\b[^.?!\n]{0,40}", re.I)
VALIDITY = re.compile(r"\b(how long (?:is|will) (?:the|this|your) (?:offer|quote|price|rate)|(?:offer|quote|price|rate) (?:is )?valid|"
                      r"validity|valid (?:until|till|for how long)|wie lange (?:ist|gilt) (?:das|ihr) (?:angebot|preis)|"
                      r"g[üu]ltig(?:keit)?|validit[àé])\b", re.I)


def classify(body, subject=""):
    """accept / decline / better_price / faster / sending_docs / unclear. Only the customer's new text counts."""
    # "so we won\u2019t go ahead" (typographic apostrophe) was read as "go ahead" = yes and BOOKED (live, round 72)
    text = own_text(body, subject).replace("\u2019", "'").replace("\u2018", "'").replace("\u02bc", "'").replace("`", "'")
    if DECLINE.search(text) or NEGATED_ROMANCE.search(text) or (NEGATED_PROCEED.search(text) and not HEDGE.search(text)):   # definitive "won't proceed" = decline; "not yet" = wait (unclear)
        return "decline"
    if AUTO_REPLY.search(text):                # an out-of-office robot is no answer: the quote stays open
        return "auto_reply"
    if PRICE.search(text):
        return "better_price"
    if SENDING_DOCS.search(text):              # "Passt, das Sicherheitsdatenblatt schicken wir nach": a yes, papers follow (#58)
        return "sending_docs"
    facts = EXTRA_SERVICE.sub(" ", text)       # "book it, and insure it for EUR 25,000": the amount is a service wish
    if ACCEPT.search(text) and not QUESTION.search(text) and not CONDITION.search(text) and not NEW_FACTS.search(facts):
        return "accept"
    if VALIDITY.search(text) and not ACCEPT.search(text):
        return "validity"
    if SHORT_YES.match(_answer_lines(text)):  # a bare "ok" / "Yes" / "De acuerdo" to OUR quote is a yes (#53)
        return "accept"
    last = _last_sentence(text)                # the answer is the last sentence; a "but" in an old story does not count (#54)
    if last and ACCEPT.search(last) and not QUESTION.search(last) and not CONDITION.search(last) and not NEW_FACTS.search(last) \
            and not QUESTION.search(text):
        return "accept"
    if FASTER.search(text) and not ACCEPT.search(text):
        return "faster"
    if SENDING_DOCS.search(text):              # proceeding, just sending the DG papers first
        return "sending_docs"
    return "unclear"


ACK_DOCS = {
    "en": "Thank you, that is perfect. Please send the dangerous goods documents whenever they are ready, and I will confirm the booking right away.",
    "de": "Vielen Dank, das passt bestens. Senden Sie uns die Gefahrgutdokumente einfach, sobald sie bereit sind, und ich bestätige die Buchung umgehend.",
    "it": "Grazie, perfetto. Ci invii pure i documenti per le merci pericolose non appena pronti e confermo subito la prenotazione.",
    "fr": "Merci, c'est parfait. Envoyez-nous les documents marchandises dangereuses dès qu'ils sont prêts et je confirme la réservation tout de suite.",
    "es": "Gracias, perfecto. Envíenos los documentos de mercancía peligrosa en cuanto estén listos y confirmo la reserva de inmediato.",
}


def _await_docs(tid, mail, s):
    """Customer will send the DG documents: acknowledge, await them, then book when they arrive."""
    lang = (json.loads(s["fields"] or "{}").get("language") or "en")[:2].lower()
    subject = s["subject"] if (s["subject"] or "").lower().startswith("re:") else "Re: " + (s["subject"] or "")
    mailbox.send(s["customer"], subject, ACK_DOCS.get(lang, ACK_DOCS["en"]), in_reply_to=tid, thread_id=tid)
    db.update_session(tid, status="awaiting_docs", note="customer will send DG documents; await then book")
    return db.event("awaiting_docs", tid, mail["id"], customer=s["customer"])


def _values(b, lang):
    route = "%s %s %s" % (b.get("origin"), "nach" if lang == "de" else "to", b.get("destination"))
    return {"ROUTE": route, "AIRLINE": b.get("airline") or "", "PRICE": "%s %s" % (b.get("price"), b.get("currency")),
            "REF": b.get("booking_reference") or b.get("team_reference"), "TRANSIT": b.get("transit_days") or ""}


def _write(kind, lang, b, extra=None):
    """Mail text from rotating templates (replies.py): no LLM, $0 cost, varied wording."""
    text, variant = replies.render(kind, lang, dict(_values(b, lang), **(extra or {})),
                                   thread_id=b.get("thread_id", 0), customer=b.get("customer", ""))
    db.event("reply_variant", b.get("thread_id"), message=kind, variant=variant)
    return text


def _tell_customer(b, kind):
    subject = b["subject"] if (b["subject"] or "").lower().startswith("re:") else "Re: " + (b["subject"] or "")
    ok = mailbox.send(b["customer"], subject, _write(kind, b.get("language") or "en", b),
                      in_reply_to=b["last_customer_mail_id"], thread_id=b["thread_id"])
    db.event("customer_informed" if ok else "customer_inform_failed", b["thread_id"], message=kind)
    return ok


def _reply_session(s, mail, body, what):
    subject = s["subject"] if (s["subject"] or "").lower().startswith("re:") else "Re: " + (s["subject"] or "")
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=mail["id"], thread_id=s["thread_id"])
    db.event("customer_informed" if ok else "customer_inform_failed", s["thread_id"], mail["id"], message=what)
    return ok


def _session_view(s):
    c, f = json.loads(s["chosen"] or "{}"), json.loads(s["fields"] or "{}")
    return dict(origin=c.get("origin"), destination=c.get("destination"), airline=c.get("airline"),
                price=c.get("total"), currency=c.get("currency"), team_reference=crm.team_reference(s["thread_id"]),
                transit_days=c.get("transit_days"), thread_id=s["thread_id"], customer=s["customer"]), f.get("language") or "en"


def handle_better_price(s, mail):
    """Customer wants a better price. Cheapest first, a call only when it is worth the forwarder's time:
    1. we have a cheaper option for this lane (e.g. we quoted 'fastest') -> offer it by mail, status stays quoted
    2. shipment is big enough (quote >= MEETING_MIN_EUR)                -> offer 3 call slots with our forwarder
    3. small shipment, already our best rate                           -> polite mail: this is our best rate, still valid
    """
    tid = s["thread_id"]
    view, lang = _session_view(s)
    chosen, options = json.loads(s["chosen"] or "{}"), json.loads(s["options"] or "[]")
    eur = lambda o: Decimal(str(o.get("total_eur") or o.get("total") or "0"))
    cheaper = sorted((o for o in options if eur(o) < eur(chosen)), key=eur)
    if cheaper:
        alt = cheaper[0]
        body = _write("cheaper_option", lang, view, {"ALT_AIRLINE": alt["airline"], "ALT_TRANSIT": alt.get("transit_days"),
                                                     "ALT_PRICE": "%s %s" % (alt["total"], alt["currency"])})
        _reply_session(s, mail, body, "cheaper_option")
        db.update_session(tid, chosen=alt, note="customer wanted a better price, cheaper option offered")
        return db.event("cheaper_option_offered", tid, mail["id"], before=chosen.get("total"), after=alt["total"])
    if eur(chosen) >= MEETING_MIN_EUR:
        return offer_meeting(s, mail, view, lang)
    _reply_session(s, mail, _write("best_rate", lang, view), "best_rate")
    db.update_session(tid, note="customer wanted a better price, told it is our best rate (small shipment)")
    db.event("best_rate_kept", tid, mail["id"], total=chosen.get("total"))


def offer_meeting(s, mail, view, lang):
    """Propose 3 call slots from the forwarder's calendar, shown in the customer's time zone."""
    tz = meeting.customer_zone(mail["body"], mail["sender"])
    slots, cal = meeting.free_slots(tz)
    if not slots:
        return _needs_human(s["thread_id"], mail["id"], "customer wants a better price, no free slot in the calendar")
    lines = "\n".join("- " + meeting.fmt(x, tz, lang) for x in slots)
    body = _write("meeting", lang, view, {"SLOTS": lines, "FORWARDER": cal.get("name", "our account manager")})
    _reply_session(s, mail, body, "meeting")
    db.update_session(s["thread_id"], status="meeting_proposed",
                      note="better price wanted, call offered: " + "; ".join(x.isoformat() for x in slots))
    db.event("meeting_proposed", s["thread_id"], mail["id"], customer_tz=str(tz), slots=[x.isoformat() for x in slots])


def _needs_human(tid, mail_id, why):
    db.update_session(tid, status="needs_human", note=why)
    db.event("needs_human", tid, mail_id, why=why)


def _fresh_rate(chosen, fields):
    status, r = mailbox.api("GET", "/v1/portal/rates", params={
        "origin": chosen["origin"], "destination": chosen["destination"],
        "airline": chosen.get("airline_code") or chosen["airline"],
        "weight_kg": chosen.get("billed_kg") or fields.get("weight_kg_total") or fields.get("weight_kg"),  # keep the weight break
        "volume_cbm": fields.get("volume_cbm_total") or fields.get("volume_cbm") or 0})
    return r if status == 200 else None


def book_portal(tid, chosen, fields):
    """POST the booking. Returns (status word, booking dict or reason)."""
    if config.DRY_RUN:
        fake = {"booking_reference": "BK-DRYRUN%02d" % (tid % 100), "price": chosen["total"],
                "currency": chosen["currency"], "airline": chosen["airline"], "airline_code": chosen.get("airline_code")}
        db.event("booking_dry_run", tid, rate_id=chosen["rate_id"])
        return "booked", fake
    rate_id = chosen["rate_id"]
    for attempt in range(2):
        status, r = mailbox.api("POST", "/v1/portal/bookings",
                                body={"rate_id": rate_id, "team_reference": crm.team_reference(tid)})
        db.event("booking_call", tid, status=status, rate_id=rate_id, response=r)
        if status in (200, 201):
            return "booked", r
        if status == 410 and attempt == 0:                      # rate older than 15 min: get a fresh one
            fresh = _fresh_rate(chosen, fields)
            if not fresh:
                return "fail", "rate expired and no fresh rate"
            fx = Decimal(fresh.get("fx_eur_per_usd") or "1")              # portal may answer in USD
            fresh_eur = Decimal(fresh["total"]) * fx
            quoted_eur = Decimal(chosen.get("total_eur") or chosen["total"])
            if fresh_eur > quoted_eur * MAX_REPRICE:
                return "fail", "fresh rate %.2f EUR is above our quote %s EUR" % (fresh_eur, quoted_eur)
            rate_id = fresh["rate_id"]
            continue
        if status == 503:
            return "fail", "portal booking down, book by email: %s" % str(r)[:200]
        return "fail", "booking %s: %s" % (status, str(r)[:200])
    return "fail", "booking failed after fresh rate"


def request_by_mail(tid, chosen, fields):
    """Book by mail: a sheet airline (no rate_id), or a portal airline whose booking the portal refuses (503)."""
    to = AIRLINE_EMAIL.get((chosen["airline"] or "").lower())
    if not to:
        return False
    rate = "portal rate ID %s" % chosen["rate_id"] if chosen.get("rate_id") else "your tariff"
    body = ("Hello,\n\nplease book the following air export shipment.\n\n"
            "Our reference: {ref}\nRoute: {o} - {d}\nWeight: {w} kg, volume {v} cbm\nRate: {rate}, all-in {p} {c}\n\n"
            "Please confirm with your booking reference.\n\nBest regards\nYour forwarding team").format(
        ref=crm.team_reference(tid), o=chosen["origin"], d=chosen["destination"], rate=rate,
        w=fields.get("weight_kg_total"), v=fields.get("volume_cbm_total"),
        p=chosen.get("flight_total") or chosen["total"],          # the airline's price, without our trucker leg
        c=chosen.get("flight_currency") or chosen["currency"])
    return mailbox.send(to, "Booking request %s %s-%s" % (crm.team_reference(tid), chosen["origin"], chosen["destination"]),
                        body, thread_id=tid)


_AMOUNT = re.compile(r"(\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}|\d+[.,]\d{2})")


def chosen_from_reply(s):
    """A human sent the quote (take-over queue): find the option whose price is in their reply text."""
    options = json.loads(s["options"] or "[]")
    amounts = set()
    for m in _AMOUNT.finditer(s["reply"] or ""):
        a = m.group(1).replace(" ", "")
        a = a.replace(".", "").replace(",", ".") if re.search(r",\d{2}$", a) else a.replace(",", "")
        amounts.add(Decimal(a))
    hits = [o for o in options for k in ("total_eur", "total") if o.get(k) and Decimal(str(o[k])) in amounts]
    if not hits:
        return None
    db.update_session(s["thread_id"], chosen=hits[0])
    db.event("chosen_from_human_reply", s["thread_id"], airline=hits[0].get("airline"), total=hits[0].get("total"))
    return hits[0]


UNCLEAR_NOTE = "customer answered the quote, not a clear yes or no"
VALIDITY_ANSWER = {
    "en": "Hi,\n\ngood question. The price is valid for a booking today; airline rates can change from one day to the next. "
          "Just reply 'book it' when you have your approval: if the airline still holds the rate, I confirm it at this price, "
          "and if it has moved, I come back to you before anything is booked.\n\nBest regards\n%s\nAir Export",
    "de": "Hallo,\n\ngute Frage. Der Preis gilt für eine Buchung heute; die Raten der Airlines können sich von Tag zu Tag ändern. "
          "Antworten Sie einfach mit 'buchen', sobald Sie die Freigabe haben: Hält die Airline den Preis noch, bestätige ich "
          "ihn so, und hat er sich geändert, melde ich mich vor der Buchung bei Ihnen.\n\nViele Grüße\n%s\nLuftfracht Export",
}


def SIGNER_NAME():
    from llm.extract import SIGNER
    return SIGNER
AFTER_BOOKING = ("booking", "booked", "booking_requested", "confirmed")
_THANKS_ONLY = re.compile(r"^\W*(?:(?:many |thank you|thanks|danke|vielen dank|merci|grazie|gracias|perfect|great|super|"
                          r"ok|noted|received|erhalten|top|wonderful|excellent)[\w\s,.!']{0,60})$", re.I)
POST_BOOKING = [   # (kind, rule): what a customer writes after the booking that a forwarder must act on
    ("cancellation", re.compile(r"\b(cancel\w*|storn\w*|annul\w*|call (?:it )?off|no longer needed|nicht mehr ben[öo]tigt)\b", re.I)),
    ("complaint", re.compile(r"\b(did ?n[o']t (?:show|arrive|come|turn up)|not (?:shown|arrived|picked up)|no(?:body| one) came|"
                             r"still waiting|damaged|broken|missing|complain\w*|unacceptable|"
                             r"nicht (?:gekommen|abgeholt|erschienen)|beschädigt|reklamation|beschwerde)\b", re.I)),
    ("change", re.compile(r"\b(change|changed|instead|new (?:date|address|pickup|weight)|postpone\w*|delay\w*|moved?|"
                          r"only (?:be )?ready on|not ready|verschieb\w*|änder\w*|neue[rs]? (?:termin|datum|adresse)|"
                          r"\d+\s*(?:kg|cbm|m3|pallets?|pieces)|20\d\d-\d\d-\d\d)\b", re.I)),
]
ACK_AFTER = {
    "en": "Hi,\n\nthank you, noted. I have passed this straight to my colleague handling your booking%s, and we will get back "
          "to you shortly.\n\nBest regards\n%s\nAir Export",
    "de": "Hallo,\n\nvielen Dank, ist notiert. Ich habe das direkt an meinen Kollegen gegeben, der Ihre Buchung betreut%s, wir "
          "melden uns in Kürze.\n\nViele Grüße\n%s\nLuftfracht Export",
}


STATUS_Q = re.compile(r"\b(where is (?:the|our|my) (?:shipment|cargo|goods|consignment|freight)|any (?:news|update)|status|"
                      r"has it (?:left|departed|arrived|landed)|when (?:will|does) it (?:leave|depart|arrive|land)|eta\b|tracking|"
                      r"wo ist (?:die|unsere|meine) (?:sendung|ware)|stand der sendung|schon (?:abgeflogen|angekommen))", re.I)


def after_booking(s, mail):
    """A customer mail after the booking: a 'thank you' needs nothing; an auto-reply is ignored; a cancellation, a new
    date / address / weight or a complaint goes to a human at once (red, with the reason) and the customer gets a short
    acknowledgement instead of silence (red-team round 5: all three were dropped as follow_up_ignored)."""
    tid = s["thread_id"]
    text = own_text(mail["body"], mail.get("subject"))
    if AUTO_REPLY.search(text):
        return db.event("after_booking_auto_reply", tid, mail["id"])
    kind = next((k for k, rx in POST_BOOKING if rx.search(text)), None)
    if not kind and STATUS_Q.search(text):                       # "where is my shipment?": answer from the booking, like tracking
        from booking import tracking
        b = crm.get(tid)
        if b:
            lang = "de" if (b.get("language") or "").lower().startswith("de") else "en"
            _reply_session(s, mail, tracking.answer_text(b, tid, lang), "status_answer")
            return db.event("after_booking_status_answered", tid, mail["id"])
    if not kind:
        return db.event("follow_up_ignored", tid, mail["id"], status=s["status"],
                        why="thanks" if _THANKS_ONLY.match(_answer_lines(text)) else "nothing to act on")
    db.update_session(tid, status="needs_human", note="AFTER BOOKING, customer %s: %s" % (kind.upper(), text.replace("\n", " ")[:300]))
    db.event("after_booking_" + kind, tid, mail["id"], was=s["status"])
    from llm.extract import SIGNER
    b = crm.get(tid) or {}
    lang = "de" if (b.get("language") or "").lower().startswith("de") else "en"
    ref = b.get("booking_reference") or crm.team_reference(tid)
    _reply_session(s, mail, ACK_AFTER[lang] % ((" (%s)" % ref) if ref else "", SIGNER), "after_booking_" + kind)


def handle_faster(s, mail):
    """'Anything faster?': offer our fastest option if it is faster than the one we quoted, like the cheaper offer."""
    tid = s["thread_id"]
    view, lang = _session_view(s)
    chosen, options = json.loads(s["chosen"] or "{}"), json.loads(s["options"] or "[]")
    days = lambda o: float(o.get("transit_days") if o.get("transit_days") is not None else 99)   # noqa: E731
    faster = sorted((o for o in options if days(o) < days(chosen)), key=lambda o: (days(o), Decimal(str(o.get("total_eur") or o["total"]))))
    if not faster:
        return _needs_human(tid, mail["id"], "customer wants it faster, we quoted our fastest option already")
    alt = faster[0]
    body = _write("faster_option", lang, view, {"ALT_AIRLINE": alt["airline"], "ALT_TRANSIT": alt.get("transit_days"),
                                                "ALT_PRICE": "%s %s" % (alt["total"], alt["currency"])})
    _reply_session(s, mail, body, "faster_option")
    db.update_session(tid, chosen=alt, note="customer wanted it faster, faster option offered")
    return db.event("faster_option_offered", tid, mail["id"], before=chosen.get("transit_days"), after=alt.get("transit_days"))


def correction_before_quote(s, mail):
    """The customer corrects weight / volume while we still wait for bids ('6 pallets, 760 kg, not 540'). Before, the
    mail was ignored and we quoted the old weight (red-team round 4). Now: the new totals go into the form, sheet and
    portal prices are taken again, and the airline bids (asked for the OLD weight) no longer count. Code only."""
    from core import main
    from shared.rfq import extract_rfq
    tid = s["thread_id"]
    text = own_text(mail["body"], mail.get("subject"))
    r = extract_rfq("", text)
    fields = json.loads(s["fields"] or "{}")
    new_kg, new_cbm = r.weight_kg, r.volume_cbm
    old_kg, old_cbm = fields.get("weight_kg_total"), fields.get("volume_cbm_total")
    if not new_kg and not new_cbm:
        return db.event("follow_up_ignored", tid, mail["id"], status=s["status"], why="no new weight or volume")
    # "not 540 kg": the first weight is the new one only if the old value is the one negated
    kgs = [float(x.replace(",", ".")) for x in re.findall(r"(\d+(?:[.,]\d+)?)\s*kg", text, re.I)]
    if old_kg and len(kgs) > 1:
        new_kg = next((k for k in kgs if abs(k - float(old_kg)) > 0.5), new_kg)
    changed = {}
    if new_kg and (not old_kg or abs(float(new_kg) - float(old_kg)) > 0.5):
        changed["weight_kg_total"] = float(new_kg)
    if new_cbm and (not old_cbm or abs(float(new_cbm) - float(old_cbm)) > 0.005):
        changed["volume_cbm_total"] = float(new_cbm)
    if not changed:
        return db.event("follow_up_ignored", tid, mail["id"], status=s["status"], why="same weight and volume")
    fields.update(changed)
    fields["weight_kg"], fields["volume_cbm"] = fields["weight_kg_total"], fields["volume_cbm_total"]
    fields["pieces"] = []                                        # the old pieces describe the old shipment
    o, d, w, v = fields["origin"], fields["destination"], fields["weight_kg_total"], fields.get("volume_cbm_total") or 0
    options = [dict(x, total_eur=x["total"]) for x in main.sheets.options(o, d, w, v)]
    try:
        options += main.portal.options(o, d, w, v)
    except Exception as e:
        db.event("portal_error", tid, mail["id"], error=str(e))
    from sourcing import bids
    bids.ensure()                                                # the bid columns (role, status...) exist
    db.con().execute("UPDATE bids SET status='stale_weight', required=0 WHERE thread_id=? AND role IN ('airline','ratedesk')", (tid,))
    db.update_session(tid, fields=fields, options=options)
    db.event("customer_correction", tid, mail["id"], changed=changed, before={"weight_kg_total": old_kg, "volume_cbm_total": old_cbm},
             options=len(options))
    if not options:
        return main.needs_human(tid, mail, "customer corrected the shipment, no sheet/portal price for the new weight")


PRICE_TOLERANCE = Decimal("1.005")       # a booking price up to 0.5% above the quote is rounding, not a new price


def booked_above_quote(chosen, r):
    """The portal books at ITS price, and that can be above the rate we quoted from: 5U 20:45, rounds 48 and 49
    were booked 10% above the quote and we still confirmed the old price (-22.5 points each). Returns the new
    all-in total (flight at the booked price + the trucker leg), or None when the booking matches the quote."""
    try:
        flight_cur = chosen.get("flight_currency") or chosen.get("currency") or "EUR"
        if (r.get("currency") or "EUR") != flight_cur or flight_cur != (chosen.get("currency") or "EUR"):
            return None                                          # other currency: no safe comparison
        quoted, booked = Decimal(str(chosen.get("flight_total") or chosen["total"])), Decimal(str(r["price"]))
        if booked <= quoted * PRICE_TOLERANCE:
            return None
        return (Decimal(str(chosen["total"])) + booked - quoted).quantize(Decimal("0.01"))
    except Exception:
        return None


def propose_new_price(tid, mail, chosen, r, new_total):
    """The airline booked above our quote: never confirm the old price. Tell the customer the new total and ask."""
    old, cur = chosen["total"], chosen.get("currency") or "EUR"
    new = dict(chosen, quoted_total=old, total=str(new_total), booked_price=str(r["price"]))
    if cur == "EUR":
        new["total_eur"] = str(new_total)
    db.update_session(tid, status="reprice_proposed", chosen=new,
                      note="airline booked at %s %s, above our quote %s: asked the customer to confirm %s" % (
                          r["price"], cur, old, new_total))
    db.event("booking_price_changed", tid, mail["id"], quoted_total=old, booked_price=r["price"],
             new_total=str(new_total), booking_reference=r.get("booking_reference"))
    b = crm.get(tid)
    subject = b["subject"] if (b["subject"] or "").lower().startswith("re:") else "Re: " + (b["subject"] or "")
    ok = mailbox.send(b["customer"], subject,
                      _write("price_changed", b.get("language") or "en", dict(b, price=old),
                             {"NEW_PRICE": "%s %s" % (new_total, cur)}),
                      in_reply_to=mail["id"], thread_id=tid)
    db.event("customer_informed" if ok else "customer_inform_failed", tid, message="price_changed")
    return ok


def reprice_answer(s, mail):
    """The customer's answer to 'the airline's price changed, do you want to go ahead at the new price?'"""
    tid = s["thread_id"]
    verdict = classify(mail["body"], mail.get("subject"))
    db.event("follow_up", tid, mail["id"], verdict=verdict, status=s["status"])
    b = crm.get(tid) or {}
    ref = b.get("booking_reference")
    if verdict == "accept" and b:
        confirmed = b["status"] == "confirmed"                   # the airline's confirmation may already be in
        crm.upsert(tid, last_customer_mail_id=mail["id"])
        db.update_session(tid, status="confirmed" if confirmed else "booked", note="customer accepted the new price")
        return _tell_customer(crm.get(tid), "confirmed" if confirmed else "booked")
    if verdict == "decline":
        crm.upsert(tid, status="cancel_pending")                 # a late airline confirmation must not reach the customer
        return _needs_human(tid, mail["id"], "customer declined the new price %s: cancel booking %s with %s by mail" % (
            b.get("price"), ref, b.get("airline")))
    return _needs_human(tid, mail["id"], "customer answered the new price without a clear yes or no (booking %s stands)" % ref)


def handle_follow_up(mail):
    tid = mail["thread_id"]
    s = db.session(tid)
    if s and s["status"] == "asked_customer":                    # answer to our clarifying question (llm/clarify.py)
        from llm import clarify
        return clarify.answer(mail)
    if s and s["status"] in ("new", "waiting_bids") and mail["sender"] == (s["customer"] or "").lower():
        return correction_before_quote(s, mail)                  # they changed the shipment before our quote went out
    if s and s["status"] == "needs_human" and (s.get("note") or "").startswith(UNCLEAR_NOTE):
        s = dict(s, status="quoted")                             # 'does it include X?' then 'ok, book it': read the new mail
        db.update_session(tid, status="quoted", note="customer wrote again after an unclear reply")
    if s and s["status"] == "reprice_proposed" and mail["sender"] == (s["customer"] or "").lower():
        return reprice_answer(s, mail)                           # yes or no to the airline's new price
    if s and s["status"] in AFTER_BOOKING and mail["sender"] == (s["customer"] or "").lower():
        return after_booking(s, mail)                            # cancel / new date / complaint: never silently dropped
    if not s or s["status"] not in ("quoted", "meeting_proposed", "awaiting_docs"):
        return db.event("follow_up_ignored", tid, mail["id"], status=s and s["status"])
    if mail["sender"] != (s["customer"] or "").lower():          # only the customer who asked can book on this quote
        return _needs_human(tid, mail["id"], "reply from %s, not from the customer %s" % (mail["sender"], s["customer"]))
    verdict = classify(mail["body"], mail.get("subject"))
    db.event("follow_up", tid, mail["id"], verdict=verdict, status=s["status"])
    if verdict == "auto_reply":                                  # out-of-office robot: no alarm, the quote stays open
        return None
    if verdict == "validity":                                    # "how long is the offer valid?": answer, keep the quote open
        view, lang = _session_view(s)
        body = VALIDITY_ANSWER["de" if lang == "de" else "en"] % SIGNER_NAME()
        _reply_session(s, mail, body, "validity_answer")
        return db.event("validity_answered", tid, mail["id"])
    if verdict == "accept" and EXTRA_SERVICE.search(own_text(mail["body"], mail.get("subject"))):
        wish = EXTRA_SERVICE.search(own_text(mail["body"], mail.get("subject"))).group(0)
        db.event("extra_service_requested", tid, mail["id"], wish=wish[:120])
        db.update_session(tid, note="CUSTOMER ALSO ASKED: %s (book it, then arrange this by hand)" % wish[:160])
    if s["status"] == "meeting_proposed" and verdict != "decline":   # "Tue 10:00, please confirm" is not a booking
        return _needs_human(tid, mail["id"], "customer answered our call offer (picked a time?): forwarder to follow up")
    if verdict == "decline":
        return db.update_session(tid, status="lost", note="customer declined")       # no mail, just closed
    if verdict == "better_price":
        return handle_better_price(s, mail)
    if verdict == "faster":
        return handle_faster(s, mail)
    if s["status"] != "awaiting_docs":                   # on a quote still open, a soft/unclear reply does not book
        if verdict == "sending_docs":                    # "we'll send the DG papers" IS the yes for 5U (rounds 39-41 counted
            db.event("sending_docs_book_now", tid, mail["id"])   # accepted). Book NOW: the rate ID expires in ~15 min and a
            # second customer mail may never come (Kai's review of #36). The papers can follow the booking. (Riky)
        if verdict == "unclear":
            return _needs_human(tid, mail["id"], UNCLEAR_NOTE)
    # status == awaiting_docs and not a decline: the promised documents arrived -> proceed to book below

    chosen, fields = (json.loads(s["chosen"] or "null") or chosen_from_reply(s)), json.loads(s["fields"] or "{}")
    if not chosen:                                             # quote sent by a human with a price we cannot match
        return _needs_human(tid, mail["id"], "no_chosen_quote: customer accepted a quote sent by a human, book by hand")
    if chosen.get("parts"):                                    # several shipments (pricing/multi.py): book by hand for now
        return _needs_human(tid, mail["id"], "multi_shipment accepted: book each part by hand: " + "; ".join(
            "%s-%s %s %s EUR" % (p["origin"], p["destination"], p["airline"], p["total_eur"]) for p in chosen["parts"]))
    base = dict(customer=s["customer"], subject=s["subject"], last_customer_mail_id=mail["id"],
                airline=chosen["airline"], airline_code=chosen.get("airline_code"), origin=chosen["origin"],
                destination=chosen["destination"], weight_kg=fields.get("weight_kg_total"),
                volume_cbm=fields.get("volume_cbm_total"), transit_days=chosen.get("transit_days"),
                price=chosen["total"], currency=chosen["currency"], source=chosen.get("source"),
                language=fields.get("language") or "en", rate_id=chosen.get("rate_id"))
    db.update_session(tid, status="booking")

    if chosen.get("rate_id"):
        result, r = book_portal(tid, chosen, fields)
        # 5U 21:00 (request 13471): the portal refuses bookings for some airlines with 503 "Please book by email".
        # That is the sheet-airline path: mail the airline, tell the customer, wait for the airline's confirmation.
        by_mail = (result != "booked" and str(r).startswith("portal booking down")
                   and request_by_mail(tid, chosen, fields))
        if by_mail:
            db.event("portal_booking_down_mail", tid, mail["id"], airline=chosen["airline"])
            crm.upsert(tid, status="requested", raw={"reason": r}, **base)
            db.update_session(tid, status="booking_requested")
            kind = "requested"
        elif result != "booked":
            crm.upsert(tid, status="failed", raw={"reason": r}, **base)
            return _needs_human(tid, mail["id"], r)
        else:
            new_total = booked_above_quote(chosen, r)
            crm.upsert(tid, status="booked", booking_reference=r["booking_reference"], booked_at=time.time(),
                       raw=r, **dict(base, rate_id=r.get("rate_id") or base["rate_id"],
                                     price=str(new_total) if new_total else base["price"]))
            if new_total:                                        # booked above the quote: ask, do not confirm the old price
                return propose_new_price(tid, mail, chosen, r, new_total)
            db.update_session(tid, status="booked")
            kind = "booked"
    else:
        if not request_by_mail(tid, chosen, fields):
            crm.upsert(tid, status="failed", **base)
            return _needs_human(tid, mail["id"], "sheet airline %s: no booking mail address" % chosen["airline"])
        crm.upsert(tid, status="requested", **base)
        db.update_session(tid, status="booking_requested")
        kind = "requested"
    _tell_customer(crm.get(tid), kind)


# An airline / portal mail about a booking that says NO. Before, every "Booking BK-..." mail counted as confirmed and the
# customer was told "confirmed, everything is set" (red-team round 5).
AIRLINE_NO = re.compile(r"\b(cancel+(?:ed|ation)?|rejected|refused|declined|not (?:be )?confirmed|unable to (?:confirm|accept)|"
                        r"cannot (?:confirm|accept)|no (?:capacity|space)|fully booked|failed|void(?:ed)?|"
                        r"storniert|abgelehnt|nicht bestätigt|keine kapazität|ausgebucht)\b", re.I)


def handle_booking_confirmation(mail):
    if mail["sender"] not in CARRIER_SENDERS and not _SYSTEM_SENDER.match(mail["sender"]):                    # customers and strangers cannot confirm bookings
        return db.event("confirmation_rejected_sender", mail["thread_id"], mail["id"], sender=mail["sender"])
    text = mail["subject"] + "\n" + mail["body"]
    ref, team = BK.search(text), TEAM_REF.search(text)
    b = crm.find(ref and ref.group(0), team and team.group(0))
    if b and b["booking_reference"] and ref and ref.group(0) != b["booking_reference"]:
        b = None                                                 # portal booking: the BK number must match ours
    if b and b["status"] not in ("booked", "requested", "confirmed"):
        b = None
    if b and b["status"] == "requested" and mail["sender"] != AIRLINE_EMAIL.get((b["airline"] or "").lower()):
        b = None                                                 # mail booking: only the airline we asked confirms
    if not b:
        return db.event("confirmation_unmatched", mail["thread_id"], mail["id"], subject=mail["subject"])
    if AIRLINE_NO.search(text):                                  # "Booking BK-... cancelled: no capacity" is NOT a confirmation
        crm.upsert(b["thread_id"], status="cancelled_by_airline", raw={"airline_mail": text[:1500]})
        db.update_session(b["thread_id"], status="needs_human",
                          note="AIRLINE CANCELLED/REFUSED the booking: rebook and tell the customer. Airline: %s" % text.replace("\n", " ")[:400])
        return db.event("booking_cancelled_by_airline", b["thread_id"], mail["id"], sender=mail["sender"],
                        booking_reference=ref and ref.group(0))
    if b["status"] == "confirmed":
        return db.event("confirmation_duplicate", b["thread_id"], mail["id"])
    crm.upsert(b["thread_id"], status="confirmed", confirmed_at=time.time(),
               booking_reference=b["booking_reference"] or (ref and ref.group(0)))
    waiting = db.session(b["thread_id"])
    if waiting and waiting["status"] == "reprice_proposed":      # the customer has not agreed to the new price yet
        return db.event("booking_confirmed", b["thread_id"], mail["id"], booking_reference=ref and ref.group(0),
                        held="customer has not confirmed the new price")
    db.update_session(b["thread_id"], status="confirmed")
    db.event("booking_confirmed", b["thread_id"], mail["id"], booking_reference=ref and ref.group(0))
    _tell_customer(crm.get(b["thread_id"]), "confirmed")
