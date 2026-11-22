"""Several shipments in one quote: the customer books one, some or all of them.

5U sends this about once an hour (requests 25791, 26215, 33297, 37892): two shipments, one reply with a price for
each, then "Both prices work for us. Please go ahead and book the first shipment now; we will confirm the second
shipment later." Until 22 Nov 04:46 the clerk read that as unclear and left it for a person, and a script outside the
clerk booked the named shipment. Now the clerk does it:

  wanted()          which shipments the customer wants booked NOW (rules, no model call)
  on_quote()        the answer to the quote: book those, one reply, the others stay on hold in the same session
  after_booking()   a later mail ("we can now confirm the second shipment, please book it"): book what was on hold
  confirmation()    the airline confirms a shipment that is not the thread's CRM row (the CRM has one row per thread)

Each shipment is booked with its own rate_id and its own team reference GOOGLE-<thread>-<n>. A plain yes that names
no shipment books all of them. Anything that is not a clear "book this one now" books nothing. A shipment of a sheet
airline (no rate_id) is booked by mail when it is the first booking of the thread, otherwise it goes to a person.
"""
import json, re, time
from core import db, mailbox
from . import crm

CLAUSE = re.compile(r"[.;!?\n,]")                         # "book the first now, the second we confirm later": two clauses
BOOK = re.compile(r"\b(book|go ahead|proceed|buchen|confirm)\b", re.I)   # the verb: not "booking", "booked", "confirming"
LATER = re.compile(r"\b(later|not yet|hold|wait|sp[äa]ter|noch nicht|will confirm|we'll confirm|we will confirm)\b", re.I)
NO = re.compile(r"\b(don't|do not|not|cancel\w*|nicht|storn\w*)\b", re.I)
THANKS = re.compile(r"\b(thanks|thank you|danke|glad)\b", re.I)
ORDINAL = ((1, re.compile(r"\b(?:first|1st|shipment 1|sendung 1|erste\w*)\b|#1\b", re.I)),
           (2, re.compile(r"\b(?:second|2nd|shipment 2|sendung 2|zweite\w*)\b|#2\b", re.I)),
           (3, re.compile(r"\b(?:third|3rd|shipment 3|sendung 3|dritte\w*)\b|#3\b", re.I)))
ALL = re.compile(r"\b(both|all|beide\w*|alle)\b", re.I)
REST = re.compile(r"\b(remaining|other|outstanding|[üu]brige\w*|andere\w*|restliche\w*)\b", re.I)
CITY = re.compile(r"\b([A-Z]{3})\s*\(([^(),\n]{3,40}),")                  # "To SGN (Ho Chi Minh City, VN)" in the request

TXT = {
    "en": dict(hi="Hi %s,", hi0="Hello,", thanks="Thank you.",
               booked="Shipment %d is booked: %s to %s with %s, booking %s, %s EUR all-in as quoted.",
               requested="Shipment %d (%s to %s with %s, %s EUR all-in as quoted) is with the airline for booking.",
               conf="I will send you the airline's confirmation as soon as it is in.",
               hold="Shipment %d (%s to %s, %s EUR all-in with %s) is on hold for you. Just tell me when you want it booked.",
               confirmed="Good news: the airline has confirmed booking %s for shipment %d (%s to %s with %s). Everything is set on our side.",
               bye="Best regards\n%s\nAir Export"),
    "de": dict(hi="Hallo %s,", hi0="Guten Tag,", thanks="Vielen Dank.",
               booked="Sendung %d ist gebucht: %s nach %s mit %s, Buchung %s, %s EUR all-in wie angeboten.",
               requested="Sendung %d (%s nach %s mit %s, %s EUR all-in wie angeboten) liegt zur Buchung bei der Airline.",
               conf="Die Bestätigung der Airline schicke ich Ihnen, sobald sie da ist.",
               hold="Sendung %d (%s nach %s, %s EUR all-in mit %s) halte ich für Sie bereit. Sagen Sie mir einfach, wann ich sie buchen soll.",
               confirmed="Gute Nachrichten: Die Airline hat die Buchung %s für Sendung %d (%s nach %s mit %s) bestätigt. Von unserer Seite ist alles vorbereitet.",
               bye="Viele Grüße\n%s\nLuftfracht Export"),
}


def _open(p):
    return not p.get("booking_reference") and not p.get("requested")


def open_parts(s):
    """True when the session's quote has several shipments and at least one is not booked yet."""
    try:
        return any(_open(p) for p in (json.loads(s["chosen"] or "null") or {}).get("parts") or [])
    except (TypeError, ValueError, AttributeError):
        return False


def number(chosen, fields):
    """The shipments of the quote, each with its number, weight, volume and flight price (older quotes lack them)."""
    from pricing import multi
    ships = fields.get("shipments") or []
    for i, p in enumerate(chosen.get("parts") or [], 1):
        w, v = multi._totals(ships[i - 1]) if i <= len(ships) else (0.0, 0.0)
        p.setdefault("n", i)
        if p.get("kg") is None:
            p["kg"] = w
        if p.get("cbm") is None:
            p["cbm"] = v
        if not p.get("flight_total"):                        # no trucker and no insurance on it: the price is the flight
            p["flight_total"] = str(p.get("total_eur") or p["total"])
    return chosen.get("parts") or []


