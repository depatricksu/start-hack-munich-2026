"""Task 04: book by rate ID when the customer accepts, and keep the customer informed.

Two handlers, registered in core/main.py HANDLERS:
  follow_up             customer answers our quote: accept -> book -> tell the customer
  booking_confirmation  "Booking BK-... confirmed" from the airline -> mark confirmed -> tell the customer

No LLM call here: acceptance is read with rules (an extra gateway call would raise our cost per quote).
Anything unclear goes to needs_human, never a guess.

Booking paths:
  portal airline (option has rate_id) -> POST /v1/portal/bookings. Rate expired (410) -> fresh rate, book that.
  sheet airline (no rate_id)          -> booking request mail to the airline (address from carrier-list.csv).
"""
import csv, json, os, re, time
from decimal import Decimal
from core import config, db, mailbox
from . import crm

_KIT = os.path.join(config.ROOT, "kit", "start-kit")
AIRLINE_EMAIL = {r["name"].lower(): r["email"] for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv")))
                 if r["kind"] == "airline"}
# A fresh rate may cost more than what we quoted. Above this we do not book on our own.
MAX_REPRICE = Decimal(os.environ.get("BOOK_MAX_REPRICE", "1.05"))

ACCEPT = re.compile(r"\b(accept\w*|book (it|this|that|the)|please book|go ahead|confirm(ed)?|agreed|deal|"
                    r"sounds good|let'?s do it|approved?|ja\b|buchen|bitte buchen|einverstanden|passt|auftrag|"
                    r"bestätig\w*|d'accord|réserv\w*|acepto|reserv\w*|confermo|prenot\w*)", re.I)
DECLINE = re.compile(r"\b(no,? thanks?|decline\w*|too expensive|not interested|cancel\w*|we pass|"
                     r"nein|zu teuer|kein interesse|absagen|storn\w*|non merci|no gracias)\b", re.I)
QUESTION = re.compile(r"\?|\b(could you|can you|what about|instead|cheaper|faster|change|könnten sie|anders)\b", re.I)
BK = re.compile(r"\bBK-[A-Za-z0-9]{6,12}\b")
TEAM_REF = re.compile(r"\bGOOGLE-\d+\b")

TEXT = {
    "booked": {
        "en": "Hi,\n\nthank you for your order. Your shipment {ROUTE} is booked with {AIRLINE} at {PRICE} all-in, "
              "our booking reference is {REF}. We will let you know as soon as the airline has confirmed it.\n\n"
              "Best regards\nYour forwarding team",
        "de": "Hallo,\n\nvielen Dank für Ihren Auftrag. Ihre Sendung {ROUTE} ist bei {AIRLINE} zum Gesamtpreis von {PRICE} "
              "gebucht, unsere Buchungsnummer ist {REF}. Sobald die Airline bestätigt hat, melden wir uns.\n\n"
              "Viele Grüße\nIhr Forwarding-Team"},
    "requested": {
        "en": "Hi,\n\nthank you for your order. We have sent the booking for {ROUTE} to {AIRLINE} at {PRICE} all-in "
              "(our reference {REF}). You will hear from us as soon as it is confirmed.\n\nBest regards\nYour forwarding team",
        "de": "Hallo,\n\nvielen Dank für Ihren Auftrag. Die Buchung {ROUTE} zum Gesamtpreis von {PRICE} ist bei {AIRLINE} "
              "angefragt (unsere Referenz {REF}). Sobald sie bestätigt ist, melden wir uns.\n\nViele Grüße\nIhr Forwarding-Team"},
    "confirmed": {
        "en": "Hi,\n\ngood news: {AIRLINE} has confirmed your shipment {ROUTE}, booking {REF}. It is booked and ready to "
              "ship, expected transit {TRANSIT} days. Just reply here if you want a status update.\n\n"
              "Best regards\nYour forwarding team",
        "de": "Hallo,\n\ngute Nachrichten: {AIRLINE} hat Ihre Sendung {ROUTE} bestätigt, Buchung {REF}. Sie ist gebucht und "
              "versandbereit, voraussichtliche Laufzeit {TRANSIT} Tage. Für einen Status antworten Sie einfach hier.\n\n"
              "Viele Grüße\nIhr Forwarding-Team"},
}


