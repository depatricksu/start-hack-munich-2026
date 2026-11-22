"""Invoice AFTER delivery, then payment tracking. Own table ops_invoices; the clerk's `invoices` is never touched.

    issued         delivery confirmed (POD / delivered): invoice made, mail to the customer is a DRAFT in the outbox
    overdue        due date passed: reminder drafts (first at due + 1 day, then every 7 days, at most 2)
    overdue_human  still unpaid after the last reminder + 7 days: note to the forwarder, no more reminders
    paid_reported  the customer wrote "we have paid": thank-you draft, reminders stop
    paid           the forwarder marked it paid (mark_paid)
    cancelled      the shipment was cancelled before delivery (no invoice is ever issued then)

The clock is passed in (`now`), so tests and the harness never wait.
"""
import json, os

from . import messages, state

DAY = 86400.0
TERMS_DAYS = float(os.environ.get("CARRIEROPS_TERMS_DAYS", "30"))
REMINDER_EVERY_DAYS = 7.0
MAX_REMINDERS = 2
OPEN = ("issued", "overdue", "overdue_human")


def get(con, thread_id):
    return state.one(con, "SELECT * FROM ops_invoices WHERE thread_id=?", (thread_id,))


def find(con, ref):
    """By invoice number (INV-41001) or thread id."""
    r = state.one(con, "SELECT * FROM ops_invoices WHERE number=?", (str(ref),))
    if r:
        return r
    try:
        return get(con, int(str(ref).replace("INV-", "")))
    except ValueError:
        return None


def issue(con, s, now):
    """Only called for a delivered shipment. Returns the invoice, or None if there already is one."""
    if s.get("status") != "delivered":
        raise ValueError("invoice only after delivery (status is %s)" % s.get("status"))
    if get(con, s["thread_id"]):
        return None
    lines = []
    if s.get("flight_quote"):
        lines.append(["Air freight %s-%s, %s, all-in" % (s["origin"], s["destination"], s["airline"]), s["flight_quote"]])
    if s.get("trucker") and s.get("trucker_quote"):
        lines.append(["Pickup by truck (%s)" % s["trucker"], s["trucker_quote"]])
    amount = s.get("quote_total") or ""
    if not lines:
        lines = [["Air freight %s-%s, %s, all-in" % (s["origin"], s["destination"], s["airline"]), amount]]
    inv = {"thread_id": s["thread_id"], "number": "INV-%s" % s["thread_id"], "customer": s["customer"], "amount": amount,
           "currency": s.get("currency") or "EUR", "lines": json.dumps(lines), "language": s.get("language"),
           "status": "issued", "issued_at": now, "due_at": now + TERMS_DAYS * DAY, "reminders": 0}
    con.execute("INSERT INTO ops_invoices(%s) VALUES(%s)" % (",".join(inv), ",".join("?" * len(inv))), list(inv.values()))
    subj, body = messages.customer_invoice(s, inv)
    oid = state.draft(con, s["thread_id"], "customer", s["customer"], subj, body, "invoice after delivery",
                      "invoice:%s" % s["thread_id"], now, s.get("last_customer_mail_id"), s.get("booking_ref"))
    con.execute("UPDATE ops_invoices SET outbox_id=? WHERE thread_id=?", (oid, s["thread_id"]))
    return get(con, s["thread_id"])


def tick(con, now):
    """Reminders for overdue invoices. Idempotent: run it as often as you like with the same `now`."""
    done = []
    for inv in state.rows(con, "SELECT * FROM ops_invoices WHERE status IN ('issued','overdue')"):
        s = state.shipment(con, inv["thread_id"]) or {"thread_id": inv["thread_id"], "customer": inv["customer"]}
        n = inv["reminders"] or 0
        last = inv["last_reminder_at"]
        if now < inv["due_at"] + DAY:
            continue
        if n < MAX_REMINDERS and (last is None or now >= last + REMINDER_EVERY_DAYS * DAY):
            n += 1
            subj, body = messages.customer_reminder(s, inv, n)
            state.draft(con, inv["thread_id"], "customer", inv["customer"], subj, body, "payment reminder %d" % n,
                        "reminder:%s:%d" % (inv["thread_id"], n), now, s.get("last_customer_mail_id"), s.get("booking_ref"))
            con.execute("UPDATE ops_invoices SET status='overdue', reminders=?, last_reminder_at=? WHERE thread_id=?",
                        (n, now, inv["thread_id"]))
            done.append((inv["number"], "reminder %d" % n))
        elif n >= MAX_REMINDERS and now >= (last or inv["due_at"]) + REMINDER_EVERY_DAYS * DAY:
            subj, body = messages.forwarder(s, "invoice %s still unpaid" % inv["number"], [
                "Invoice %s over %s %s was due %s days ago. %d reminders are in the outbox. Please call the customer."
                % (inv["number"], inv["amount"], inv["currency"], int((now - inv["due_at"]) / DAY), n)])
            state.draft(con, inv["thread_id"], "forwarder", "", subj, body, "invoice overdue after reminders",
                        "overdue_human:%s" % inv["thread_id"], now, booking_ref=s.get("booking_ref"))
            con.execute("UPDATE ops_invoices SET status='overdue_human' WHERE thread_id=?", (inv["thread_id"],))
            done.append((inv["number"], "overdue_human"))
    return done


def report_paid(con, s, now, mail_id=None):
    """The customer says they paid. -> 'paid_reported' | 'no_invoice' | current status (nothing to do)."""
    inv = get(con, s["thread_id"])
    if not inv:
        subj, body = messages.forwarder(s, "customer says paid, but no invoice yet", [
            "The customer wrote that they paid for %s, but carrierops has not issued an invoice (status %s)."
            % (s.get("our_ref"), s.get("status")), "Please check the payment by hand."])
        state.draft(con, s["thread_id"], "forwarder", "", subj, body, "paid before invoice", "paid_noinv:%s:%s" % (s["thread_id"], mail_id),
                    now, booking_ref=s.get("booking_ref"))
        return "no_invoice"
    if inv["status"] not in OPEN:
        return inv["status"]
    con.execute("UPDATE ops_invoices SET status='paid_reported', paid_reported_at=? WHERE thread_id=?", (now, s["thread_id"]))
    subj, body = messages.customer_paid_thanks(s, inv)
    state.draft(con, s["thread_id"], "customer", s["customer"], subj, body, "customer reported payment",
                "paid_thanks:%s" % s["thread_id"], now, mail_id, s.get("booking_ref"))
    return "paid_reported"


def mark_paid(con, ref, now):
    """The forwarder saw the money. -> the invoice row, or None if not found."""
    inv = find(con, ref)
    if not inv:
        return None
    if inv["status"] != "paid":
        con.execute("UPDATE ops_invoices SET status='paid', paid_at=? WHERE thread_id=?", (now, inv["thread_id"]))
    return get(con, inv["thread_id"])
