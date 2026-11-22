"""Step 8: "where is my shipment?" answered from carrierops' own state.

The carrier owns the movement data. We repeat what the carrier last reported (status, ETA, flight, AWB, tracking
link) and our own leg (truck pickup). We never invent a status: before the airline reports anything we say so,
and a planned date is called planned.
"""
from . import messages, state

STATUS_TEXT = {
    "en": {"confirmed": "booked and confirmed, not yet departed", "picked_up": "collected by the truck, on the way to the airport",
           "handed_over": "handed over to the airline at %(origin)s", "departed": "departed", "delayed": "delayed",
           "offloaded": "taken off the planned flight and moved to another one", "rebooked": "rebooked on another flight",
           "arrived": "arrived in %(destination)s", "delivered": "delivered", "cancelled_by_airline": "booking cancelled by the airline",
           "rebook_requested": "rebooking requested, waiting for the airline", "cancelled": "cancelled"},
    "de": {"confirmed": "gebucht und bestätigt, noch nicht abgeflogen", "picked_up": "vom Lkw abgeholt, auf dem Weg zum Flughafen",
           "handed_over": "an die Airline in %(origin)s übergeben", "departed": "abgeflogen", "delayed": "verspätet",
           "offloaded": "vom geplanten Flug genommen und auf einen anderen gebucht", "rebooked": "auf einen anderen Flug umgebucht",
           "arrived": "in %(destination)s angekommen", "delivered": "zugestellt", "cancelled_by_airline": "Buchung von der Airline storniert",
           "rebook_requested": "Umbuchung angefragt, wir warten auf die Airline", "cancelled": "storniert"},
}


def find(con, thread_id=None, ref=None):
    if thread_id:
        s = state.shipment(con, thread_id)
        if s:
            return s
    if ref:
        ref = str(ref).strip().upper()
        if ref.startswith("GOOGLE-"):
            try:
                return state.shipment(con, int(ref[7:]))
            except ValueError:
                return None
        return state.one(con, "SELECT * FROM shipment_state WHERE UPPER(booking_ref)=? OR awb=?", (ref, ref))
    return None


def last_carrier_update(con, thread_id):
    return state.one(con, "SELECT * FROM shipment_updates WHERE thread_id=? AND source='carrier' AND type NOT IN "
                          "('info','price','booked') ORDER BY at DESC, id DESC LIMIT 1", (thread_id,))


def status(con, thread_id):
    """The facts, as a dict (for a UI or a test)."""
    s = state.shipment(con, thread_id)
    if not s:
        return None
    u = last_carrier_update(con, thread_id)
    reported = state.one(con, "SELECT 1 FROM shipment_updates WHERE thread_id=? AND new_eta IS NOT NULL", (thread_id,))
    return {"thread_id": thread_id, "our_ref": s["our_ref"], "booking_ref": s["booking_ref"], "airline": s["airline"],
            "status": s["status"], "eta": s["eta_current"], "eta_is_planned": reported is None,
            "flight": s["flight"], "awb": s["awb"], "tracking_url": s["tracking_url"],
            "last_carrier_report": u and {"type": u["type"], "at": u["at"], "summary": u["summary"]},
            "trucker": s["trucker"], "picked_up_at": s["picked_up_at"], "delivered_at": s["delivered_at"]}


def answer_text(con, thread_id=None, ref=None, lang=None, desk=False):
    """Plain text answer in the customer's language (or `lang`). None if we do not know the shipment."""
    s = find(con, thread_id, ref)
    if not s:
        return None
    st = status(con, s["thread_id"])
    lang = lang or messages.lang_of(s)
    de = lang == "de"
    T = STATUS_TEXT[lang]
    lines = []
    refs = messages.ref_line(s, lang)
    if st["last_carrier_report"] is None and s["status"] == "confirmed":
        lines.append(("Ihre Sendung %s ist bei %s gebucht und bestätigt. Die Airline hat noch keine Bewegung gemeldet."
                      if de else "your shipment %s is booked and confirmed with %s. The airline has not reported any movement yet.")
                     % (refs, s["airline"]))
    else:
        txt = T.get(s["status"], s["status"]) % s
        lines.append(("Ihre Sendung %s mit %s: %s (letzte Meldung der Airline)." if de else
                      "your shipment %s with %s: %s (latest report from the airline).") % (refs, s["airline"], txt))
    if s["status"] == "delivered":
        when = messages.fmt_date(s["delivered_at"], lang)
        if when:
            lines.append(("Zugestellt am %s." if de else "Delivered on %s.") % when)
    elif s["status"] not in ("cancelled", "cancelled_by_airline", "rebook_requested") and s["eta_current"]:
        eta = messages.fmt_date(s["eta_current"], lang)
        if st["eta_is_planned"]:
            lines.append(("Geplante Ankunft in %s: um den %s (Plan, noch nicht von der Airline gemeldet)." if de else
                          "Planned arrival in %s: around %s (our plan, not yet reported by the airline).") % (s["destination"], eta))
        else:
            lines.append(("Ankunft in %s laut Airline: %s." if de else "Arrival in %s as reported by the airline: %s.")
                         % (s["destination"], eta))
    if s["status"] == "cancelled_by_airline" and s["offer_flight"]:
        lines.append(("Die Airline bietet Flug %s an. Sollen wir umbuchen?" if de else
                      "The airline offers flight %s. Shall we rebook?") % s["offer_flight"])
    facts = []
    if s["flight"]:
        facts.append(("Flug %s" if de else "flight %s") % s["flight"])
    if s["awb"]:
        facts.append("AWB %s" % s["awb"])
    if facts:
        lines.append(("Details: %s." if de else "Details: %s.") % ", ".join(facts))
    if s["tracking_url"]:
        lines.append(("Sendungsverfolgung der Airline: %s" if de else "Airline tracking: %s") % s["tracking_url"])
    elif s["awb"]:
        lines.append(("Mit der AWB-Nummer können Sie die Sendung auch auf der Seite von %s verfolgen." if de else
                      "You can also track it with the AWB number on %s's website.") % s["airline"])
    if s["trucker"]:
        if s["picked_up_at"]:
            lines.append(("Abholung: %s hat die Ware am %s abgeholt." if de else "Pickup: %s collected the goods on %s.")
                         % (s["trucker"], messages.fmt_date(s["picked_up_at"], lang)))
        elif s["status"] == "confirmed":
            lines.append(("Abholung: mit %s geplant, noch nicht gemeldet." if de else
                          "Pickup: planned with %s, not reported yet.") % s["trucker"])
    greet = "Hello," if desk else messages.hello(s, lang)
    return "%s\n\n%s\n\n%s" % (greet, "\n".join(lines), messages.SIGN[lang])
