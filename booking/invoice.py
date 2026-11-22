"""Cash flow: invoice the day the airline confirms, remind politely when it is overdue. Owner: Patrick.

Why: a forwarder pays the airline and the trucker in 7-30 days but the customer pays in 45-90. Every day an invoice
is late or forgotten is the forwarder's own money. Today it is written by hand, often days after the flight.

    python3 -m booking.invoice              # receivables: open, overdue (biggest first), paid, per customer
    python3 -m booking.invoice --paid 1234  # the forwarder saw the money: mark invoice INV-1234 (or thread 1234) paid
    python3 -m booking.invoice --run        # own Terminal on the runner: payment reminders every INVOICE_TICK_S

Flow
  airline confirms   booking/handlers.py calls issue(thread): invoice INV-<thread> with the agreed all-in price,
                     the flight and truck lines, our references, due in PAYMENT_TERMS_DAYS. Mailed (with a PDF) only
                     when INVOICE_MAIL=1; otherwise stored as a ready draft (status open, sent=0) for the forwarder.
  overdue            tick(): one reminder every REMINDER_EVERY_DAYS, at most MAX_REMINDERS; after that the invoice is
                     `overdue_human` (a person calls the customer) and event `invoice_overdue_human` is logged.
  customer writes    "we have paid / überwiesen" -> `paid_reported` + a short thank-you, no more reminders
                     (the forwarder still confirms with --paid when the money is in the account);
                     "please send the invoice" -> the invoice again, in the thread (not a red case any more).
                     "the invoice is wrong" is NOT handled here: it stays a human case.
  cancelled          customer or airline cancels -> the invoice is cancelled, no reminders.

Safety: nothing here changes a quote or a booking. With INVOICE_MAIL=0 (default) no new mail goes to customers, except
the invoice copy a customer asks for themselves.
"""
import json, os, re, sys, time
from decimal import Decimal, InvalidOperation

from core import db, mailbox
from . import crm

INVOICE_MAIL = os.environ.get("INVOICE_MAIL", "0") == "1"
TERMS_DAYS = float(os.environ.get("PAYMENT_TERMS_DAYS", "30"))
REMINDER_EVERY_DAYS = float(os.environ.get("REMINDER_EVERY_DAYS", "7"))
MAX_REMINDERS = int(os.environ.get("MAX_REMINDERS", "2"))
TICK_S = float(os.environ.get("INVOICE_TICK_S", "60"))
DAY = 86400.0

SCHEMA = """CREATE TABLE IF NOT EXISTS invoices(thread_id INTEGER PRIMARY KEY, number TEXT UNIQUE, customer TEXT,
  subject TEXT, amount TEXT, currency TEXT, lines TEXT, language TEXT, issued_at REAL, due_at REAL, status TEXT,
  sent INTEGER DEFAULT 0, reminders INTEGER DEFAULT 0, last_reminder_at REAL, paid_at REAL, body TEXT, note TEXT);"""
OPEN = ("open", "overdue_human")

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
SEND_INVOICE = re.compile(
    r"\b((?:send|resend|forward|share|need|want|get|provide|mail|email|e-mail|receive)\w* (?:\w+ ){0,4}"
    r"(?:invoice|bill)|(?:invoice|bill) (?:please|again|copy)|copy of (?:the |your |our )?invoice|"
    r"where is (?:the|your|our) invoice|rechnung (?:bitte|senden|schicken|zusenden)|"
    r"(?:senden|schicken|zusenden)\w* (?:\w+ ){0,4}rechnung|bitte (?:um )?(?:die )?rechnung)\b", re.I)
DISPUTE = re.compile(r"\b(wrong|incorrect|mistake|error|too high|overcharg\w*|dispute\w*|doesn't match|does not match|"
                     r"not agreed|falsch|fehler|zu hoch|stimmt nicht|reklamier\w*)\b", re.I)

