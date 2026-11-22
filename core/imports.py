"""A request to bring goods INTO Germany. We arrange air export out of German airports: no rate sheet and no lane on
the rate portal starts anywhere else, and the airlines answer "we do not serve this lane".

5U, 22 Nov 08:01 (request 47987): "Could you quote ... an airport-to-airport air import from Tokyo airport (NRT), JP,
to Hamburg airport (HAM), Germany? Our supplier will hand over the goods at NRT, and we're the receiver in Germany."
The gate stopped it (NRT is not an export airport) and left it for a person. The rate desk and five airlines, asked by
mail, all answered that nobody offers NRT-HAM. An honest "we cannot quote this" was the right answer: 5U counted the
round as accepted and the customer wrote "Understood, thanks for letting me know."

Careful: the word "import" alone says nothing. Customers call an export from Germany "our buyer's import into
Vietnam" or "MUC to LAX import quote" (requests 36828, 43639), and those are quoted as always. An import is decided by
the lane: it starts at an airport that is not one of ours and ends at one of ours, and the mail says so in one
sentence ("from ... NRT ... to ... HAM"). Anything less clear stays with a person, as before.
"""
import json, re
from shared import rfq
from . import db, mailbox

TEXT = {
    "en": "%s\n\nthank you for sending this our way. I have to be straight with you: this is an import from %s into %s, and we "
          "arrange air export out of German airports. Our rate sheets and the airlines we book with only offer departures "
          "from Germany, so nobody on our side flies %s to %s, and I cannot give you a price I could stand behind.\n\n"
          "For this shipment your supplier's forwarder at origin is the right contact, since the goods are handed over at "
          "%s. If you have an export from Germany, to %s or anywhere else, send me the details and I will quote it right "
          "away.\n\nBest regards\n%s\nAir Export",
    "de": "%s\n\nvielen Dank für Ihre Anfrage. Ich sage es Ihnen offen: Das ist ein Import von %s nach %s, und wir organisieren "
          "Luftfracht-Export ab deutschen Flughäfen. Unsere Ratenblätter und die Airlines, mit denen wir buchen, bieten nur "
          "Abflüge ab Deutschland an. Die Richtung %s nach %s fliegt bei uns niemand, deshalb kann ich Ihnen keinen Preis "
          "nennen, hinter dem ich stehen könnte.\n\nFür diese Sendung ist der Spediteur Ihres Lieferanten am Abgangsort der "
          "richtige Ansprechpartner, da die Ware in %s übergeben wird. Wenn Sie einen Export ab Deutschland haben, nach %s "
          "oder anderswohin, schicken Sie mir die Daten und ich biete sofort an.\n\nViele Grüße\n%s\nLuftfracht Export",
}


def lane(fields, mail):
    """(origin, destination) when the mail clearly asks for a flight INTO one of our airports from somewhere we do not
    fly from; None for everything else (an export, a misread lane, a pickup in Germany)."""
    o, d = str(fields.get("origin") or "").upper(), str(fields.get("destination") or "").upper()
    if not (re.fullmatch(r"[A-Z]{3}", o) and re.fullmatch(r"[A-Z]{3}", d)):
        return None
    if o in rfq.known_origins() or d not in rfq.ORIGINS:         # we fly from o, or it does not end at a German airport
        return None
    if fields.get("pickup_postcode") or len(fields.get("shipments") or []) > 1:
        return None                                              # a pickup in Germany is an export with a misread lane
    text = mail.get("body") or ""
    gap = r"[^.!?\n]{0,120}"
    said = re.search(r"\b(?:from|von|ab)\b%s\b%s\b%s\b(?:to|into|nach)\b%s\b%s\b" % (gap, o, gap, gap, d), text) \
        or re.search(r"\b(?:to|into|nach)\b%s\b%s\b%s\b(?:from|von|ab)\b%s\b%s\b" % (gap, d, gap, gap, o), text)
    return (o, d) if said else None


def decline(tid, mail, fields, origin, destination):
    """One honest mail: we cannot quote this direction. No price, no bids, nothing booked."""
    from llm.extract import SIGNER
    if not db.claim_for_sending(tid):
        return db.event("quote_skipped_already_sent", tid)
    s = db.session(tid)
    lang = "de" if (fields.get("language") or "").lower().startswith("de") else "en"
    name = fields.get("customer_first_name")
    hello = (("Hallo %s," if lang == "de" else "Hi %s,") % name) if name else ("Guten Tag," if lang == "de" else "Hello,")
    body = TEXT[lang] % (hello, origin, destination, origin, destination, origin, origin, SIGNER)
    subject = s["subject"] if (s["subject"] or "").lower().startswith("re:") else "Re: " + (s["subject"] or "")
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=mail["id"], thread_id=tid)
    why = "import_declined: %s to %s comes INTO Germany, we only fly out of it. Told the customer we cannot quote it." % (origin, destination)
    db.update_session(tid, status="lost" if ok else "needs_human", note=why if ok else "import %s to %s: the decline could not be sent" % (origin, destination),
                      reply=body)
    return db.event("import_declined" if ok else "needs_human", tid, mail["id"], origin=origin, destination=destination, sent=bool(ok))
