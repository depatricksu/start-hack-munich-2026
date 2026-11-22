"""Message templates for every party and every update. Plain human tone, no LLM. Customer: EN or DE (their language
when we know it, else EN). Carriers, partners and the forwarder desk: EN.

Every function returns (subject, body). Nothing here sends anything: run.py puts the result into the outbox as a draft.
"""
import re

from . import rules

SIGN = {"en": "Kind regards\nAir Export team", "de": "Viele Grüße\nIhr Air-Export-Team"}
MON_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def lang_of(s):
    return "de" if (s.get("language") or "").lower().startswith("de") else "en"


def fmt_date(iso, lang="en"):
    """'2026-11-28 09:15' -> '28 Nov 2026, 09:15' / '28.11.2026, 09:15 Uhr'."""
    if not iso:
        return None
    d = rules.parse_eta(iso)
    if not d:
        return iso
    has_time = len(iso) > 10
    if lang == "de":
        return d.strftime("%d.%m.%Y") + (d.strftime(", %H:%M Uhr") if has_time else "")
    return "%d %s %d" % (d.day, MON_EN[d.month - 1], d.year) + (d.strftime(", %H:%M") if has_time else "")


def hello(s, lang):
    n = s.get("customer_name")
    if lang == "de":
        return "Hallo %s," % n if n else "Guten Tag,"
    return "Hi %s," % n if n else "Hello,"


def ref_line(s, lang):
    parts = [s.get("our_ref")]
    if s.get("booking_ref"):
        parts.append(("Buchung " if lang == "de" else "booking ") + s["booking_ref"])
    return ", ".join(p for p in parts if p)


def cust_subject(s):
    subj = s.get("subject") or "Your shipment %s" % s.get("our_ref")
    return subj if subj.lower().startswith(("re:", "aw:")) else "Re: " + subj


def goods_text(s):
    g = s.get("goods") or "general cargo"
    return g if re.search(r"\bkg\b", g, re.I) else "%s, %s kg, %s cbm" % (g, kg(s.get("weight_kg")), kg(s.get("volume_cbm")))


def kg(v):
    try:
        return ("%.1f" % float(v)).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "?"


# ------------------------------------------------------------------ step 6: everyone informed after confirmation
def customer_next_steps(s):
    lang = lang_of(s)
    eta = fmt_date(s.get("eta_planned"), lang)
    if lang == "de":
        body = ("%s\n\nIhre Sendung %s ist bei %s fest gebucht. So geht es weiter:\n\n"
                "1. Abholung: %s\n"
                "2. Bitte schicken Sie uns als Antwort auf diese Mail: Shipper's Letter of Instruction, Handelsrechnung "
                "und Packliste. Bei einem Warenwert über 1.000 EUR erstellen wir mit der Rechnung auch die Ausfuhranmeldung.\n"
                "3. Geplante Ankunft in %s: um den %s. Sobald die Airline den Flug meldet, geben wir Ihnen Bescheid.\n\n"
                "Die Rechnung bekommen Sie nach der Zustellung.\n\n%s"
                % (hello(s, lang), ref_line(s, lang), s.get("airline"),
                   ("%s holt die Ware bei Ihnen ab (%s). Den Termin bestätigen wir Ihnen noch." % (s["trucker"], s.get("pickup") or "Ihre Adresse"))
                   if s.get("trucker") else "Bitte liefern Sie die Ware am Flughafen %s an." % s.get("origin"),
                   s.get("destination"), eta or "?", SIGN[lang]))
    else:
        body = ("%s\n\nyour shipment %s is booked with %s. Next steps:\n\n"
                "1. Pickup: %s\n"
                "2. Please send us, as a reply to this mail: the Shipper's Letter of Instruction, the commercial invoice "
                "and the packing list. If the goods are worth more than EUR 1,000 we also file the export declaration with the invoice.\n"
                "3. Planned arrival in %s: around %s. We will tell you as soon as the airline reports the flight.\n\n"
                "You will get our invoice after delivery.\n\n%s"
                % (hello(s, lang), ref_line(s, lang), s.get("airline"),
                   ("%s will collect the goods from you (%s). We will confirm the time." % (s["trucker"], s.get("pickup") or "your address"))
                   if s.get("trucker") else "please deliver the goods to %s airport." % s.get("origin"),
                   s.get("destination"), eta or "?", SIGN[lang]))
    return cust_subject(s), body