TEXT = {
    "en": {
        "invoice": "Hi {name},\n\nthank you for your booking. The airline has confirmed it, so here is our invoice "
                   "{number} for {ref}:\n\n{lines}\n\nTotal: {amount} {cur}\nDue: {due} ({days} days)\n\n"
                   "Please quote {number} with your payment. The invoice is attached as a PDF.\n\nBest regards\n{signer}\nAir Export",
        "reminder": "Hi {name},\n\na friendly reminder: our invoice {number} for {ref} over {amount} {cur} was due on {due} and "
                    "we have not received the payment yet. If it is already on its way, please ignore this mail. "
                    "Otherwise we would be grateful for the transfer in the next days, quoting {number}.\n\n"
                    "Best regards\n{signer}\nAir Export",
        "paid": "Hi {name},\n\nthank you for letting us know. We will match the payment for invoice {number} with our "
                "account and will only get back to you if anything is unclear.\n\nBest regards\n{signer}\nAir Export",
        "copy": "Hi {name},\n\nof course, here is invoice {number} for {ref} again:\n\n{lines}\n\nTotal: {amount} {cur}\n"
                "Due: {due}\n\nBest regards\n{signer}\nAir Export",
    },
    "de": {
        "invoice": "Hallo {name},\n\nvielen Dank für Ihre Buchung. Die Airline hat sie bestätigt, anbei unsere Rechnung "
                   "{number} für {ref}:\n\n{lines}\n\nGesamt: {amount} {cur}\nFällig: {due} ({days} Tage)\n\n"
                   "Bitte geben Sie bei der Zahlung {number} an. Die Rechnung hängt als PDF an.\n\nViele Grüße\n{signer}\nLuftfracht Export",
        "reminder": "Hallo {name},\n\neine freundliche Erinnerung: unsere Rechnung {number} für {ref} über {amount} {cur} war am "
                    "{due} fällig, die Zahlung ist bei uns noch nicht eingegangen. Falls sie schon unterwegs ist, "
                    "betrachten Sie diese Mail bitte als gegenstandslos. Sonst freuen wir uns über die Überweisung in den "
                    "nächsten Tagen, mit Angabe von {number}.\n\nViele Grüße\n{signer}\nLuftfracht Export",
        "paid": "Hallo {name},\n\nvielen Dank für die Info. Wir ordnen die Zahlung zu Rechnung {number} zu und melden uns "
                "nur, falls etwas unklar ist.\n\nViele Grüße\n{signer}\nLuftfracht Export",
        "copy": "Hallo {name},\n\ngern, hier noch einmal Rechnung {number} für {ref}:\n\n{lines}\n\nGesamt: {amount} {cur}\n"
                "Fällig: {due}\n\nViele Grüße\n{signer}\nLuftfracht Export",
    },
}


def con():
    c = db.con()
    c.executescript(SCHEMA)
    return c


def get(thread_id):
    r = con().execute("SELECT * FROM invoices WHERE thread_id=?", (thread_id,)).fetchone()
    return dict(r) if r else None


