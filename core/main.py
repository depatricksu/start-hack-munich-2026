"""The clerk: the one program that runs all night.

    DRY_RUN=1 python -m core.main                      # everyone: reads the mailbox, never sends
    DRY_RUN=0 caffeinate -i python -m core.main        # ERIK'S MACBOOK ONLY
    LLM_FAKE=1 python -m core.main --fake examples/rfq.json   # no key, no network: one fake mail

Loop: poll mailbox -> save mail -> router decides the route -> HANDLERS[route](mail).
To add a feature, write a handler in your own folder and register it in HANDLERS below.
"""
import csv, json, os, sys, time, traceback
from decimal import Decimal
from . import config, db, mailbox
from router.route import route
from llm import extract as llm
from pricing import price as sheets
from sourcing import portal

try:                       # sourcing/bids.py does not exist yet. See CLAUDE.md "How to plug in".
    from sourcing import bids
except ImportError:
    bids = None
from booking import handlers as booking                  # task 04: accept -> book -> keep the customer informed

_ZONES = os.path.join(config.ROOT, "kit", "start-kit", "pickup_zones.csv")
ZONE_AIRPORT = {r["zone"]: r["airport"] for r in csv.DictReader(open(_ZONES))}


def shipment(f):
    """Total weight and volume from the extracted fields. All math is here, not in the LLM."""
    pieces = f.get("pieces") or []
    weight = f.get("weight_kg") or sum((p.get("count") or 1) * (p.get("kg_each") or 0) for p in pieces)
    volume = f.get("volume_cbm") or sum((p.get("count") or 1) * (p.get("l_cm") or 0) * (p.get("w_cm") or 0)
                                        * (p.get("h_cm") or 0) for p in pieces) / 1e6
    return float(weight or 0), float(volume or 0)


def handle_rfq(mail):
    tid = mail["thread_id"]
    db.new_session(mail)
    age = time.time() - mail["received_at"]
    if age > config.RFQ_MAX_AGE_S:
        db.update_session(tid, status="expired", note="mail was %d s old when we saw it" % age)
        return db.event("rfq_expired", tid, mail["id"], age_s=round(age))

    fields, usage = llm.extract(mail)                       # the one gateway call
    db.event("llm", tid, mail["id"], fields=fields, usage=usage)
    postcode = str(fields.get("pickup_postcode") or "")
    if not fields.get("origin") and postcode[:2] in ZONE_AIRPORT:
        fields["origin"] = ZONE_AIRPORT[postcode[:2]]
    weight, volume = shipment(fields)
    fields["weight_kg_total"], fields["volume_cbm_total"] = weight, volume
    db.update_session(tid, fields=fields, reply_template=fields.get("reply") or "", llm_cost_usd=usage.get("cost_usd"))

    if not (fields.get("origin") and fields.get("destination") and weight > 0):
        return needs_human(tid, mail, "could not read origin, destination or weight")

    o, d = fields["origin"].upper(), fields["destination"].upper()
    options = [dict(x, total_eur=x["total"]) for x in sheets.options(o, d, weight, volume)]
    try:
        options += portal.options(o, d, weight, volume)
    except Exception as e:                                   # portal down: sheets still work
        db.event("portal_error", tid, mail["id"], error=str(e))
    db.update_session(tid, options=options)
    db.event("options", tid, mail["id"], count=len(options), options=options)

    pending = bids.request(db.session(tid), fields) if bids else 0   # mails to carriers/truckers
    if pending:
        db.update_session(tid, status="waiting_bids")
        return db.event("waiting_bids", tid, mail["id"], pending=pending, wait_s=config.BID_WAIT_S)
    if postcode:
        return needs_human(tid, mail, "door pickup needs a trucker bid, sourcing/bids.py is not built yet")
    finalize(tid)


