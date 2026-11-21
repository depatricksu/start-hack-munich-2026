"""The clerk: the one program that runs all night.

    DRY_RUN=1 python -m core.main                      # everyone: reads the mailbox, never sends
    DRY_RUN=0 caffeinate -i python -m core.main        # ERIK'S MACBOOK ONLY
    LLM_FAKE=1 python -m core.main --fake examples/rfq.json   # no key, no network: one fake mail

Loop: poll mailbox -> save mail -> router decides the route -> HANDLERS[route](mail).
To add a feature, write a handler in your own folder and register it in HANDLERS below.
"""
import csv, json, os, re, sys, time, traceback
from decimal import Decimal
from . import config, db, mailbox, safety
from router.route import route
from llm import extract as llm
from pricing import price as sheets
from sourcing import portal
from actions import queue as actions            # take-over queue: sends human replies typed in the UI
from shared.rfq import gate as rfq_gate
from pricing import multi, tariff_mail
from llm import clarify

from sourcing import bids                               # truckers, rare lanes, rate desk: prices by mail (Kai)
from booking import tracking
from booking import handlers as booking                 # task 04: accept -> book -> keep the customer informed

_ZONES = os.path.join(config.ROOT, "kit", "start-kit", "pickup_zones.csv")
ZONE_AIRPORT = {r["zone"]: r["airport"] for r in csv.DictReader(open(_ZONES))}


NULLISH = {"", "null", "none", "n/a", "na", "unknown", "nil"}


def _airport(v):
    """A clean IATA code, or None. The model sometimes returns the string 'NULL' instead of a real null,
    which must NOT block deriving the airport from the pickup postcode (live bug 21 Nov: round 10 lost)."""
    v = str(v or "").strip()
    return None if v.lower() in NULLISH else v.upper()


def shipment(f):
    """Total weight and volume. Several lots can arrive split: a total in weight_kg AND more lots in pieces that
    carry their own kg_each. We ADD the piece weights the model gave on top of weight_kg so we never under-count
    (live bug 21 Nov: round 9 priced 730 of 1952 kg -> rejected 'too_low'). Pieces with only dimensions (kg_each
    null) add volume, not weight, so the normal single-shipment case is unchanged."""
    pieces = f.get("pieces") or []
    pieces_kg = sum((p.get("count") or 1) * (p.get("kg_each") or 0) for p in pieces)
    pieces_cbm = sum((p.get("count") or 1) * (p.get("l_cm") or 0) * (p.get("w_cm") or 0) * (p.get("h_cm") or 0)
                     for p in pieces) / 1e6
    weight = float(f.get("weight_kg") or 0) + pieces_kg
    volume = float(f.get("volume_cbm") or 0) + pieces_cbm
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
    fields["origin"] = _airport(fields.get("origin"))        # the string "NULL" must not block zone->airport
    fields["destination"] = _airport(fields.get("destination"))
    postcode = str(fields.get("pickup_postcode") or "")
    if not fields.get("origin") and postcode[:2] in ZONE_AIRPORT:
        fields["origin"] = ZONE_AIRPORT[postcode[:2]]
    weight, volume = shipment(fields)
    fields["weight_kg_total"], fields["volume_cbm_total"] = weight, volume
    db.update_session(tid, fields=fields, reply_template=fields.get("reply") or "", llm_cost_usd=usage.get("cost_usd"))
    price_and_quote(tid, mail, fields)


def price_and_quote(tid, mail, fields, asked=False):
    """Everything after the gateway call. Also re-entered by llm/clarify.py when the customer answered our question."""
    postcode = str(fields.get("pickup_postcode") or "")
    weight, volume = fields.get("weight_kg_total") or 0, fields.get("volume_cbm_total") or 0
    if len(fields.get("shipments") or []) > 1:               # several shipments in one mail (pricing/multi.py, Patrick)
        return multi.handle(tid, mail, fields)
    ok, note = rfq_gate(fields, mail)                       # shared/rfq.py (Patrick): stop or warn, with reason codes
    db.event("gate", tid, mail["id"], ok=ok, note=note)
    if not ok:
        missing = clarify.only_missing(fields, mail)
        if missing and not asked and config.CLARIFY:         # only data is missing: ask the customer once (Erik)
            return clarify.ask(tid, mail, fields, missing)
        return needs_human(tid, mail, note)
    if note:
        db.update_session(tid, note=note)                    # warnings only, we still quote

    if not (fields.get("origin") and fields.get("destination") and weight > 0):
        return needs_human(tid, mail, "could not read origin, destination or weight")
    if weight > 100_000 or not (0 <= volume <= 1000):         # portal limits: never quote outside them
        return needs_human(tid, mail, "weight %s kg / volume %s cbm out of range" % (weight, volume))

    o, d = fields["origin"], fields["destination"]           # already clean IATA from _airport()
    options = [dict(x, total_eur=x["total"]) for x in sheets.options(o, d, weight, volume)]
    try:
        options += portal.options(o, d, weight, volume)
    except Exception as e:                                   # portal down: sheets still work
        db.event("portal_error", tid, mail["id"], error=str(e))
    db.update_session(tid, options=options)
    db.event("options", tid, mail["id"], count=len(options), options=options)

    pending = bids.request(db.session(tid), fields)          # mails to carriers/truckers
    if pending:
        db.update_session(tid, status="waiting_bids")
        return db.event("waiting_bids", tid, mail["id"], pending=pending, wait_s=config.BID_WAIT_S)
    if postcode:                                             # door pickup but nobody to ask
        return needs_human(tid, mail, "door_pickup: no trucker serves postcode zone %s" % postcode[:2])
    finalize(tid)