def _dec(x):
    try:
        return Decimal(str(x)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _lang(x):
    return "de" if (x or "").lower().startswith("de") else "en"


def _signer():
    from llm.extract import SIGNER
    return SIGNER


def _date(ts, lang):
    return time.strftime("%d.%m.%Y" if lang == "de" else "%d %b %Y", time.localtime(ts))


def _lines(chosen, b, lang):
    """Freight (and the truck leg when there is one), from the agreed quote."""
    total = _dec(chosen.get("total")) or _dec(b.get("price"))
    cur = chosen.get("currency") or b.get("currency") or "EUR"
    route = "%s-%s" % (chosen.get("origin") or b.get("origin") or "?", chosen.get("destination") or b.get("destination") or "?")
    airline = chosen.get("airline") or b.get("airline") or "airline"
    out = []
    truck, flight = _dec(chosen.get("trucker_total")), _dec(chosen.get("flight_total"))
    if truck and flight and chosen.get("trucker_currency", cur) == cur and chosen.get("flight_currency", cur) == cur \
            and truck + flight == total:
        out.append(("Air freight %s, %s, all-in" % (route, airline) if lang == "en" else
                    "Luftfracht %s, %s, all-in" % (route, airline), flight))
        out.append(("Pickup by truck (%s)" % chosen.get("trucker") if lang == "en" else
                    "Abholung per LKW (%s)" % chosen.get("trucker"), truck))
    else:
        out.append(("Air freight %s, %s, all-in" % (route, airline) if lang == "en" else
                    "Luftfracht %s, %s, all-in" % (route, airline), total))
    return [(t, str(v)) for t, v in out], (str(total) if total is not None else None), cur


def _fill(kind, inv, s_row=None):
    lang = inv["language"] or "en"
    lines = json.loads(inv["lines"] or "[]")
    cur = inv["currency"]
    return TEXT[lang][kind].format(
        name=inv.get("_name") or ("there" if lang == "en" else "zusammen"), number=inv["number"],
        ref=inv.get("_ref") or inv["number"], amount=inv["amount"], cur=cur,
        lines="\n".join("- %s: %s %s" % (t, v, cur) for t, v in lines),
        due=_date(inv["due_at"], lang), days=int(round((inv["due_at"] - inv["issued_at"]) / DAY)), signer=_signer())


def _refs(thread_id, b):
    ref = crm.team_reference(thread_id)
    if b and b.get("booking_reference"):
        ref += ", booking %s" % b["booking_reference"]
    return ref


def _pdf(inv, body):
    try:
        from core import offer_file
        lines = ["INVOICE %s" % inv["number"], "", body]
        text = [x for part in lines for x in part.split("\n")]
        return [{"filename": "%s.pdf" % inv["number"], "content_type": "application/pdf",
                 "content_base64": __import__("base64").b64encode(offer_file.pdf(text)).decode()}]
    except Exception as e:
        db.event("invoice_pdf_error", inv["thread_id"], error=str(e))
        return None


def _send(inv, body, in_reply_to, what, attach=False):
    subject = inv["subject"] if (inv["subject"] or "").lower().startswith("re:") else "Re: " + (inv["subject"] or "")
    ok = mailbox.send(inv["customer"], subject, body, in_reply_to=in_reply_to, thread_id=inv["thread_id"],
                      attachments=_pdf(inv, body) if attach else None)
    db.event("invoice_" + what + ("_sent" if ok else "_send_failed"), inv["thread_id"], number=inv["number"])
    return ok


def _view(inv):
    """The invoice row plus the bits only the mail needs (reference, greeting)."""
    b = crm.get(inv["thread_id"]) or {}
    from .replies import first_name
    try:
        name = first_name(inv["customer"] or "")
    except Exception:
        name = None
    return dict(inv, _ref=_refs(inv["thread_id"], b), _name=name)


def issue(thread_id, now=None):
    """Create the invoice for a confirmed booking (once). Mails it only when INVOICE_MAIL=1. Returns the row."""
    now = now or time.time()
    have = get(thread_id)
    if have:
        return have
    s, b = db.session(thread_id), crm.get(thread_id) or {}
    if not s or not b:
        return None
    chosen = json.loads(s["chosen"] or "{}")
    lang = _lang(b.get("language") or json.loads(s["fields"] or "{}").get("language"))
    lines, amount, cur = _lines(chosen, b, lang)
    if amount is None:
        db.event("invoice_skipped", thread_id, why="no agreed price")
        return None
    number = "INV-%s" % thread_id
    con().execute("INSERT OR IGNORE INTO invoices(thread_id,number,customer,subject,amount,currency,lines,language,"
                  "issued_at,due_at,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (thread_id, number, b.get("customer") or s["customer"], b.get("subject") or s["subject"], amount, cur,
                   json.dumps(lines), lang, now, now + TERMS_DAYS * DAY, "open"))
    inv = get(thread_id)
    body = _fill("invoice", _view(inv))
    con().execute("UPDATE invoices SET body=? WHERE thread_id=?", (body, thread_id))
    db.event("invoice_issued", thread_id, number=number, amount=amount, currency=cur, due_days=TERMS_DAYS,
             mailed=INVOICE_MAIL)
    if INVOICE_MAIL and _send(inv, body, b.get("last_customer_mail_id"), "issued", attach=True):
        con().execute("UPDATE invoices SET sent=1 WHERE thread_id=?", (thread_id,))
    return get(thread_id)


def cancel(thread_id, why):
    inv = get(thread_id)
    if inv and inv["status"] in OPEN + ("paid_reported",):
        con().execute("UPDATE invoices SET status='cancelled', note=? WHERE thread_id=?", (why, thread_id))
        db.event("invoice_cancelled", thread_id, number=inv["number"], why=why)


def mark_paid(key, now=None):
    """The forwarder saw the money. key: 'INV-123', '123' (thread). Returns the invoice or None."""
    k = str(key).upper().replace("INV-", "")
    inv = get(int(k)) if k.isdigit() else None
    if not inv:
        return None
    con().execute("UPDATE invoices SET status='paid', paid_at=? WHERE thread_id=?", (now or time.time(), inv["thread_id"]))
    db.event("invoice_paid", inv["thread_id"], number=inv["number"], amount=inv["amount"])
    return get(inv["thread_id"])


def on_customer_mail(s, mail, text):
    """A customer mail after the booking. True when it was about the invoice and is fully handled here."""
    inv = get(s["thread_id"])
    if not inv or inv["status"] == "cancelled":
        return False
    if DISPUTE.search(text):
        return False                                             # "the invoice is wrong": a person handles it
    if PAID.search(text) and not NOT_PAID.search(text):
        if inv["status"] != "paid":
            con().execute("UPDATE invoices SET status='paid_reported', paid_at=? WHERE thread_id=?",
                          (time.time(), inv["thread_id"]))
        db.event("invoice_paid_reported", s["thread_id"], mail["id"], number=inv["number"])
        _send(inv, _fill("paid", _view(inv)), mail["id"], "thanks")
        return True
    if SEND_INVOICE.search(text) and not re.search(r"\b(air ?waybill|awb|pod|proof of delivery|frachtbrief)\b", text, re.I):
        if _send(inv, _fill("copy", _view(inv)), mail["id"], "copy", attach=True):
            con().execute("UPDATE invoices SET sent=1 WHERE thread_id=?", (inv["thread_id"],))
        return True
    return False


