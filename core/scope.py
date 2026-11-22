"""A request for a service we do not offer. We arrange AIR freight out of German airports.

5U, 22 Nov 09:50 (request 53351): "an all-in price in EUR for a port-to-port sea freight shipment from Hamburg (DEHAM)
to Jebel Ali (AEJEA)? ... an FCL shipment in 1 x 40ft container, with 6 pieces, a gross weight of 9617 kg and a total
volume of 43.5 cbm." The gate stopped it (nobody serves AEJEA) and left it for a person. An honest "we cannot quote
this" at 31 s was the right answer: 5U counted the round as accepted, the customer wrote "Understood, thanks for
letting me know." (Same as the import at 08:01, core/imports.py.)

Sea freight is decided by the mail's own words (sea or ocean freight, FCL, LCL, a 20 or 40 ft container, port to
port) and only when nothing in it speaks of air freight, an airport or a flight. "We used to ship this by sea, please
quote air freight" is an air request and is quoted as always.
"""
import re
from . import db, mailbox

SEA = re.compile(r"\b(?:sea[- ]?freight|ocean[- ]?freight|seefracht|by (?:sea|vessel|ship)\b|per (?:schiff|see)\b|fcl\b|lcl\b|"
                 r"port[- ]to[- ]port|(?:20|40|45)\s*(?:ft|foot|['’])\s*(?:hc\s*|high cube\s*)?container|"
                 r"\d+\s*x\s*(?:20|40|45)\s*(?:ft|foot|['’])|shipping line|bill of lading|konnossement)", re.I)
AIR = re.compile(r"\b(?:air[- ]?freight|air cargo|air export|air import|by air\b|luftfracht|airport|flughafen|flights?\b|fly\b|airlines?\b)", re.I)

TEXT = {
    "en": "%s\n\nthank you for thinking of us. I have to be straight with you: this is a sea freight shipment, a container from port to "
          "port, and we arrange air freight out of German airports. We have no ocean rates and no container space, so I cannot give "
          "you a price I could stand behind.\n\nFor the container, an ocean forwarder or the shipping line is the right contact. If "
          "any of it needs to fly, send me the details and I will quote it right away.\n\nBest regards\n%s\nAir Export",
    "de": "%s\n\nvielen Dank, dass Sie an uns denken. Ich sage es Ihnen offen: Das ist eine Seefracht-Sendung, ein Container von Hafen "
          "zu Hafen, und wir organisieren Luftfracht ab deutschen Flughäfen. Wir haben keine Seefrachtraten und keinen "
          "Containerplatz, deshalb kann ich Ihnen keinen Preis nennen, hinter dem ich stehen könnte.\n\nFür den Container ist ein "
          "Seefrachtspediteur oder die Reederei der richtige Ansprechpartner. Wenn ein Teil davon fliegen soll, schicken Sie mir "
          "die Daten und ich biete sofort an.\n\nViele Grüße\n%s\nLuftfracht Export",
}


def sea(mail):
    """True when the mail asks for sea freight and nothing in it speaks of air freight."""
    text = "%s\n%s" % (mail.get("subject") or "", mail.get("body") or "")
    return bool(SEA.search(text)) and not AIR.search(text)


def decline_sea(tid, mail, fields):
    """One honest mail: we do not do sea freight. No price, no bids, nothing booked."""
    from llm.extract import SIGNER
    if not db.claim_for_sending(tid):
        return db.event("quote_skipped_already_sent", tid)
    s = db.session(tid)
    lang = "de" if (fields.get("language") or "").lower().startswith("de") else "en"
    name = fields.get("customer_first_name")
    hello = (("Hallo %s," if lang == "de" else "Hi %s,") % name) if name else ("Guten Tag," if lang == "de" else "Hello,")
    body = TEXT[lang] % (hello, SIGNER)
    subject = s["subject"] if (s["subject"] or "").lower().startswith("re:") else "Re: " + (s["subject"] or "")
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=mail["id"], thread_id=tid)
    db.update_session(tid, status="lost" if ok else "needs_human", reply=body,
                      note="sea_freight_declined: the customer asks for sea freight, we only do air. Told them we cannot quote it." if ok
                      else "sea freight request: the decline could not be sent")
    return db.event("sea_freight_declined" if ok else "needs_human", tid, mail["id"], sent=bool(ok))