def names(tid, parts):
    """What the customer may call a shipment besides its number: the destination code, and the city the request gave."""
    row = db.con().execute("SELECT body FROM mails WHERE id=?", (tid,)).fetchone()
    city = {m.group(1): m.group(2).strip() for m in CITY.finditer((row["body"] if row else "") or "")}
    return {p["n"]: [x for x in (p.get("destination"), city.get(p.get("destination"))) if x] for p in parts}


def _named(clause, parts, called):
    out = {n for n, rx in ORDINAL if rx.search(clause)}
    if ALL.search(clause):
        out |= {p["n"] for p in parts}
    if REST.search(clause):                                  # "the remaining shipment", "the other one"
        out |= {p["n"] for p in parts if _open(p)}
    for n, words in (called or {}).items():
        for w in words:
            if re.search(r"\b%s\b" % re.escape(w), clause, 0 if len(w) == 3 and w.isupper() else re.I):   # codes: as written
                out.add(n)
    return out & {p["n"] for p in parts}


def mentions(text, parts, called=None):
    return bool(_named((text or "").replace("’", "'"), parts, called))


def wanted(text, parts, called=None):
    """The numbers of the shipments the customer asks us to book NOW. 'We will confirm the second one later' takes that
    one out, also when an earlier sentence said 'both prices work for us'. Booked shipments are never returned."""
    now, later, prev = set(), set(), set()
    for clause in CLAUSE.split((text or "").replace("’", "'")):
        named = _named(clause, parts, called)
        if LATER.search(clause) or NO.search(clause):
            later |= named
            prev = set()
        elif THANKS.search(clause) and not BOOK.search(clause):          # "Thanks for confirming the SGN booking"
            prev = set()
        else:
            if BOOK.search(clause):
                now |= named or prev     # "We can now confirm the second shipment. Please go ahead and book it."
            if named:
                prev = named
    return sorted(n for n in now - later if any(p["n"] == n and _open(p) for p in parts))


def _lang(fields):
    return "de" if (fields.get("language") or "").lower().startswith("de") else "en"


def _book(s, mail, chosen, fields, want):
    """Book the wanted shipments, tell the customer once, keep the others on hold. Always leaves a clear session."""
    from . import handlers
    tid, parts, T = s["thread_id"], chosen["parts"], TXT[_lang(fields)]
    db.event("shipments_to_book", tid, mail["id"], wanted=want, of=len(parts))
    done, failed = [], []
    for p in [x for x in parts if x["n"] in want and _open(x)]:
        pf = {"weight_kg_total": p["kg"], "volume_cbm_total": p["cbm"]}
        base = dict(customer=s["customer"], subject=s["subject"], last_customer_mail_id=mail["id"], airline=p["airline"],
                    airline_code=p.get("airline_code"), origin=p["origin"], destination=p["destination"], weight_kg=p["kg"],
                    volume_cbm=p["cbm"], transit_days=p.get("transit_days"), price=p["total"],
                    currency=p.get("currency") or "EUR", source=p.get("source"), language=fields.get("language") or "en",
                    rate_id=p.get("rate_id"))
        first = not crm.get(tid)                             # the CRM row (tracking, airline confirmation) is the first booking
        if p.get("rate_id"):
            result, r = handlers.book_portal(tid, p, pf, reference="%s-%d" % (crm.team_reference(tid), p["n"]))
            if result != "booked":
                failed.append("shipment %d (%s) could not be booked: %s" % (p["n"], p["destination"], str(r)[:160]))
                continue
            p["booking_reference"], p["booked_price"] = r["booking_reference"], str(r.get("price"))
            if first:
                crm.upsert(tid, status="booked", booking_reference=r["booking_reference"], booked_at=time.time(),
                           raw=dict(r, part=p["n"], of=len(parts)), **dict(base, rate_id=r.get("rate_id") or base["rate_id"]))
            db.update_session(tid, chosen=chosen)            # the reference is saved before anything else can fail
            db.event("booked", tid, mail["id"], part=p["n"], booking_reference=r["booking_reference"], price=str(r.get("price")))
            if handlers.booked_above_quote(p, r):            # never tell the customer "as quoted" at a higher price
                failed.append("shipment %d (%s) booked %s ABOVE the quoted flight price (%s vs %s): ask the customer" % (
                    p["n"], p["destination"], r["booking_reference"], r.get("price"), p["flight_total"]))
            else:
                done.append(p)
        elif first and handlers.request_by_mail(tid, p, pf):
            p["requested"] = time.time()
            crm.upsert(tid, status="requested", raw={"part": p["n"], "of": len(parts)}, **base)
            db.update_session(tid, chosen=chosen)
            db.event("booking_requested", tid, mail["id"], part=p["n"], airline=p["airline"])
            done.append(p)
        else:
            failed.append("shipment %d (%s) is with sheet airline %s: book it by mail" % (p["n"], p["destination"], p["airline"]))
    hold = [p for p in parts if _open(p)]
    if done:
        name = fields.get("customer_first_name")
        lines = [T["hi"] % name if name else T["hi0"], T["thanks"] + " " + " ".join(
            (T["booked"] % (p["n"], p["origin"], p["destination"], p["airline"], p["booking_reference"], p["total"]))
            if p.get("booking_reference") else (T["requested"] % (p["n"], p["origin"], p["destination"], p["airline"], p["total"]))
            for p in done) + " " + T["conf"]]
        lines += [T["hold"] % (p["n"], p["origin"], p["destination"], p["total"], p["airline"]) for p in hold if p["n"] not in want]
        handlers._reply_session(s, mail, "\n\n".join(lines + [T["bye"] % handlers.SIGNER_NAME()]), "shipments_booked")
    note = "BOOKED: %s. ON HOLD (booked when the customer says so): %s" % (
        "; ".join("shipment %d %s %s" % (p["n"], p["destination"], p.get("booking_reference") or "requested by mail")
                  for p in parts if not _open(p)) or "nothing",
        "; ".join("shipment %d %s %s EUR" % (p["n"], p["destination"], p["total"]) for p in hold) or "nothing")
    if failed:
        return handlers._needs_human(tid, mail["id"], "; ".join(failed) + " | " + note)
    status = "booked" if any(p.get("booking_reference") for p in parts) else "booking_requested"
    db.update_session(tid, status=status, note=note)
    return True