def finalize(tid):
    """Pick the best option and send the one quote. Called right away, or when the bid wait is over."""
    s = db.session(tid)
    fields, options = json.loads(s["fields"]), json.loads(s["options"] or "[]")
    if bids and hasattr(bids, "final_options"):
        options = bids.final_options(tid, options)           # add bids, add trucker leg
    if not options:
        return needs_human(tid, None, "no price found for this lane")
    if fields.get("prefer") == "fastest":
        best = min(options, key=lambda x: (x["transit_days"], Decimal(x["total_eur"])))
    else:
        best = min(options, key=lambda x: Decimal(x["total_eur"]))
    if not db.claim_for_sending(tid):                        # someone already quoted this thread
        return db.event("quote_skipped_already_sent", tid)

    template = s["reply_template"] if "{PRICE}" in (s["reply_template"] or "") else llm.FALLBACK_REPLY
    body = (template.replace("{PRICE}", "%s %s" % (best["total"], best["currency"]))
            .replace("{AIRLINE}", best["airline"]).replace("{TRANSIT_DAYS}", str(best["transit_days"])))
    subject = s["subject"] if s["subject"].lower().startswith("re:") else "Re: " + s["subject"]
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=tid, thread_id=tid)
    now = time.time()
    db.update_session(tid, status="quoted" if ok else "failed", chosen=best, reply=body, quoted_at=now)
    db.event("quote_sent" if ok else "quote_failed", tid, chosen=best, seconds=round(now - s["received_at"], 1),
             dry_run=config.DRY_RUN)


def needs_human(tid, mail, why):
    """We do not guess: only the first quote counts. The UI shows these in red."""
    db.update_session(tid, status="needs_human", note=why)
    db.event("needs_human", tid, mail["id"] if mail else None, why=why)


def handle_carrier_bid(mail):
    if bids:
        bids.on_reply(mail)                                  # must save the bid with replied_at
    else:
        db.event("no_handler_yet", mail["thread_id"], mail["id"], route="carrier_bid")


# route -> function(mail). Routes without a handler are saved and logged, nothing more.
# TODO owners: tariff (reload sheets), ratedesk, tracking (+10), booking_confirmation
HANDLERS = {
    "rfq": handle_rfq,
    "carrier_bid": handle_carrier_bid,
    "follow_up": booking.handle_follow_up,
    "booking_confirmation": booking.handle_booking_confirmation,
}


def process(mail):
    if not db.save_mail(mail):
        return                                               # seen before (restart): never handle twice
    r = route(mail, config.OUR_ADDRESS)
    db.set_route(mail["id"], r)
    db.event("mail_in", mail["thread_id"], mail["id"], route=r, sender=mail["sender"], subject=mail["subject"])
    handler = HANDLERS.get(r)
    if not handler:
        return db.event("no_handler_yet", mail["thread_id"], mail["id"], route=r)
    try:
        handler(mail)
    except Exception as e:                                   # one bad mail must not stop the clerk
        db.event("error", mail["thread_id"], mail["id"], error=str(e), trace=traceback.format_exc()[-1500:])
        if db.session(mail["thread_id"]):
            db.update_session(mail["thread_id"], status="needs_human", note="error: %s" % e)


def tick():
    """Quote the sessions that waited long enough for bids (or have all bids in)."""
    for s in db.waiting_sessions():
        rows = db.bids_for(s["thread_id"])
        all_in = rows and all(b["replied_at"] for b in rows)
        if all_in or time.time() >= s["deadline"]:
            db.event("bid_wait_over", s["thread_id"], all_in=bool(all_in), bids=len(rows),
                     answered=sum(1 for b in rows if b["replied_at"]))
            finalize(s["thread_id"])


def run():
    if not config.API_KEY:
        sys.exit("FIVEU_API_KEY is missing. Put it in .env, or test with: LLM_FAKE=1 python -m core.main --fake examples/rfq.json")
    since = int(db.get_state("since_id", 0))
    db.event("start", dry_run=config.DRY_RUN, since_id=since, model=config.LLM_MODEL, bid_wait_s=config.BID_WAIT_S)
    while True:
        try:
            mails, nxt = mailbox.poll(since)
            for m in mails:
                process(m)
                since = max(since, m["id"])
                db.set_state("since_id", since)
            if nxt > since:
                since = nxt
                db.set_state("since_id", since)
            tick()
        except Exception as e:                               # network hiccup: log and keep going
            db.event("loop_error", error=str(e))
        time.sleep(config.POLL_S)


def run_fake(path):
    """Push one mail from a JSON file through the whole pipeline. Forces DRY_RUN."""
    config.DRY_RUN = True
    raw = json.load(open(path))
    raw.setdefault("id", int(time.time()))
    process(mailbox.normalize(raw))
    tick()
    print(json.dumps(db.session(raw["id"]), indent=2, default=str))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--fake":
        run_fake(sys.argv[2])
    else:
        run()
