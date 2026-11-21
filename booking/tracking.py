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
from shared.rfq import PICKUP_ZONES

IATA = re.compile(r"\b([A-Z]{3})\b")
KG = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg", re.I)
POSTCODE = re.compile(r"\b(\d{5})\b")        # the customer names the pickup site by postcode: 51447 -> zone 51 -> CGN

STATUS_TEXT = {
    "requested": "booking requested with the airline, waiting for their confirmation",
    "booked": "booked with the airline",
    "confirmed": "booked and confirmed by the airline",
    "failed": "booking not completed yet, our team is on it",
}


def _all():
    return [dict(r) for r in crm.con().execute("SELECT * FROM bookings ORDER BY created_at DESC")]


EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _route_codes(text):
    codes = set(IATA.findall(text))
    codes |= {PICKUP_ZONES[p[:2]] for p in POSTCODE.findall(text) if p[:2] in PICKUP_ZONES}
    try:
        from shared.rfq import extract_rfq
        r = extract_rfq("", text)                       # city names in any language -> IATA
        codes |= {c for c in (r.origin, r.destination) if c}
    except Exception:
        pass
    return codes


def _name_tokens(address):
    local = (address or "").split("@")[0].lower()
    return {t for t in re.split(r"[._\-+]", local) if len(t) >= 3 and t.isalpha()}


def _company(address):
    dom = (address or "").split("@")[-1].lower().split(".")[0]
    words = [w for w in re.split(r"[-_]", dom) if len(w) >= 3]
    return " ".join(words) if words and dom not in ("gmail", "hackloop", "outlook", "yahoo", "web", "gmx") else ""


def find_booking(text, mail=None):
    """-> (booking or None, how it was matched). Strongest clue first."""
    # 1. the thread the question arrives in (a tracking mail may answer our booking mail in the customer's thread)
    if mail:
        raw = mail.get("raw") or {}
        for tid in [mail.get("thread_id")] + list(raw.get("references") or []) + [raw.get("in_reply_to")]:
            b = crm.get(tid) if tid else None
            if b:
                return b, "thread"
    # 2. booking reference or our own reference
    bk, team = BK.search(text), TEAM_REF.search(text)
    b = crm.find(bk and bk.group(0), team and team.group(0))
    if b:
        return b, "reference"
    rows = _all()
    low = text.lower()
    # 3. the customer: their address, or their name from the address ("Tobias Auer")
    mails = {e.lower() for e in EMAIL.findall(text)} - {"tracking@hackloop.mail"}
    by_cust = [r for r in rows if (r["customer"] or "").lower() in mails]
    if not by_cust:
        by_cust = [r for r in rows if _name_tokens(r["customer"]) and
                   all(re.search(r"\b%s\b" % re.escape(t), low) for t in _name_tokens(r["customer"]))]
    if not by_cust:                                     # company from the domain: auer-maschinenbau.de -> "auer maschinenbau"
        by_cust = [r for r in rows if _company(r["customer"]) and _company(r["customer"]) in re.sub(r"[-_.]", " ", low)]
    if not by_cust:                                     # one distinctive part of the name is enough when it points to ONE customer
        hit = [r for r in rows if any(len(t) >= 5 and t in low for t in _name_tokens(r["customer"]))]   # "roesterei" in "Kaffeeroesterei"
        if len({r["customer"] for r in hit}) == 1:
            by_cust = hit
    codes = _route_codes(text)
    pool = by_cust or rows
    lane = [r for r in pool if r["origin"] in codes and r["destination"] in codes] if codes else pool if by_cust else []
    if len(lane) > 1:
        m = KG.search(text)
        if m:
            kg = float(m.group(1).replace(",", "."))
            close = [r for r in lane if r["weight_kg"] and abs(r["weight_kg"] - kg) <= 0.02 * kg]
            lane = close or lane
    if not lane:                                        # origin written some way we cannot map: destination (+ weight) decides
        kg = KG.search(text)
        kg = float(kg.group(1).replace(",", ".")) if kg else None
        near = lambda r: bool(kg and r["weight_kg"] and abs(r["weight_kg"] - kg) <= 0.02 * kg)
        dest = [r for r in (by_cust or rows) if r["destination"] in codes] if codes else []
        lane = [r for r in dest if near(r)] or (dest if by_cust else [])
    if len(lane) > 1 and by_cust:
        return lane[0], "customer, newest of %d" % len(lane)     # rows are newest first
    if len(lane) == 1:
        return lane[0], "customer" if by_cust else "route"
    if len(lane) > 1:
        return None, "ambiguous: %d bookings on this route" % len(lane)
    return None, "no match"