def trucker_pickup_order(s):
    subj = "Pickup order %s, %s to %s airport" % (s.get("our_ref"), s.get("pickup") or "pickup address", s.get("origin"))
    body = ("Hello %s team,\n\nthank you for your offer of %s %s. We confirm the pickup:\n\n"
            "- Collect: %s%s\n"
            "- Goods: %s\n"
            "- Ready: %s\n"
            "- Deliver to: %s airport, %s cargo terminal, booking %s\n\n"
            "Please confirm the pickup time and send us the delivery receipt once the goods are handed over. "
            "Please quote %s in every mail.\n\n%s"
            % (s.get("trucker"), s.get("trucker_quote") or "?", s.get("currency") or "EUR",
               (s.get("company") + ", ") if s.get("company") else "", s.get("pickup") or "address to follow",
               goods_text(s), s.get("ready") or "as agreed with the shipper", s.get("origin"), s.get("airline"),
               s.get("booking_ref") or "to follow", s.get("our_ref"), SIGN["en"]))
    return subj, body


def airline_details(s):
    subj = "Booking %s, shipment details (%s)" % (s.get("booking_ref") or "", s.get("our_ref"))
    body = ("Hello,\n\nthank you for confirming booking %s. The shipment details:\n\n"
            "- Our reference: %s\n- Lane: %s-%s\n- Shipper: %s\n- Goods: %s\n"
            "- Weight / volume: %s kg gross, %s cbm\n- Delivery to your %s terminal: %s\n\n"
            "Please issue the air waybill to our reference and send us the AWB number and any flight change.\n\n%s"
            % (s.get("booking_ref"), s.get("our_ref"), s.get("origin"), s.get("destination"),
               s.get("company") or s.get("customer"), s.get("goods") or "general cargo", kg(s.get("weight_kg")),
               kg(s.get("volume_cbm")), s.get("origin"),
               ("by truck (%s)" % s["trucker"]) if s.get("trucker") else "by the shipper", SIGN["en"]))
    return subj, body


def partner_prealert(s):
    subj = "Pre-alert %s, %s-%s, %s" % (s.get("our_ref"), s.get("origin"), s.get("destination"), s.get("airline"))
    body = ("Hello partner in %s,\n\npre-alert for an inbound air shipment:\n\n"
            "- Our reference: %s, airline booking %s with %s\n- Goods: %s\n"
            "- Planned arrival: %s%s\n- Shipper: %s\n\n"
            "We will send flight and AWB as soon as the airline reports them. Please arrange customs clearance and "
            "delivery with the consignee.\n\n%s"
            % (s.get("destination"), s.get("our_ref"), s.get("booking_ref"), s.get("airline"), goods_text(s),
               fmt_date(s.get("eta_current") or s.get("eta_planned")) or "to follow",
               (", AWB %s" % s["awb"]) if s.get("awb") else "", s.get("company") or s.get("customer"), SIGN["en"]))
    return subj, body


def bidder_thanks(s, carrier):
    subj = "Your offer for %s" % s.get("our_ref")
    body = ("Hello %s team,\n\nthank you for your quick offer for our request %s (%s-%s). This time we have chosen "
            "another option. We will gladly ask you again for the next shipment on this lane.\n\n%s"
            % (carrier, s.get("our_ref"), s.get("origin"), s.get("destination"), SIGN["en"]))
    return subj, body