def classify(body):
    """accept / decline / unclear. Only the customer's new text counts, not our quoted mail below it."""
    text = re.split(r"\n\s*(>|On .+wrote:|Am .+schrieb)", body or "", maxsplit=1)[0]
    if DECLINE.search(text):
        return "decline"
    if ACCEPT.search(text) and not QUESTION.search(text):
        return "accept"
    return "unclear"


def _say(kind, lang, b):
    t = TEXT[kind].get(lang) or TEXT[kind]["en"]
    return (t.replace("{ROUTE}", "%s to %s" % (b["origin"], b["destination"]) if lang != "de"
                      else "%s nach %s" % (b["origin"], b["destination"]))
            .replace("{AIRLINE}", b["airline"] or "").replace("{PRICE}", "%s %s" % (b["price"], b["currency"]))
            .replace("{REF}", b.get("booking_reference") or b["team_reference"])
            .replace("{TRANSIT}", str(b.get("transit_days") or "")))


def _tell_customer(b, kind):
    subject = b["subject"] if (b["subject"] or "").lower().startswith("re:") else "Re: " + (b["subject"] or "")
    ok = mailbox.send(b["customer"], subject, _say(kind, b.get("language") or "en", b),
                      in_reply_to=b["last_customer_mail_id"], thread_id=b["thread_id"])
    db.event("customer_informed" if ok else "customer_inform_failed", b["thread_id"], message=kind)
    return ok


def _needs_human(tid, mail_id, why):
    db.update_session(tid, status="needs_human", note=why)
    db.event("needs_human", tid, mail_id, why=why)


def _fresh_rate(chosen, fields):
    status, r = mailbox.api("GET", "/v1/portal/rates", params={
        "origin": chosen["origin"], "destination": chosen["destination"],
        "airline": chosen.get("airline_code") or chosen["airline"],
        "weight_kg": fields.get("weight_kg_total") or fields.get("weight_kg"),
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
            if Decimal(fresh["total"]) > Decimal(chosen["total"]) * MAX_REPRICE:
                return "fail", "fresh rate %s %s is above our quote %s" % (fresh["total"], fresh["currency"], chosen["total"])
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


def handle_follow_up(mail):
    tid = mail["thread_id"]
    s = db.session(tid)
    if not s or s["status"] not in ("quoted",):
        return db.event("follow_up_ignored", tid, mail["id"], status=s and s["status"])
    verdict = classify(mail["body"])
    db.event("follow_up", tid, mail["id"], verdict=verdict)
    if verdict == "decline":
        return db.update_session(tid, status="lost", note="customer declined")
    if verdict == "unclear":
        return _needs_human(tid, mail["id"], "customer answered the quote, not a clear yes or no")

    chosen, fields = json.loads(s["chosen"]), json.loads(s["fields"] or "{}")
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
    text = mail["subject"] + "\n" + mail["body"]
    ref, team = BK.search(text), TEAM_REF.search(text)
    b = crm.find(ref and ref.group(0), team and team.group(0))
    if not b:
        return db.event("confirmation_unmatched", mail["thread_id"], mail["id"], subject=mail["subject"])
    if b["status"] == "confirmed":
        return db.event("confirmation_duplicate", b["thread_id"], mail["id"])
    crm.upsert(b["thread_id"], status="confirmed", confirmed_at=time.time(),
               booking_reference=b["booking_reference"] or (ref and ref.group(0)))
    db.update_session(b["thread_id"], status="confirmed")
    db.event("booking_confirmed", b["thread_id"], mail["id"], booking_reference=ref and ref.group(0))
    _tell_customer(crm.get(b["thread_id"]), "confirmed")
