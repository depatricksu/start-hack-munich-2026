"""Task 05: answer "where is my shipment?" from tracking@hackloop.mail, from our own CRM (+10 per correct answer).

No LLM, $0: the answer is facts from the `bookings` table (booking/crm.py), so code writes it.
Which booking? Strongest clue first:
  1. BK-... booking reference   2. our GOOGLE-<thread> reference   3. route (+ weight) of a booking we hold
If nothing matches we say so politely and ask for the reference (never invent a status).
"""
import datetime as dt, re

from core import db, mailbox
from . import crm
from .handlers import BK, TEAM_REF

IATA = re.compile(r"\b([A-Z]{3})\b")
KG = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.I)

STATUS_TEXT = {
    "requested": "booking requested with the airline, waiting for their confirmation",
    "booked": "booked with the airline",
    "confirmed": "booked and confirmed by the airline",
    "failed": "booking not completed yet, our team is on it",
}


def _all():
    return [dict(r) for r in crm.con().execute("SELECT * FROM bookings ORDER BY created_at DESC")]


def find_booking(text):
    """-> (booking or None, how it was matched)."""
    bk, team = BK.search(text), TEAM_REF.search(text)
    b = crm.find(bk and bk.group(0), team and team.group(0))
    if b:
        return b, "reference"
    rows = _all()
    codes = set(IATA.findall(text))
    lane = [r for r in rows if r["origin"] in codes and r["destination"] in codes]
    if len(lane) > 1:
        m = KG.search(text)
        if m:
            kg = float(m.group(1).replace(",", "."))
            close = [r for r in lane if r["weight_kg"] and abs(r["weight_kg"] - kg) <= 0.02 * kg]
            lane = close or lane
    if len(lane) == 1:
        return lane[0], "route"
    if len(lane) > 1:
        return None, "ambiguous: %d bookings on this route" % len(lane)
    return None, "no match"


def _day(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%d %b %Y") if ts else None


def answer_text(b):
    status = STATUS_TEXT.get(b["status"], b["status"] or "in progress")
    lines = ["Hello,", "", "here is the current status of the shipment:", "",
             "Booking reference: %s" % (b["booking_reference"] or "pending (our ref %s)" % b["team_reference"]),
             "Our reference: %s" % b["team_reference"],
             "Route: %s to %s" % (b["origin"], b["destination"]),
             "Airline: %s" % b["airline"]]
    if b["weight_kg"]:
        lines.append("Weight: %g kg%s" % (b["weight_kg"], ", %g cbm" % b["volume_cbm"] if b["volume_cbm"] else ""))
    lines.append("Status: %s" % status)
    since = b["confirmed_at"] or b["booked_at"]
    if since:
        lines.append("Booked on: %s" % _day(b["booked_at"] or since))
        if b["transit_days"]:
            eta = since + int(b["transit_days"]) * 86400
            lines.append("Transit time: %s days, expected arrival around %s" % (b["transit_days"], _day(eta)))
    lines += ["", "Best regards", "Your forwarding team"]
    return "\n".join(lines)


NOT_FOUND = ("Hello,\n\nthank you for your message. We could not match it to one of our bookings yet. "
             "Could you send us the booking reference (BK-...) or our reference (GOOGLE-...)? "
             "Then we will reply with the status right away.\n\nBest regards\nYour forwarding team")


def handle(mail):
    tid = mail["thread_id"]
    b, how = find_booking(mail["subject"] + "\n" + mail["body"])
    db.event("tracking_lookup", tid, mail["id"], matched=bool(b), how=how,
             booking=b and {k: b[k] for k in ("thread_id", "booking_reference", "status")})
    body = answer_text(b) if b else NOT_FOUND
    subject = mail["subject"] if mail["subject"].lower().startswith("re:") else "Re: " + mail["subject"]
    ok = mailbox.send(mail["sender"], subject, body, in_reply_to=mail["id"], thread_id=tid)
    db.event("tracking_answered" if ok else "tracking_failed", tid, mail["id"], matched=bool(b), how=how)