# ------------------------------------------------------------------ step 7: updates to the customer
def customer_update(s, typ, upd):
    """One update mail for the customer. upd: new_eta, flight, old_flight, delay_hours, summary, offer_flight, offer_date."""
    lang = lang_of(s)
    eta = fmt_date(upd.get("new_eta") or s.get("eta_current"), lang)
    flight = upd.get("flight") or s.get("flight")
    ref = ref_line(s, lang)
    reason = upd.get("reason")
    de = lang == "de"
    if typ == "delayed":
        if de:
            lines = ["die Airline %s hat uns eine Verspätung Ihrer Sendung %s gemeldet." % (s.get("airline"), ref)]
            if reason:
                lines.append("Grund laut Airline: %s." % reason)
            lines.append("Neue Ankunft in %s: %s%s." % (s.get("destination"), eta or "folgt",
                         (", mit Flug %s" % flight) if flight else ""))
            lines.append("Sie müssen nichts tun. Wir verfolgen die Sendung weiter und melden uns bei jeder Änderung.")
        else:
            lines = ["%s has told us that your shipment %s is delayed." % (s.get("airline"), ref)]
            if reason:
                lines.append("The airline's reason: %s." % reason)
            lines.append("New arrival in %s: %s%s." % (s.get("destination"), eta or "to follow",
                         (", on flight %s" % flight) if flight else ""))
            lines.append("No action is needed from you. We keep watching the shipment and tell you about every change.")
    elif typ in ("offloaded", "rebooked"):
        if de:
            lines = ["Ihre Sendung %s fliegt mit einem anderen Flug: %s%s." % (
                ref, "die Airline hat sie vom geplanten Flug genommen" if typ == "offloaded" else "die Airline hat sie umgebucht",
                (" (vorher %s)" % upd["old_flight"]) if upd.get("old_flight") else ""),
                "Neuer Flug: %s. Neue Ankunft in %s: %s." % (flight or "folgt", s.get("destination"), eta or "folgt"),
                "Sie müssen nichts tun."]
        else:
            lines = ["your shipment %s is moving to another flight: %s%s." % (
                ref, "the airline took it off the planned flight" if typ == "offloaded" else "the airline has rebooked it",
                (" (was %s)" % upd["old_flight"]) if upd.get("old_flight") else ""),
                "New flight: %s. New arrival in %s: %s." % (flight or "to follow", s.get("destination"), eta or "to follow"),
                "No action is needed from you."]
    elif typ == "cancelled":
        offer = upd.get("offer_flight")
        odate = fmt_date(upd.get("offer_date"), lang)
        if de:
            lines = ["leider hat %s die Buchung für Ihre Sendung %s storniert%s." % (s.get("airline"), ref,
                     (" (%s)" % reason) if reason else "")]
            lines.append(("Die Airline bietet stattdessen Flug %s%s zum gleichen Preis an. Sollen wir umbuchen? "
                          "Ein kurzes \"Ja\" als Antwort genügt." % (offer, (" am %s" % odate) if odate else ""))
                         if offer else "Wir suchen gerade den nächsten freien Flug und schicken Ihnen den Vorschlag.")
            lines.append("Es entstehen Ihnen dafür keine Mehrkosten ohne Ihre Zustimmung.")
        else:
            lines = ["I am sorry: %s has cancelled the booking for your shipment %s%s." % (s.get("airline"), ref,
                     (" (%s)" % reason) if reason else "")]
            lines.append(("The airline offers flight %s%s at the same price instead. Shall we rebook? "
                          "A short \"yes\" as a reply is enough." % (offer, (" on %s" % odate) if odate else ""))
                         if offer else "We are looking for the next free flight and will send you a proposal.")
            lines.append("Nothing will be charged extra without your OK.")
    elif typ == "rebook_confirmed":
        lines = (["die Airline hat die Umbuchung bestätigt. Ihre Sendung %s fliegt mit %s, Ankunft in %s: %s."
                  % (ref, flight or "dem neuen Flug", s.get("destination"), eta or "folgt")] if de else
                 ["the airline has confirmed the new booking. Your shipment %s flies on %s, arrival in %s: %s."
                  % (ref, flight or "the new flight", s.get("destination"), eta or "to follow")])
    elif typ == "departed":
        lines = (["Ihre Sendung %s ist abgeflogen%s. Erwartete Ankunft in %s: %s." % (
            ref, (" (Flug %s)" % flight) if flight else "", s.get("destination"), eta or "folgt")] if de else
            ["your shipment %s has departed%s. Expected arrival in %s: %s." % (
                ref, (" on flight %s" % flight) if flight else "", s.get("destination"), eta or "to follow")])
    elif typ == "arrived":
        lines = (["Ihre Sendung %s ist in %s angekommen (%s). Die Zustellung an den Empfänger folgt." % (
            ref, s.get("destination"), eta or "heute")] if de else
            ["your shipment %s has arrived in %s (%s). Delivery to the consignee follows." % (
                ref, s.get("destination"), eta or "today")])
    elif typ == "delivered":
        when = fmt_date(upd.get("delivered_at") or s.get("delivered_at"), lang)
        lines = (["Ihre Sendung %s wurde zugestellt%s. Den Abliefernachweis (POD) haben wir. Die Rechnung schicken wir separat."
                  % (ref, (" (%s)" % when) if when else "")] if de else
                 ["your shipment %s has been delivered%s. We have the proof of delivery. Our invoice follows separately."
                  % (ref, (" (%s)" % when) if when else "")])
    elif typ == "picked_up":
        lines = (["%s hat Ihre Ware abgeholt (%s). Sie ist auf dem Weg zum Flughafen %s." % (s.get("trucker"), ref, s.get("origin"))]
                 if de else ["%s has collected your goods (%s). They are on the way to %s airport." % (
                     s.get("trucker"), ref, s.get("origin"))])
    elif typ == "handed_over":
        lines = (["%s hat Ihre Ware abgeholt und bei %s am Flughafen %s abgegeben (%s). Jetzt ist die Airline dran."
                  % (s.get("trucker"), s.get("airline"), s.get("origin"), ref)] if de else
                 ["%s has collected your goods and handed them to %s at %s airport (%s). The airline takes it from here."
                  % (s.get("trucker"), s.get("airline"), s.get("origin"), ref)])
    elif typ == "rebook_ack":
        lines = (["danke, wir haben die Airline gebeten, Ihre Sendung %s auf %s umzubuchen. Sobald sie bestätigt, melden wir uns."
                  % (ref, upd.get("offer_flight") or "den angebotenen Flug")] if de else
                 ["thank you, we have asked the airline to move your shipment %s to %s. We will confirm as soon as they do."
                  % (ref, upd.get("offer_flight") or "the offered flight")])
    else:
        return None
    return cust_subject(s), "%s\n\n%s\n\n%s" % (hello(s, lang), "\n".join(lines), SIGN[lang])