def quote_in_eur(best):
    """Customers ask for an all-in price in EUR. A portal option may come in USD: quote its EUR value, keep the original.
    Turn off with QUOTE_EUR=0."""
    if not config.QUOTE_EUR or best.get("currency", "EUR") == "EUR" or not best.get("total_eur"):
        return best
    if best.get("fx_missing"):                               # no exchange rate came with the price: total_eur is NOT in EUR
        return best                                          # quote the original number in the original currency
    return dict(best, original_total=best["total"], original_currency=best["currency"],
                total=str(Decimal(best["total_eur"]).quantize(Decimal("0.01"))), currency="EUR")


def finalize(tid):
    """Pick the best option and send the one quote. Called right away, or when the bid wait is over."""
    s = db.session(tid)
    fields, options = json.loads(s["fields"]), json.loads(s["options"] or "[]")
    options = bids.final_options(tid, options)               # add bids, add trucker leg
    if not options:
        return needs_human(tid, None, "no price found for this lane")
    if fields.get("prefer") == "fastest":
        best = min(options, key=lambda x: (x["transit_days"], Decimal(x["total_eur"])))
    else:
        best = min(options, key=lambda x: Decimal(x["total_eur"]))
    best = quote_in_eur(best)
    if not db.claim_for_sending(tid):                        # someone already quoted this thread
        return db.event("quote_skipped_already_sent", tid)

    body, why = llm.final_reply(s["reply_template"], best, fields, s["customer"], tid)   # llm/: filled + quality gate
    if why:                                                  # the model's text failed the gate: our own template went out
        db.event("reply_gate", tid, reasons=why, language=fields.get("language"))
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
    bids.on_reply(mail)                                      # reads the answer and saves it; tick() quotes


# route -> function(mail). Routes without a handler are saved and logged, nothing more.
# TODO owners: tariff (reload sheets), ratedesk, tracking (+10), booking_confirmation
HANDLERS = {
    "rfq": handle_rfq,
    "carrier_bid": handle_carrier_bid,
    "ratedesk": handle_carrier_bid,                      # the rate desk answers like a carrier (sourcing/bids.py)
    "follow_up": booking.handle_follow_up,
    "booking_confirmation": booking.handle_booking_confirmation,
    "tracking": tracking.handle,                         # task 05 (Patrick): answer from our bookings table
    "tariff": tariff_mail.handle,                        # Patrick: airline tariff mail -> live price update
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
    """Quote the sessions that waited long enough for bids (or have all needed bids in)."""
    for s in db.waiting_sessions():
        tid, now = s["thread_id"], time.time()
        rows = [b for b in bids.rows(tid) if b["required"]]
        all_in = all(b["replied_at"] for b in rows)
        if not all_in and now < s["deadline"]:
            continue
        if not all_in and bids.must_wait(tid) and now < s["received_at"] + config.BID_MAX_WAIT_S:
            continue                                         # a needed leg is missing: late quote beats no quote
        db.event("bid_wait_over", tid, all_in=bool(all_in), bids=len(rows),
                 answered=sum(1 for b in rows if b["replied_at"]), waited_s=round(now - s["received_at"], 1))
        try:
            finalize(tid)
        except Exception as e:                               # never loop forever on one broken session
            db.event("error", tid, error=str(e), trace=traceback.format_exc()[-1500:])
            db.update_session(tid, status="needs_human", note="error: %s" % e)


def run():
    if not config.API_KEY:
        sys.exit("FIVEU_API_KEY is missing. Put it in .env, or test with: LLM_FAKE=1 python -m core.main --fake examples/rfq.json")
    safety.lock()                                            # only ONE clerk per database, or mails go out twice
    since = int(db.get_state("since_id", 0))
    commit = safety.commit()
    db.set_state("commit", commit)
    db.set_state("started_at", time.time())
    db.set_state("supervised", "1" if safety.SUPERVISED else "0")
    db.event("start", dry_run=config.DRY_RUN, since_id=since, model=config.LLM_MODEL, bid_wait_s=config.BID_WAIT_S,
             commit=commit, supervised=safety.SUPERVISED)
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
            actions.tick()                                   # human replies from the UI (actions/queue.py)
            db.set_state("heartbeat", time.time())           # the UI can show "clerk alive" from this
        except Exception as e:                               # network hiccup: log and keep going
            db.event("loop_error", error=str(e))
        if safety.restart_wanted():                          # asked by `python3 -m core.restart`, between two turns
            db.event("restart", commit=commit)
            sys.exit(0)                                      # core/supervise.py starts the new code
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
