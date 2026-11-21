"""Sort every mail into one route. Rules only, no LLM: we know every sender.

Routes: rfq, follow_up, carrier_bid, tariff, ratedesk, tracking, booking_confirmation, own
"""
import csv, os, re

_KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "start-kit")
CARRIERS = {r["email"].lower(): r for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv")))}


def route(mail, our_address="google@hackloop.mail"):
    sender, subject = mail["sender"], mail["subject"].lower()
    if sender == our_address:
        return "own"
    if re.search(r"booking\s+bk-", subject):
        return "booking_confirmation"
    if sender.startswith("tracking@"):
        return "tracking"
    if sender.startswith("ratedesk@"):
        return "ratedesk"
    if sender in CARRIERS:
        if mail["attachments"] or "tariff" in subject or "rate sheet" in subject:
            return "tariff"
        return "carrier_bid"
    # anyone else is a customer
    return "rfq" if mail["is_thread_start"] else "follow_up"