def partner_update(s, typ, upd):
    subj = "Update %s: %s" % (s.get("our_ref"), typ)
    eta = fmt_date(upd.get("new_eta") or s.get("eta_current"))
    body = ("Hello partner in %s,\n\nupdate for %s (airline %s, booking %s): %s.\n"
            "Flight: %s. Arrival: %s.%s\n\n%s"
            % (s.get("destination"), s.get("our_ref"), s.get("airline"), s.get("booking_ref"),
               {"delayed": "delayed", "offloaded": "offloaded, moved to another flight", "rebooked": "rebooked",
                "departed": "departed", "cancelled": "booking cancelled by the airline, pre-alert on hold",
                "cancelled_by_customer": "cancelled by the customer, please close the pre-alert",
                "rebook_confirmed": "rebooked and confirmed again"}.get(typ, typ),
               upd.get("flight") or s.get("flight") or "to follow", eta or "to follow",
               (" AWB %s." % (upd.get("awb") or s.get("awb"))) if (upd.get("awb") or s.get("awb")) else "", SIGN["en"]))
    return subj, body


def trucker_hold(s, why):
    subj = "Pickup %s: please hold" % s.get("our_ref")
    body = ("Hello %s team,\n\nplease hold the pickup for %s (%s): %s. We will send you a new date or a cancellation "
            "shortly.\n\n%s" % (s.get("trucker"), s.get("our_ref"), s.get("pickup") or "", why, SIGN["en"]))
    return subj, body


def trucker_cancel(s):
    subj = "Pickup %s cancelled" % s.get("our_ref")
    body = ("Hello %s team,\n\nthe customer has cancelled shipment %s. Please cancel the pickup at %s. "
            "Sorry for the trouble and thank you.\n\n%s" % (s.get("trucker"), s.get("our_ref"), s.get("pickup") or "", SIGN["en"]))
    return subj, body


