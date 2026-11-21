"""Sort every mail into one route. Rules only, no LLM: we know every sender.

Routes: rfq, follow_up, carrier_bid, tariff, ratedesk, tracking, booking_confirmation, own, spam

spam: a new thread with spam/phishing words and no sign of a freight request. It has no handler, so it is only
saved and logged: no session, no needs_human, no reply. Kept strict so a real RFQ is never dropped.
"""
import csv, os, re

_KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "start-kit")
SPAM = re.compile(r"\b(you('ve| have)? won|winner|prize|lottery|gewinnspiel|gewonnen|click here|klicken sie hier|"
                  r"claim your|gift ?card|bitcoin|crypto|investment opportunit\w*|earn \$|make money|viagra|casino|"
                  r"verify your (account|password)|password|api key|login details|bank details|wire transfer|"
                  r"unsubscribe|newsletter|seo services|backlinks)\b", re.I)
FREIGHT = re.compile(r"\b(\d[\d.,]*\s*(kg|kgs|lbs?|t|tons?|tonnen|cbm|m3)|quote|quotation|rfq|rate|freight|shipment|"
                     r"cargo|pallets?|airport|angebot|fracht|sendung|paletten|cotizaci\w+|devis|[A-Z]{3}\s*(-|to|nach|->)\s*[A-Z]{3})\b",
                     re.I)
CARRIERS = {r["email"].lower(): r for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv")))}


def route(mail, our_address="google@hackloop.mail"):
    sender, subject = mail["sender"], mail["subject"].lower()
    if sender == our_address:
        return "own"
    if re.search(r"booking\s+bk-", subject):
        return "booking_confirmation"
    if sender == "tracking@hackloop.mail":                    # exact: tracking@evil.mail is a customer
        return "tracking"
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
        return "rfq"
    return "follow_up"
