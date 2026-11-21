"""Sort every mail into one route. Rules only, no LLM: we know every sender.

Routes: rfq, follow_up, carrier_bid, tariff, ratedesk, tracking, booking_confirmation, own, spam

spam: a new thread with spam/phishing words and no sign of a freight request, or a vendor's sales pitch with no
shipment in it. It has no handler, so it is only saved and logged: no session, no needs_human, no reply. Kept strict
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


def route(mail, our_address="google@hackloop.mail"):
    sender, subject = mail["sender"], mail["subject"].lower()
    if sender == our_address:
        return "own"
    if sender == "tracking@hackloop.mail":                    # exact: tracking@evil.mail is a customer. FIRST: a tracking
        return "tracking"                                    # question 'Status of booking BK-...' is not a confirmation
    if re.search(r"booking\s+bk-", subject):
        return "booking_confirmation"
    if sender == "ratedesk@hackloop.mail":
        return "ratedesk"
    if sender in CARRIERS:
        if mail["attachments"] or "tariff" in subject or "rate sheet" in subject:
            return "tariff"
        return "carrier_bid"
    # anyone else is a customer
    if mail["is_thread_start"]:
        text = mail["subject"] + "\n" + mail["body"]
        if SPAM.search(text) and not FREIGHT.search(text):
            return "spam"
        if PITCH.search(text) and not SHIPMENT.search(text) and not mail.get("attachments"):
            return "spam"                                    # a sales pitch with no shipment in it: never a reply
        return "rfq"
    return "follow_up"
