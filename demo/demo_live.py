"""Live demo for the video: one shipment from the customer's first mail to "paid", played in real time.

    sh demo/run.sh             (wrapper: fresh DB, all safety env vars, then this file)

It reuses harness_ops.py (same safety: no key, DRY_RUN=1, LLM_FAKE=1, INVOICE_MAIL=0, every network call blocked,
DB inside the research folder) and its helpers. Two differences from the c-scenarios:
  - real clock: every mail is stamped "now" and carrierops runs with --now = now, so the UI shows it happening live;
  - pacing: a pause between steps (DEMO_PACE_S, default 9 s) so the screens can be filmed.
First a few background requests are fed at once (so the lists are not empty), then DEMO_START_S of quiet to start
the recording, then the hero shipment step by step. Every mail here is invented for the demo.
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
WT = os.environ.get("DEMO_WT", os.path.dirname(HERE))   # the checkout this demo/ folder lives in
OUT = os.path.join(HERE, "out")
sys.argv = [os.path.join(HERE, "harness_ops.py"), WT, "demo", OUT, WT]   # harness_ops reads its args at import
sys.path.insert(0, HERE)
import harness_ops as h  # noqa: E402  (runs all of harness_ops' safety checks and network blocks)

PACE = float(os.environ.get("DEMO_PACE_S", "9"))
START = float(os.environ.get("DEMO_START_S", "20"))
YT = h.YT


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def step(label, fn, pause=None):
    """One visible step: do it, report it, then wait so the UI has time to show it."""
    s = fn()
    outs = [m.get("to") for m in (s.get("mails_out") or [])]
    drafts = len(s.get("drafts") or [])
    say("%-58s %s%s" % (label, ("-> " + ", ".join(outs)) if outs else "", (" | %d drafts" % drafts) if drafts else ""))
    if s.get("harness_error"):
        say("   HARNESS ERROR: " + s["harness_error"].strip().splitlines()[-1])
    time.sleep(PACE if pause is None else pause)
    return s


def dispatch():
    """Demo only: carrierops' drafts count as sent (logged as mail_out with demo_dispatch, nothing leaves the Mac).
    Live, carrierops only writes drafts; here every draft with an address goes out at once, and the customer counts as
    informed, so the screens show "Relay told the customer" as they would with sending switched on."""
    con = h.db.con()
    rows = con.execute("SELECT id, thread_id, party, to_addr, subject, reason, body FROM outbox "
                       "WHERE status='draft' AND COALESCE(to_addr,'')<>'' ORDER BY id").fetchall()
    for r in rows:
        oid, tid, party, to, subject, reason, body = r
        # logged as "mail_out" (what a sent mail looks like in the log; the bell and Shipments read it), marked as demo
        h.db.event("mail_out", thread_id=tid, to=to, subject=subject, body=body, demo_dispatch=reason, sent=False)
        if party == "customer":
            h.db.event("customer_informed", thread_id=tid, message=reason)
        con.execute("UPDATE outbox SET status='sent' WHERE id=?", (oid,))
    con.commit()
    return len(rows)


def co_now(label, tid, args=None):
    s = h.co(label, time.time(), tid, args)
    s["dispatched"] = dispatch()
    return s


def carrier_now(label, tid, r):
    """Mail through the clerk (stored as live), then carrierops at the real clock."""
    h.feed(label, r, tid)
    return co_now("carrierops after: " + label, tid)


# ------------------------------------------------------------------ background: a normal morning, fed at once
BACKGROUND = [
    (61101, "j.weber@rheintal-elektronik.de", "Rate request MUC to PEK",
     "Hello,\n\nplease quote air freight from Munich (MUC) to Beijing (PEK).\n4 cartons of electronic modules, "
     "320 kg, 1.6 cbm, general cargo. We deliver to MUC ourselves. Cheapest option please.\n\nThanks\nJonas Weber"),
    (61102, "s.kaya@auer-maschinenbau.de", "Air freight HAM - DXB, 300 kg",
     "Hi,\n\ncould you quote HAM to DXB, 300 kg, 1.5 cbm, spare parts, delivered to Hamburg airport by us?\n"
     "Fastest option please.\n\nRegards\nSelin Kaya"),
    (61103, "m.lindqvist@lindqvist-medtech.se", "Quote FRA to JFK",
     "Hello,\n\nwe need a price for FRA to JFK: 2 pallets of medical device housings, 300 kg, 1.5 cbm, "
     "non-dangerous. Delivered to FRA by us.\n\nBest\nMaja Lindqvist"),
    (61104, "t.auer@nordlicht-audio.de", "Luftfracht FRA - NBO",
     "Guten Tag,\n\nbitte ein Angebot für Luftfracht FRA nach Nairobi (NBO): 300 kg, 1,5 cbm, Lautsprecherteile. "
     "Wir liefern selbst zum Flughafen FRA. Günstigste Option.\n\nViele Grüße\nTobias Auer"),
]


def background():
    for i, (tid, cust, subj, body) in enumerate(BACKGROUND):
        r = h.raw(tid, cust, subj, body)
        r["created_at"] = time.time() - (95 - 12 * i)   # they came in a minute or two ago, so "time to quote" is real
        h.feed("background RFQ %d" % tid, r, tid)
        h.call("tick", tid, h.main.tick)
    # one of them says yes and gets booked + confirmed, so Shipments has a second line
    tid, cust = 61104, "t.auer@nordlicht-audio.de"
    s = h.db.session(tid)
    h.feed("background: customer accepts", h.raw(tid + 10, cust, "Re: " + s["subject"],
           "Hallo,\n\npasst, bitte buchen.\n\nViele Grüße\nTobias Auer", thread=tid), tid)
    ch = json.loads(h.db.session(tid)["chosen"] or "{}")
    h.feed("background: airline confirms", h.confirmation(tid, "BK-8RW2N5TA", ch.get("airline"), YT,
           ch.get("flight_total") or ch.get("total"), tid + 200, lane="FRA-NBO"), tid)
    co_now("background: carrierops pass", tid)
    for tid, *_ in BACKGROUND:
        say("background %d: %s" % (tid, h.db.session(tid)["status"]))


# ------------------------------------------------------------------ the hero shipment
TID, CUST, BK, AWB = 61201, "lena.hoffmann@hoffmann-feinwerk.de", "BK-5TQ8M2LC", "160-61201007"
SIGN = "Lena Hoffmann\nHoffmann Feinwerk GmbH"


def hero():
    rfq = h.raw(TID, CUST, "Quote request: pickup Offenbach to Chicago ORD, 420 kg",
                "Hello,\n\nplease quote air freight to Chicago O'Hare (ORD).\n"
                "Pickup at our plant: 63067 Offenbach am Main, Hafenstrasse 12.\n"
                "3 pallets of precision gears, 420 kg total, 2.2 cbm, not stackable, general cargo.\n"
                "Ready from Monday. We would like the cheapest option, all-in in EUR.\n\n"
                "Best regards\n" + SIGN)
    step("1. customer request arrives (door pickup Offenbach -> ORD)", lambda: h.feed("RFQ from customer (door pickup)", rfq, TID))

    # truckers answer the pickup bids Relay sent out
    bids = [b for b in h.bids_of(TID) if b["role"] == "trucker"]
    prices = [(178.50, 20), (204.00, 24)]
    for n, b in enumerate(bids):
        sub = h.db.con().execute("SELECT data FROM events WHERE kind='bid_mail_out_dry_run' AND data LIKE ?",
                                 ("%%[BID-%d]%%" % b["id"],)).fetchone()
        subject = json.loads(sub[0])["subject"] if sub else "Pickup [BID-%d]" % b["id"]
        price, hours = prices[n % len(prices)]
        body = ("Hello,\n\nthank you for the request. Our all-in price for this pickup in Offenbach is %.2f EUR, "
                "collection within %d hours of your order, delivery to the FRA cargo terminal the same day.\n\n"
                "Kind regards\n%s Dispatch" % (price, hours, b["carrier"]))
        step("2. trucker answers: %s (%.2f EUR)" % (b["carrier"], price),
             lambda b=b, subject=subject, body=body, n=n: h.feed("trucker answers: %s" % b["carrier"],
                                                                h.raw(TID + 100 + n, b["email"], "Re: " + subject, body), TID))
    # the quote went out with the last trucker answer; this tick only closes the bid wait (no extra pause on camera)
    step("3. bid wait closed (quote already out)", lambda: h.call("tick (bid wait over)", TID, h.main.tick), pause=0)

    subj = h.db.session(TID)["subject"]
    step("4. customer says yes -> Relay books with the airline",
         lambda: h.feed("customer accepts", h.raw(TID + 110, CUST, "Re: " + subj,
                        "Hi,\n\nthanks for the quick offer, that works for us. Please book it.\n\nBest regards\n" + SIGN,
                        thread=TID), TID))

    ch = json.loads(h.db.session(TID)["chosen"] or "{}")
    conf = h.confirmation(TID, BK, ch.get("airline"), YT, ch.get("flight_total") or ch.get("total"), TID + 200)
    conf["body"] = conf["body"].replace("Status: booked", "AWB: %s\nStatus: booked" % AWB)
    step("5. airline confirms the booking", lambda: h.feed("airline confirms booking", conf, TID))
    step("6. Relay informs the customer, trucker, airline; invoice written", lambda: co_now("carrierops pass 1 (step 6)", TID))

    chosen_trucker = next((b for b in h.bids_of(TID) if b["role"] == "trucker" and b.get("status") == "chosen"), None) \
        or next((b for b in bids if b["carrier"] in json.dumps(h.db.session(TID)["chosen"] or "")), bids[0] if bids else None)
    t_mail = chosen_trucker["email"] if chosen_trucker else "westfalenroute@hackloop.mail"
    t_name = chosen_trucker["carrier"] if chosen_trucker else "Westfalenroute"
    step("7. trucker: picked up and handed over at FRA",
         lambda: carrier_now("trucker: picked up", TID, h.raw(TID + 301, t_mail,
                             "Re: Pickup order GOOGLE-%d" % TID,
                             "Hello,\n\npicked up today at Hoffmann Feinwerk, Offenbach, 3 pallets, and delivered to the "
                             "Yellowtail cargo terminal FRA. Receipt attached.\n\n%s Dispatch" % t_name)))
    step("8. airline: departed",
         lambda: carrier_now("airline: departed", TID, h.raw(TID + 302, YT, "Booking %s - departed" % BK,
                             "Dear partner,\n\nshipment %s / GOOGLE-%d departed today on flight YT 880 FRA-ORD, AWB %s.\n"
                             "Track: https://track.yellowtail.example/%s\n\nYellowtail Air Freight Operations"
                             % (BK, TID, AWB, AWB))))
    step("9. airline: DELAYED (aircraft change, new ETA)",
         lambda: carrier_now("airline: delayed", TID, h.raw(TID + 303, YT, "Booking %s - DELAYED" % BK,
                             "Dear partner,\n\ndue to an aircraft change your shipment %s (your ref GOOGLE-%d) was moved "
                             "from YT 880 to YT 4412. New ETA ORD is one day later than planned.\n"
                             "We apologise for the inconvenience.\n\nYellowtail Air Freight Operations" % (BK, TID))),
         pause=PACE * 1.5)
    step("10. customer asks: where is my shipment?",
         lambda: carrier_now("customer: where is my shipment", TID, h.raw(TID + 304, CUST, "Re: " + subj,
                             "Hi,\n\nwhere is our shipment now? When will it arrive in Chicago?\n\nThanks\nLena", thread=TID)))
    step("11. airline: arrived ORD",
         lambda: carrier_now("airline: arrived", TID, h.raw(TID + 305, YT, "Booking %s - arrived ORD" % BK,
                             "Shipment %s / GOOGLE-%d arrived ORD on YT 4412. Ready for pickup by the consignee.\n\n"
                             "Yellowtail Air Freight Operations" % (BK, TID))))
    step("12. airline: delivered, POD",
         lambda: carrier_now("airline: delivered", TID, h.raw(TID + 306, YT, "Booking %s - delivered, POD attached" % BK,
                             "Shipment %s delivered to the consignee, signed by J. Miller. POD attached.\n\n"
                             "Yellowtail Air Freight Operations" % BK)))
    step("13. customer: we have paid",
         lambda: carrier_now("customer: we have paid", TID, h.raw(TID + 307, CUST, "Re: " + subj,
                             "Hello,\n\nwe have paid the invoice today by bank transfer.\n\nBest regards\n" + SIGN, thread=TID)))
    def paid():
        h.invoice.mark_paid(str(TID))        # the clerk's invoice (what Invoices and Shipments show)
        return co_now("forwarder: --mark-paid INV-%d" % TID, TID, ["--mark-paid", "INV-%d" % TID])   # carrierops' copy
    step("14. money is in the bank: invoice marked paid", paid, pause=0)


if __name__ == "__main__":
    say("DB: %s" % h.dbp)
    background()
    say("background ready. Hero shipment starts in %.0f s: open the UI and start recording." % START)
    time.sleep(START)
    hero()
    os.makedirs(OUT, exist_ok=True)
    json.dump({"steps": h.STEPS, "network_attempts": h.BLOCKED}, open(os.path.join(OUT, "demo.json"), "w"), indent=1, default=str)
    say("done. network attempts: %d, harness errors: %d. Log: %s" % (
        len(h.BLOCKED), sum(1 for s in h.STEPS if s.get("harness_error")), os.path.join(OUT, "demo.json")))
