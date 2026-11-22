"""Sort every mail into one route. Rules only, no LLM: we know every sender.

Routes: rfq, follow_up, carrier_bid, tariff, ratedesk, tracking, booking_confirmation, own, spam

spam: a new thread with spam/phishing words and no sign of a freight request, a vendor's sales pitch with no
shipment in it, or a sender whose address imitates a customer we know (lookalike()). It has no handler, so it is only saved and logged: no session, no needs_human, no reply. Kept strict
so a real RFQ is never dropped: when in doubt the mail stays "rfq", the gateway call reads it, and a mail that is not
clearly a freight request ends in needs_human for a person to decide.
"""
import csv, os, re

_KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "start-kit")
SPAM = re.compile(r"\b(you('ve| have)? won|winner|prize|lottery|gewinnspiel|gewonnen|click here|klicken sie hier|"
                  r"claim your|gift ?card|bitcoin|crypto|investment opportunit\w*|earn \$|make money|viagra|casino|"
                  r"verify your (account|password)|password|api key|login details|bank details|wire transfer|"
                  r"unsubscribe|newsletter|seo services|backlinks)\b", re.I)
FREIGHT = re.compile(r"\b(\d[\d.,]*\s*(kg|kgs|kilos?|kilograms?|lbs?|t|tons?|tonnen|cbm|m3)|quote|quotation|rfq|rate|freight|shipment|"
                     # red-team #62, #63: "60 kilos", "4 boxes", "we need to fly an engine to Mexico City" are requests
                     r"ship|shipping|fly|flight|air\s?freight|luftfracht|boxes|cartons|crates|versand|spedizione|envío|"
                     r"cargo|pallets?|airport|angebot|fracht|sendung|paletten|cotizaci\w+|devis|[A-Z]{3}\s*(-|to|nach|->)\s*[A-Z]{3})\b",
                     re.I)
# A vendor selling to US (5U 21:21: "FreightSoft Pro answers every RFQ in under 60 seconds, book 15 minutes for a
# demo?"). It talks about quotes and RFQs, so FREIGHT matches; what it never has is a shipment. Rule from Erik: no
# reply to cold mail, ignore phishing, reply only to freight requests, and when unsure a person decides. So this is
# spam only with a sales phrase AND no weight, volume, lane, postcode or attachment; anything else goes on to the
# gateway call, and what that cannot place goes to needs_human.
PITCH = re.compile(r"\b(book(ing)? (a |an )?(\d+ )?(minutes?|mins?|call|demo|meeting)|show you (a|our) demo|"
                   r"(quick|short|free|live|\d+[- ]minute) (demo|trial)|free trial|schedule a (call|demo|meeting)|"
                   r"account executive|sales (rep\w*|team|manager|development)|"
                   r"our (platform|software|tool|solution|product)|case stud(y|ies)|pricing plans?|"
                   r"partnership opportunit\w*)\b", re.I)
SHIPMENT = re.compile(r"(?i:\d[\d.,]*\s*(?:kg|kgs|lbs?|tons?|tonnen|cbm|m3|m³)\b)"
                      r"|\b[A-Z]{3}\s*(?:-|to|nach|->)\s*[A-Z]{3}\b|\b\d{5}\b")
CARRIERS = {r["email"].lower(): r for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv")))}


# 'Undelivered Mail Returned to Sender ... [BID-152]' from mailer-daemon@ was routed as a new request: one gateway call
# and a quote sent to the daemon (Patrick's red-team run, 21 Nov 23:29).
BOUNCE_SENDER = re.compile(r"^(?:mailer-daemon|postmaster|mail-daemon|bounces?|no-?reply-bounce)[^@]*@", re.I)
BOUNCE_SUBJECT = re.compile(r"undelivered mail|undeliverable|delivery status notification|mail delivery (?:failed|failure|subsystem)|"
                            r"returned mail|delivery failure|failure notice|nicht zustellbar|unzustellbar", re.I)


# 5U, 22 Nov 02:32: "our usual mailbox has been down since this morning ... could you confirm your price for our shipment
# to Bangkok to this address" from nordlicht.audio@hackloop.mail. Our customer is nordlicht-audio@hackloop.mail (a hyphen).
# A sender that is almost, but not exactly, a customer we know is an impostor: no reply, no price, nothing from the
# real customer's history.
_SWAP = str.maketrans({"0": "o", "1": "l", "i": "l", "5": "s", "3": "e", "4": "a", "7": "t", "8": "b"})


def _canon(part):
    return re.sub(r"[._\-+]", "", part.lower()).replace("rn", "m").replace("vv", "w").translate(_SWAP)


def _distance(a, b, cap=3):
    """Edit distance, capped (small strings: a plain table is enough)."""
    if abs(len(a) - len(b)) >= cap:
        return cap
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return min(prev[-1], cap)


def lookalike(sender, known):
    """-> the known customer address this sender imitates, or None. Exactly a known address is never an imitation."""
    sender = (sender or "").lower()
    known = {k.lower() for k in known or () if k}
    if "@" not in sender or sender in known:
        return None
    local, domain = sender.rsplit("@", 1)
    for k in sorted(known):
        if "@" not in k:
            continue
        kl, kd = k.rsplit("@", 1)
        same_name = _canon(local) == _canon(kl)
        numbered = re.sub(r"\d", "", local) == re.sub(r"\d", "", kl)       # buyer1@ and buyer2@ are two mailboxes, not a fake
        if domain == kd and (same_name or (len(kl) >= 8 and not numbered and _distance(local, kl) == 1)):
            return k                                         # nordlicht.audio@ / nordlicht-audi0@ / nordlich-audio@ for nordlicht-audio@
        if domain != kd and same_name and len(kl) >= 6 and len(kd) >= 8 and (_canon(domain) == _canon(kd) or _distance(domain, kd) <= 2):
            return k                                         # the same name on hackl00p.mail or hackloop.mall
    return None


def route(mail, our_address="google@hackloop.mail", customers=None):
    sender, subject = mail["sender"], mail["subject"].lower()
    if sender == our_address:
        return "own"
    if BOUNCE_SENDER.search(sender) or BOUNCE_SUBJECT.search(subject):   # never a request: no gateway call, no quote to a daemon
        return "bounce"
    if sender == "tracking@hackloop.mail":                    # exact: tracking@evil.mail is a customer. FIRST: a tracking
        return "tracking"                                    # question 'Status of booking BK-...' is not a confirmation
    if re.search(r"booking\s+bk-", subject):
        return "booking_confirmation"
    if sender == "ratedesk@hackloop.mail":
        return "ratedesk"
    if sender in CARRIERS:
        if re.search(r"\[bid-\d+\]", subject):               # the answer to OUR bid mail. 5U 22:17: truckers send the price
            return "carrier_bid"                             # as a file (PDF, Word, text, voice): still a bid, not a tariff
        if mail["attachments"] or "tariff" in subject or "rate sheet" in subject:
            return "tariff"
        return "carrier_bid"
    # anyone else is a customer
    if mail["is_thread_start"]:
        if lookalike(sender, customers):                     # an address that imitates a customer we know: never a reply
            return "spam"
        text = mail["subject"] + "\n" + mail["body"]
        if SPAM.search(text) and not FREIGHT.search(text):
            return "spam"
        if PITCH.search(text) and not SHIPMENT.search(text) and not mail.get("attachments"):
            return "spam"                                    # a sales pitch with no shipment in it: never a reply
        return "rfq"
    return "follow_up"
