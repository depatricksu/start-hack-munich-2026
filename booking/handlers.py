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
                     r"nein|kein interesse|absagen|storn\w*|anderen anbieter|non merci|no gracias)\b", re.I)
# A negated "go ahead / proceed / book" is a DECLINE, not an accept (live bug: "we will not go ahead" was booked).
NEGATED_PROCEED = re.compile(r"\b(won'?t|will not|would not|do(es)?\s*n'?t|did\s*n'?t|cannot|can'?t|"
                             r"not|never|decided (not|against)|rather not|prefer not|hold off|"
                             r"nicht|werden nicht|m[oö]chten? nicht)\b[^.?!]{0,40}?"
                             r"\b(go(ing)? ahead|proceed|book|order|confirm|move forward|buch\w*|fortfahren|best[aä]tig\w*)\b", re.I)
HEDGE = re.compile(r"\b(yet|still|for now|at the moment|right now|checking|review\w*|noch|momentan|gerade|pr[uü]f\w*)\b", re.I)
PRICE = re.compile(r"\b(cheaper|better price|best price|lower( the)? price|discount|too expensive|too high|negotiat\w*|"
                   r"budget|match|günstiger|rabatt|zu teuer|preis\w* (senken|nachlass|verhandeln)|moins cher|"
                   r"do (?:any |a bit |a little )?better|better (?:offer|rate|deal)|lower (?:rate|offer)|"
                   r"más barato|descuento|sconto)\b", re.I)
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
         r"document\w*[^.?!]{0,20}(marchandises dangereuses|peligros))")
_SEND = (r"(send|provide|forward|share|supply|pass (?:it |them |you )?along|get (?:you |it )?|"
         r"senden|schicken|nachreich\w*|zusenden|zukommen|envoy\w*|enviar\w*|invi\w*)")
SENDING_DOCS = re.compile(_SEND + r"[^.?!]{0,60}?" + _DOCS + r"|" + _DOCS + r"[^.?!]{0,60}?" + _SEND, re.I)


def classify(body):
    """accept / decline / better_price / sending_docs / unclear. Only the customer's new text counts, not our quoted mail below it."""
    text = re.split(r"\n\s*(>|On .+wrote:|Am .+schrieb)", body or "", maxsplit=1)[0]
    if DECLINE.search(text) or (NEGATED_PROCEED.search(text) and not HEDGE.search(text)):   # definitive "won't proceed" = decline; "not yet" = wait (unclear)
        return "decline"
    if PRICE.search(text):
        return "better_price"
    if ACCEPT.search(text) and not QUESTION.search(text) and not CONDITION.search(text) and not NEW_FACTS.search(text):
        return "accept"
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
    """Sheet airlines have no rate_id: send the airline a booking request."""
    to = AIRLINE_EMAIL.get((chosen["airline"] or "").lower())
    if not to:
        return False
    body = ("Hello,\n\nplease book the following air export shipment.\n\n"
            "Our reference: {ref}\nRoute: {o} - {d}\nWeight: {w} kg, volume {v} cbm\nRate: your tariff, all-in {p} {c}\n\n"
            "Please confirm with your booking reference.\n\nBest regards\nYour forwarding team").format(
        ref=crm.team_reference(tid), o=chosen["origin"], d=chosen["destination"],
        w=fields.get("weight_kg_total"), v=fields.get("volume_cbm_total"), p=chosen["total"], c=chosen["currency"])
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


def handle_follow_up(mail):
    tid = mail["thread_id"]
    s = db.session(tid)
    if s and s["status"] == "asked_customer":                    # answer to our clarifying question (llm/clarify.py)
        from llm import clarify
        return clarify.answer(mail)
    if not s or s["status"] not in ("quoted", "meeting_proposed", "awaiting_docs"):
        return db.event("follow_up_ignored", tid, mail["id"], status=s and s["status"])
    if mail["sender"] != (s["customer"] or "").lower():          # only the customer who asked can book on this quote
        return _needs_human(tid, mail["id"], "reply from %s, not from the customer %s" % (mail["sender"], s["customer"]))
    verdict = classify(mail["body"])
    db.event("follow_up", tid, mail["id"], verdict=verdict, status=s["status"])
    if s["status"] == "meeting_proposed" and verdict != "decline":   # "Tue 10:00, please confirm" is not a booking
        return _needs_human(tid, mail["id"], "customer answered our call offer (picked a time?): forwarder to follow up")
    if verdict == "decline":
        return db.update_session(tid, status="lost", note="customer declined")       # no mail, just closed
    if verdict == "better_price":
        return handle_better_price(s, mail)
    if s["status"] != "awaiting_docs":                   # on a quote still open, a soft/unclear reply does not book
        if verdict == "sending_docs":                    # "we'll send the DG papers" IS the yes for 5U (rounds 39-41 counted
            db.event("sending_docs_book_now", tid, mail["id"])   # accepted). Book NOW: the rate ID expires in ~15 min and a
            # second customer mail may never come (Kai's review of #36). The papers can follow the booking. (Riky)
        if verdict == "unclear":
            return _needs_human(tid, mail["id"], "customer answered the quote, not a clear yes or no")
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
        if result != "booked":
            crm.upsert(tid, status="failed", raw={"reason": r}, **base)
            return _needs_human(tid, mail["id"], r)
        crm.upsert(tid, status="booked", booking_reference=r["booking_reference"], booked_at=time.time(),
                   raw=r, **dict(base, rate_id=r.get("rate_id") or base["rate_id"]))
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
    if b["status"] == "confirmed":
        return db.event("confirmation_duplicate", b["thread_id"], mail["id"])
    crm.upsert(b["thread_id"], status="confirmed", confirmed_at=time.time(),
               booking_reference=b["booking_reference"] or (ref and ref.group(0)))
    db.update_session(b["thread_id"], status="confirmed")
    db.event("booking_confirmed", b["thread_id"], mail["id"], booking_reference=ref and ref.group(0))
    _tell_customer(crm.get(b["thread_id"]), "confirmed")