def on_quote(s, mail, verdict):
    """The customer's answer to a quote with several shipments. Always decides: books, or leaves it with the reason."""
    from . import handlers
    tid = s["thread_id"]
    chosen, fields = (json.loads(s["chosen"] or "null") or {}), json.loads(s["fields"] or "{}")
    parts = number(chosen, fields)
    text = handlers.own_text(mail["body"], mail.get("subject"))
    called = names(tid, parts)
    want = wanted(text, parts, called)
    if not want and verdict in ("accept", "sending_docs") and not mentions(text, parts, called):
        want = [p["n"] for p in parts if _open(p)]           # a plain "yes, please book it": all of them
    if not want:
        return handlers._needs_human(tid, mail["id"], handlers.UNCLEAR_NOTE)
    return _book(s, mail, chosen, fields, want)


def after_booking(s, mail):
    """A later customer mail on a thread with a shipment still on hold. True = it asked for one and we handled it."""
    from . import handlers
    chosen, fields = (json.loads(s["chosen"] or "null") or {}), json.loads(s["fields"] or "{}")
    parts = number(chosen, fields)
    want = wanted(handlers.own_text(mail["body"], mail.get("subject")), parts, names(s["thread_id"], parts))
    if not want:
        return False
    _book(s, mail, chosen, fields, want)
    return True


def confirmation(mail, ref):
    """'Booking BK-... confirmed' for a shipment that is not the thread's CRM row: mark it and tell the customer."""
    s = chosen = p = None
    for row in db.con().execute("SELECT thread_id FROM sessions WHERE chosen LIKE ?", ("%" + ref + "%",)).fetchall():
        s = db.session(row["thread_id"])
        chosen = (json.loads(s["chosen"] or "null") or {})
        p = next((x for x in chosen.get("parts") or [] if x.get("booking_reference") == ref), None)
        if p:
            break
    if not p:
        return False
    from . import handlers
    tid, fields = s["thread_id"], json.loads(s["fields"] or "{}")
    if p.get("confirmed"):
        db.event("confirmation_duplicate", tid, mail["id"])
        return True
    p["confirmed"] = time.time()
    db.update_session(tid, chosen=chosen)
    db.event("booking_confirmed", tid, mail["id"], booking_reference=ref, part=p.get("n"))
    last = db.con().execute("SELECT id FROM mails WHERE thread_id=? AND lower(sender)=? ORDER BY id DESC LIMIT 1",
                            (tid, (s["customer"] or "").lower())).fetchone()
    T, name = TXT[_lang(fields)], fields.get("customer_first_name")
    body = "\n\n".join([T["hi"] % name if name else T["hi0"],
                        T["confirmed"] % (ref, p.get("n") or 0, p["origin"], p["destination"], p["airline"]),
                        T["bye"] % handlers.SIGNER_NAME()])
    subject = s["subject"] if (s["subject"] or "").lower().startswith("re:") else "Re: " + (s["subject"] or "")
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=last["id"] if last else tid, thread_id=tid)
    db.event("customer_informed" if ok else "customer_inform_failed", tid, mail["id"], message="shipment_confirmed")
    if s["status"] == "booked" and (crm.get(tid) or {}).get("status") == "confirmed":
        db.update_session(tid, status="confirmed")
    return True