def airline_rebook_request(s, offer_flight, offer_date):
    subj = "Booking %s: please rebook on %s (%s)" % (s.get("booking_ref"), offer_flight or "next flight", s.get("our_ref"))
    body = ("Hello,\n\nthank you for the alternative. Please rebook shipment %s (%s, %s kg, %s cbm, %s-%s) on %s%s "
            "at the same rate and send us the new confirmation.\n\n%s"
            % (s.get("our_ref"), s.get("booking_ref"), kg(s.get("weight_kg")), kg(s.get("volume_cbm")), s.get("origin"),
               s.get("destination"), offer_flight or "your next available flight",
               (" on %s" % fmt_date(offer_date)) if offer_date else "", SIGN["en"]))
    return subj, body


def forwarder(s, title, lines):
    """Internal note for the forwarder desk."""
    subj = "[carrierops] %s: %s" % ((s or {}).get("our_ref") or "unmatched", title)
    return subj, "\n".join(lines)


# ------------------------------------------------------------------ invoice
def customer_invoice(s, inv):
    lang = lang_of(s)
    lines = "\n".join("- %s: %s %s" % (l[0], l[1], inv["currency"]) for l in rules_lines(inv))
    due = fmt_date(_iso(inv["due_at"]), lang)
    if lang == "de":
        body = ("%s\n\nIhre Sendung %s ist zugestellt. Hier ist unsere Rechnung %s:\n\n%s\n\nGesamt: %s %s\nFällig: %s\n\n"
                "Bitte geben Sie %s bei der Zahlung an.\n\n%s" % (hello(s, lang), ref_line(s, lang), inv["number"], lines,
                                                                 inv["amount"], inv["currency"], due, inv["number"], SIGN[lang]))
        subj = "Rechnung %s für %s" % (inv["number"], s.get("our_ref"))
    else:
        body = ("%s\n\nyour shipment %s has been delivered. Here is our invoice %s:\n\n%s\n\nTotal: %s %s\nDue: %s\n\n"
                "Please quote %s with your payment.\n\n%s" % (hello(s, lang), ref_line(s, lang), inv["number"], lines,
                                                              inv["amount"], inv["currency"], due, inv["number"], SIGN[lang]))
        subj = "Invoice %s for %s" % (inv["number"], s.get("our_ref"))
    return subj, body


def customer_reminder(s, inv, n):
    lang = lang_of(s)
    due = fmt_date(_iso(inv["due_at"]), lang)
    if lang == "de":
        body = ("%s\n\neine freundliche Erinnerung: unsere Rechnung %s für %s über %s %s war am %s fällig. Wir haben die "
                "Zahlung noch nicht gesehen. Falls sie schon unterwegs ist, ignorieren Sie diese Mail bitte.\n\n%s"
                % (hello(s, lang), inv["number"], s.get("our_ref"), inv["amount"], inv["currency"], due, SIGN[lang]))
        subj = "Erinnerung %d: Rechnung %s" % (n, inv["number"])
    else:
        body = ("%s\n\na friendly reminder: our invoice %s for %s over %s %s was due on %s and we have not seen the payment "
                "yet. If it is already on its way, please ignore this mail.\n\n%s"
                % (hello(s, lang), inv["number"], s.get("our_ref"), inv["amount"], inv["currency"], due, SIGN[lang]))
        subj = "Reminder %d: invoice %s" % (n, inv["number"])
    return subj, body


def customer_paid_thanks(s, inv):
    lang = lang_of(s)
    if lang == "de":
        return cust_subject(s), ("%s\n\nvielen Dank für die Nachricht. Wir ordnen die Zahlung für Rechnung %s zu, sobald "
                                 "sie bei uns eingeht.\n\n%s" % (hello(s, lang), inv["number"], SIGN[lang]))
    return cust_subject(s), ("%s\n\nthank you for letting us know. We will match the payment for invoice %s as soon as it "
                             "reaches our account.\n\n%s" % (hello(s, lang), inv["number"], SIGN[lang]))


def rules_lines(inv):
    import json
    try:
        return json.loads(inv["lines"]) or [["Air freight", inv["amount"]]]
    except (TypeError, ValueError):
        return [["Air freight", inv["amount"]]]


def _iso(ts):
    import time
    return time.strftime("%Y-%m-%d", time.gmtime(ts))