def _day(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%d %b %Y") if ts else None


STATUS_TEXT_DE = {
    "requested": "bei der Airline angefragt, die Bestätigung steht noch aus",
    "booked": "bei der Airline gebucht",
    "confirmed": "gebucht und von der Airline bestätigt",
    "failed": "noch nicht fertig gebucht, wir sind dran",
}


def _answer_de(b, thread_id=0):
    """Same facts as the English answer, for a customer who wrote in German."""
    from llm.extract import CITY, CITY_DE, SIGNER, SIGN_OFF
    import zlib
    names = dict(CITY, **CITY_DE)
    o, d = names.get(b["origin"], b["origin"]), names.get(b["destination"], b["destination"])
    ref = b["booking_reference"] or b["team_reference"]
    status = STATUS_TEXT_DE.get(b["status"], b["status"] or "in Arbeit")
    since = b["confirmed_at"] or b["booked_at"]
    eta = dt.datetime.fromtimestamp(since + int(b["transit_days"]) * 86400).strftime("%d.%m.%Y") \
        if since and b["transit_days"] else None
    kg = ("%g kg " % b["weight_kg"]) if b["weight_kg"] else ""
    first = "ich habe gerade nachgesehen: Ihre %sSendung von %s nach %s (%s) ist %s, Airline ist %s." % (
        kg, o, d, ref, status, b["airline"])
    if eta:
        first += " Bei rund %s Tagen Laufzeit rechnen wir mit der Ankunft um den %s." % (b["transit_days"], eta)
    facts = ["Buchungsnummer: %s" % (b["booking_reference"] or "folgt"), "Unsere Referenz: %s" % b["team_reference"],
             "Strecke: %s nach %s" % (b["origin"], b["destination"]), "Airline: %s" % b["airline"], "Status: %s" % status]
    if b["weight_kg"]:
        facts.append("Gewicht: %g kg%s" % (b["weight_kg"], ", %g cbm" % b["volume_cbm"] if b["volume_cbm"] else ""))
    if since:
        facts.append("Gebucht am: %s" % dt.datetime.fromtimestamp(b["booked_at"] or since).strftime("%d.%m.%Y"))
    if eta:
        facts.append("Voraussichtliche Ankunft: um den %s" % eta)
    sign = SIGN_OFF["de"][zlib.crc32(str(thread_id).encode()) % len(SIGN_OFF["de"])]
    return ("Guten Tag,\n\n%s\n\n%s\n\nWenn sich etwas ändert, melde ich mich sofort.\n\n%s\n%s\nLuftfracht Export"
            % (first, "\n".join(facts), sign, SIGNER))


def answer_text(b, thread_id=0, lang="en"):
    """Human first paragraph with the facts in it, then the same facts as short lines (easy to check)."""
    if lang == "de":
        return _answer_de(b, thread_id)
    from llm.extract import CITY, SIGNER, SIGN_OFF
    import zlib
    o, d = CITY.get(b["origin"], b["origin"]), CITY.get(b["destination"], b["destination"])
    ref = b["booking_reference"] or b["team_reference"]
    status = STATUS_TEXT.get(b["status"], b["status"] or "in progress")
    since = b["confirmed_at"] or b["booked_at"]
    eta = _day(since + int(b["transit_days"]) * 86400) if since and b["transit_days"] else None
    kg = ("%g kg " % b["weight_kg"]) if b["weight_kg"] else ""
    if b["status"] == "confirmed":
        first = "I just checked your %sshipment from %s to %s (%s): it is %s, flying with %s." % (
            kg, o, d, ref, status, b["airline"])
    elif b["status"] == "booked":
        first = "Your %sshipment from %s to %s (%s) is %s %s; the airline's confirmation is on its way." % (
            kg, o, d, ref, "booked with", b["airline"])
    else:
        first = "Your %sshipment from %s to %s (our ref %s): %s." % (kg, o, d, ref, status)
    if eta:
        first += " With about %s days in transit we expect it to arrive around %s." % (b["transit_days"], eta)
    facts = ["Booking reference: %s" % (b["booking_reference"] or "pending"), "Our reference: %s" % b["team_reference"],
             "Route: %s to %s" % (b["origin"], b["destination"]), "Airline: %s" % b["airline"], "Status: %s" % status]
    if b["weight_kg"]:
        facts.append("Weight: %g kg%s" % (b["weight_kg"], ", %g cbm" % b["volume_cbm"] if b["volume_cbm"] else ""))
    if since:
        facts.append("Booked on: %s" % _day(b["booked_at"] or since))
    if eta:
        facts.append("Expected arrival: around %s" % eta)
    sign = SIGN_OFF["en"][zlib.crc32(str(thread_id).encode()) % len(SIGN_OFF["en"])]
    return ("Hello,\n\n%s\n\n%s\n\nIf anything changes I'll let you know right away.\n\n%s\n%s\nAir Export"
            % (first, "\n".join(facts), sign, SIGNER))


NOT_FOUND = ("Hello,\n\nthanks for checking in. I couldn't match your message to one of our bookings yet. "
             "Could you send me the booking reference (BK-...) or our reference (GOOGLE-...)? "
             "Then I'll reply with the status straight away.\n\nBest regards\n{SIGNER}\nAir Export")
NOT_FOUND_DE = ("Guten Tag,\n\ndanke für Ihre Nachfrage. Ich konnte Ihre Nachricht noch keiner unserer Buchungen zuordnen. "
                "Schicken Sie mir bitte die Buchungsnummer (BK-...) oder unsere Referenz (GOOGLE-...)? "
                "Dann bekommen Sie den Status sofort.\n\nViele Grüße\n{SIGNER}\nLuftfracht Export")


def not_found(lang="en"):
    from llm.extract import SIGNER
    return (NOT_FOUND_DE if lang == "de" else NOT_FOUND).replace("{SIGNER}", SIGNER)


def handle(mail):
    tid = mail["thread_id"]
    b, how = find_booking(mail["subject"] + "\n" + mail["body"], mail)
    db.event("tracking_lookup", tid, mail["id"], matched=bool(b), how=how,
             booking=b and {k: b[k] for k in ("thread_id", "booking_reference", "status")})
    from llm import lang as langmod
    lang = langmod.detect(mail["subject"] + "\n" + mail["body"]) or (b and b.get("language")) or "en"   # the customer's language
    body = answer_text(b, tid, lang) if b else not_found(lang)
    subject = mail["subject"] if mail["subject"].lower().startswith("re:") else "Re: " + mail["subject"]
    ok = mailbox.send(mail["sender"], subject, body, in_reply_to=mail["id"], thread_id=tid)
    db.event("tracking_answered" if ok else "tracking_failed", tid, mail["id"], matched=bool(b), how=how)