def tick(now=None):
    """Overdue invoices: a reminder every REMINDER_EVERY_DAYS (mailed only with INVOICE_MAIL=1), then a person."""
    now = now or time.time()
    done = []
    for r in con().execute("SELECT * FROM invoices WHERE status='open' AND due_at < ?", (now,)).fetchall():
        inv = dict(r)
        last = inv["last_reminder_at"] or inv["due_at"]
        if inv["reminders"] and now - last < REMINDER_EVERY_DAYS * DAY:
            continue
        if inv["reminders"] >= MAX_REMINDERS:
            con().execute("UPDATE invoices SET status='overdue_human' WHERE thread_id=?", (inv["thread_id"],))
            db.event("invoice_overdue_human", inv["thread_id"], number=inv["number"], amount=inv["amount"],
                     days_overdue=int((now - inv["due_at"]) // DAY), reminders=inv["reminders"])
            done.append((inv["number"], "overdue_human"))
            continue
        if INVOICE_MAIL:
            b = crm.get(inv["thread_id"]) or {}
            _send(inv, _fill("reminder", _view(inv)), b.get("last_customer_mail_id"), "reminder")
        con().execute("UPDATE invoices SET reminders=reminders+1, last_reminder_at=? WHERE thread_id=?",
                      (now, inv["thread_id"]))
        db.event("payment_reminder", inv["thread_id"], number=inv["number"], n=inv["reminders"] + 1, mailed=INVOICE_MAIL)
        done.append((inv["number"], "reminder %d" % (inv["reminders"] + 1)))
    return done


def receivables(now=None):
    """Totals and rows for the report and the dashboard: open, overdue (biggest first), paid, per customer."""
    now = now or time.time()
    rows = [dict(r) for r in con().execute("SELECT * FROM invoices ORDER BY due_at")]
    for r in rows:
        r["overdue_days"] = int((now - r["due_at"]) // DAY) if r["status"] in OPEN and now > r["due_at"] else 0
    eur = lambda rs: sum((_dec(r["amount"]) or 0) for r in rs if (r["currency"] or "EUR") == "EUR")
    openr = [r for r in rows if r["status"] in OPEN]
    overdue = sorted([r for r in openr if r["overdue_days"] > 0], key=lambda r: -(_dec(r["amount"]) or 0))
    by_cust = {}
    for r in openr:
        by_cust[r["customer"]] = by_cust.get(r["customer"], 0) + (_dec(r["amount"]) or 0)
    return {"open_eur": str(eur(openr)), "overdue_eur": str(eur(overdue)), "open": len(openr), "overdue": overdue,
            "paid_reported": [r for r in rows if r["status"] == "paid_reported"],
            "paid": len([r for r in rows if r["status"] == "paid"]),
            "by_customer": sorted(by_cust.items(), key=lambda x: -x[1]), "rows": rows}


def main(argv):
    if "--paid" in argv:
        inv = mark_paid(argv[argv.index("--paid") + 1])
        print("marked paid: %s %s %s" % (inv["number"], inv["amount"], inv["currency"]) if inv else "no such invoice")
        return
    if "--run" in argv:
        while True:
            for x in tick():
                print(time.strftime("%H:%M:%S"), *x, flush=True)
            time.sleep(TICK_S)
    r = receivables()
    print("Open: %d invoices, %s EUR | overdue: %d, %s EUR | paid: %d | customer says paid, check the bank: %d" % (
        r["open"], r["open_eur"], len(r["overdue"]), r["overdue_eur"], r["paid"], len(r["paid_reported"])))
    if r["overdue"]:
        print("\nOverdue, biggest first (call these):")
        for x in r["overdue"]:
            print("  %-12s %-40s %10s %s  %3d days  reminders %d  %s" % (x["number"], x["customer"][:40], x["amount"],
                                                                       x["currency"], x["overdue_days"], x["reminders"], x["status"]))
    if r["by_customer"]:
        print("\nOpen per customer:")
        for c, v in r["by_customer"][:15]:
            print("  %-40s %10s" % (c[:40], v))
    if r["paid_reported"]:
        print("\nCustomer says paid, confirm with --paid when the money is in:")
        for x in r["paid_reported"]:
            print("  %-12s %-40s %10s %s" % (x["number"], x["customer"][:40], x["amount"], x["currency"]))


if __name__ == "__main__":
    main(sys.argv[1:])
