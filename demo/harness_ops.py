"""Offline start-to-end freight simulation through the real clerk code, EXTENDED with carrierops (copy of harness.py).

Run (one scenario per process, own fresh DB):
    python3 harness_ops.py <worktree> <scenario> <outdir> [<repo with carrierops/>]

s1..s7 are the original scenarios (unchanged) plus one carrierops catch-up pass at the end.
c1..c8 run steps 1-5 through the clerk, then feed carrier/customer mails through the clerk (so the clerk stores them
the way it does live) and run `carrierops.run --once --now T` in-process after each mail, with an advancing clock.
carrierops is imported from the repo checkout (it is not on origin/main) and is covered by the same network block.

Safety: refuses to run unless FIVEU_API_KEY is empty, DRY_RUN=1, LLM_FAKE=1, INVOICE_MAIL=0 and DB_PATH is inside
the research folder. All network is blocked (urlopen, sockets, mailbox.api, mailbox.poll) and every attempt is
counted. Mails are fed the way core.main.run_fake does: process(mailbox.normalize(raw)) then tick().
"""
import json, os, socket, sys, time, urllib.request

WT, SCEN, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
REPO = sys.argv[4] if len(sys.argv) > 4 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ hard safety checks, before any repo import
def die(msg):
    sys.exit("ABORT: " + msg)

if os.environ.get("FIVEU_API_KEY", "x") != "":
    die("FIVEU_API_KEY must be set and empty")
if os.environ.get("DRY_RUN") != "1" or os.environ.get("LLM_FAKE") != "1" or os.environ.get("INVOICE_MAIL") != "0":
    die("need DRY_RUN=1 LLM_FAKE=1 INVOICE_MAIL=0")
dbp = os.path.abspath(os.environ.get("DB_PATH", ""))
if not dbp.startswith(HERE + os.sep):
    die("DB_PATH must be inside %s" % HERE)
if os.path.exists(os.path.join(WT, ".env")):
    die("worktree has a .env file: config would load keys from it")
if os.path.exists(dbp):
    die("DB_PATH already exists, want a fresh DB: %s" % dbp)

BLOCKED = []
def _blocked(what):
    def f(*a, **k):
        BLOCKED.append((what, str(a)[:200]))
        raise RuntimeError("HARNESS: network blocked (%s)" % what)
    return f

urllib.request.urlopen = _blocked("urllib.request.urlopen")
socket.create_connection = _blocked("socket.create_connection")
socket.socket.connect = _blocked("socket.connect")
socket.socket.connect_ex = _blocked("socket.connect_ex")

sys.path.insert(0, WT)
os.chdir(WT)
from core import config  # noqa: E402
if config.API_KEY != "" or config.DRY_RUN is not True or config.LLM_FAKE is not True:
    die("config: API_KEY=%r DRY_RUN=%r LLM_FAKE=%r" % (bool(config.API_KEY), config.DRY_RUN, config.LLM_FAKE))
if os.path.abspath(config.DB_PATH) != dbp:
    die("config.DB_PATH differs")
from core import mailbox, db  # noqa: E402
mailbox.api = _blocked("mailbox.api")
mailbox.poll = _blocked("mailbox.poll")
from core import main  # noqa: E402
from llm import extract as llm_extract, human  # noqa: E402
human.STATE = os.path.join(os.path.dirname(dbp), "human_learn.json")      # keep writes out of the worktree
from booking import invoice, crm  # noqa: E402
try:                                                       # dg/attach.py compiles a macOS OCR tool into <worktree>/data:
    from dg import attach as _dg_attach                     # our mails have no attachments, so OCR is switched off to keep
    _dg_attach.ocr_binary = lambda report=None: None        # the worktree untouched
except Exception:
    pass
from monitor import carriers  # noqa: E402
assert invoice.INVOICE_MAIL is False

# The gateway is off (LLM_FAKE). Its crude regex never reads a pickup postcode; the real model does. Stand-in: add the
# postcode the way the real extract fills it (customer wrote "pickup at 63067 Offenbach"), and clear the origin so the
# clerk derives it from the zone, as it does live. Nothing else of the fake reader is changed.
import re as _re  # noqa: E402
_orig_fake = llm_extract._fake
def _fake_with_postcode(mail):
    f = _orig_fake(mail)
    m = _re.search(r"(?:pickup|pick-up|abholung|collect\w*|abholen)[^.\n]{0,40}?\b(\d{5})\b", mail["subject"] + " " + mail["body"], _re.I)
    if m:
        f["pickup_postcode"] = m.group(1)
        codes = _re.findall(r"\b[A-Z]{3}\b", mail["subject"] + " " + mail["body"])
        f["origin"], f["destination"] = None, (codes[0] if codes else None)
    return f
llm_extract._fake = _fake_with_postcode

# ------------------------------------------------------------------ recorder
STEPS = []
_ROUTE_HANDLER = {k: "%s.%s" % (v.__module__, v.__name__) for k, v in main.HANDLERS.items()}


def _events_after(eid):
    return [dict(r) for r in db.con().execute("SELECT * FROM events WHERE id>? ORDER BY id", (eid,))]


def _max_event():
    return db.con().execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]


def _status(tid):
    s = db.session(tid) if tid else None
    return (s["status"], (s["note"] or "")[:200]) if s else (None, None)


def _booking(tid):
    try:
        b = crm.get(tid)
    except Exception:
        return None
    return b and {k: b[k] for k in ("status", "booking_reference", "airline", "price", "currency", "transit_days",
                                    "booked_at", "confirmed_at")}


def _invoice(tid):
    try:
        i = invoice.get(tid)
    except Exception:
        return None
    return i and {k: i[k] for k in ("number", "status", "amount", "currency", "sent", "reminders", "issued_at", "due_at", "paid_at")}


def _short(d):
    d = dict(d)
    for k in ("trace", "options", "fields", "form", "usage", "chosen", "candidates"):
        if k in d and len(json.dumps(d[k], default=str)) > 300:
            d[k] = "<%d chars>" % len(json.dumps(d[k], default=str))
    return d


def record(label, tid, fn, mail=None):
    eid, before = _max_event(), _status(tid)
    nblocked = len(BLOCKED)
    err, result = None, None
    try:
        result = fn()
    except Exception as e:                                  # the harness itself should never hide a crash
        import traceback
        err = traceback.format_exc()[-1200:]
    evs = _events_after(eid)
    route = next((json.loads(e["data"]).get("route") for e in evs if e["kind"] == "mail_in"), None)
    out_mails = []
    for e in evs:
        if e["kind"].endswith("_dry_run") and e["kind"] != "booking_dry_run":
            d = json.loads(e["data"])
            out_mails.append({"event": e["kind"], "to": d.get("to"), "subject": d.get("subject"), "body": d.get("body"),
                              "attachments": d.get("attachments")})
    step = {"label": label, "mail_in": mail and {k: mail.get(k) for k in ("id", "from", "subject", "body", "in_reply_to", "references")},
            "route": route, "handler": _ROUTE_HANDLER.get(route) if route else None,
            "status_before": before, "status_after": _status(tid),
            "events": [{"kind": e["kind"], "thread": e["thread_id"], "data": _short(json.loads(e["data"] or "{}"))} for e in evs],
            "mails_out": out_mails, "booking": _booking(tid), "invoice": _invoice(tid),
            "network_attempts": BLOCKED[nblocked:], "harness_error": err,
            "result": json.loads(json.dumps(result, default=str)) if result is not None else None}
    STEPS.append(step)
    return step


NOW = time.time()
_mid = [0]


def raw(mid, frm, subject, body, thread=None, reply_to=None, attachments=None):
    r = {"id": mid, "from": frm, "subject": subject, "body": body, "created_at": time.time()}
    if thread:
        r["references"] = [thread]
        r["in_reply_to"] = reply_to or thread
    if attachments:
        r["attachments"] = attachments
    return r


def feed(label, r, tid):
    def go():
        main.process(mailbox.normalize(r))
        main.tick()
    return record(label, tid, go, r)


def call(label, tid, fn):
    return record(label, tid, fn)


def bids_of(tid):
    return [dict(b) for b in db.con().execute("SELECT * FROM bids WHERE thread_id=? ORDER BY id", (tid,))]


def trucker_replies(tid, base_id, prices):
    """Answer every trucker bid of this thread, in the bid's own subject with [BID-n]."""
    n = 0
    for b in bids_of(tid):
        if b["role"] != "trucker":
            continue
        price, hours = prices[n % len(prices)]
        n += 1
        subj = db.con().execute("SELECT data FROM events WHERE kind='bid_mail_out_dry_run' AND data LIKE ?",
                                ("%%[BID-%d]%%" % b["id"],)).fetchone()
        subject = json.loads(subj[0])["subject"] if subj else "Pickup [BID-%d]" % b["id"]
        body = ("Hello,\n\nthank you for your request. Our all-in price for this pickup is %.2f EUR. "
                "Collection in %d hours from order, delivery to the airport the same day.\n\nKind regards\n%s"
                % (price, hours, b["carrier"]))
        feed("trucker answers: %s" % b["carrier"], raw(base_id + n, b["email"], "Re: " + subject, body), tid)


def first_mail_out_to(step_list, who):
    return [m for s in step_list for m in s["mails_out"] if m["to"] == who]


# ------------------------------------------------------------------ scenarios
YT = "yellowtail-air-freight@hackloop.mail"
ORION = "orion-cargo-air@hackloop.mail"


def rfq_door(tid, customer, lang="en"):
    if lang == "de":
        body = ("Guten Tag,\n\nbitte um ein Angebot für Luftfracht nach Chicago (ORD).\n"
                "Abholung bei uns in 63067 Offenbach am Main, Hafenstraße 12.\n"
                "3 Paletten Maschinenteile, 400 kg, 2,1 cbm, nicht stapelbar.\n"
                "Ware ist ab Montag versandbereit. Bitte günstigste Option.\n\n"
                "Mit freundlichen Grüßen\nKatrin Vogel\nVogel Antriebstechnik GmbH")
        subject = "Anfrage Luftfracht Offenbach - ORD, 400 kg"
    else:
        body = ("Hello,\n\nplease quote air freight to Chicago O'Hare (ORD).\n"
                "Pickup at our warehouse: 63067 Offenbach am Main, Hafenstrasse 12.\n"
                "3 pallets of machine parts, 400 kg total, 2.1 cbm, not stackable.\n"
                "Cargo is ready from Monday. We would like the cheapest option.\n\n"
                "Best regards\nMarkus Brandt\nBrandt Maschinenbau GmbH")
        subject = "Quote request: door pickup Offenbach to ORD, 400 kg"
    return raw(tid, customer, subject, body)


def quote_and_book(tid, customer, lang="en", base=100):
    """RFQ -> trucker bids -> quote -> customer yes -> booking request by mail. Returns the session subject."""
    feed("RFQ from customer (door pickup)", rfq_door(tid, customer, lang), tid)
    trucker_replies(tid, tid + base, [(185.0, 24), (210.0, 20)])
    call("tick (bid wait over)", tid, main.tick)
    s = db.session(tid)
    yes = "Hallo,\n\npasst, bitte buchen.\n\nViele Grüße\nKatrin Vogel" if lang == "de" else \
        "Hi,\n\nthanks, that works for us. Please book it.\n\nBest regards\nMarkus Brandt"
    feed("customer accepts", raw(tid + base + 10, customer, "Re: " + s["subject"], yes, thread=tid), tid)
    return s


def confirmation(tid, bk, airline_name, airline_mail, price, mid, lane="FRA-ORD"):
    body = ("Dear customer,\n\nyour booking %s is confirmed.\n\nBooking reference: %s\nYour reference: GOOGLE-%d\n"
            "Airline: %s\nLane: %s\nPrice: %s EUR\nStatus: booked and ready to ship\n\nKind regards\n%s Bookings"
            % (bk, bk, tid, airline_name, lane, price, airline_name))
    return raw(mid, airline_mail, "Booking %s confirmed" % bk, body)


def chosen_total(tid):
    return json.loads(db.session(tid)["chosen"] or "{}").get("total")


def s1():
    """Happy path, English, then a carrier delay."""
    tid, cust, bk = 41001, "markus.brandt@brandt-maschinenbau.de", "BK-7Q2M9XKD"
    quote_and_book(tid, cust)
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    feed("airline confirms booking (real 5U format)", confirmation(tid, bk, ch.get("airline"), YT, ch.get("flight_total") or ch.get("total"), tid + 200), tid)
    feed("airline: DEPARTED (subject has Booking BK-)", raw(tid + 201, YT, "Booking %s - departed" % bk,
         "Dear partner,\n\nshipment %s / GOOGLE-%d departed today on flight YT 880 FRA-ORD.\n3 pcs, 400 kg.\n\n"
         "Yellowtail Air Freight Operations" % (bk, tid)), tid)
    feed("airline: DELAYED (aircraft change, new ETA + flight)", raw(tid + 202, YT, "Booking %s - DELAYED" % bk,
         "Dear partner,\n\ndue to an aircraft change your shipment %s (your ref GOOGLE-%d) was moved from YT 880 to "
         "YT 4412. New departure 26 Nov 2026 14:30, new ETA ORD 28 Nov 2026 09:15 (was 25 Nov).\n"
         "We apologise for the inconvenience.\n\nYellowtail Air Freight Operations" % (bk, tid)), tid)
    s = db.session(tid)
    feed("customer: where is my shipment? (in thread)", raw(tid + 203, cust, "Re: " + s["subject"],
         "Hi,\n\nwhere is our shipment now? When will it arrive in Chicago?\n\nThanks\nMarkus", thread=tid), tid)
    feed("customer asks again, mentions the delay", raw(tid + 204, cust, "Re: " + s["subject"],
         "Hi,\n\nwe heard the flight was delayed. What is the new arrival date?\n\nMarkus", thread=tid), tid)
    feed("5U tracking desk asks about BK", raw(tid + 205, "tracking@hackloop.mail", "Status of booking %s" % bk,
         "Hello,\n\nthe consignee asks for the current status and ETA of booking %s (Offenbach to Chicago, 400 kg).\n\n"
         "Thanks" % bk), tid)
    feed("airline: ARRIVED", raw(tid + 206, YT, "Booking %s - arrived ORD" % bk,
         "Shipment %s / GOOGLE-%d arrived ORD 28 Nov 2026 09:40 on YT 4412. Ready for pickup by consignee.\n\n"
         "Yellowtail Air Freight Operations" % (bk, tid)), tid)
    feed("airline: DELIVERED / POD", raw(tid + 207, YT, "Booking %s - delivered, POD attached" % bk,
         "Shipment %s delivered to consignee 28 Nov 2026 15:10, signed by J. Miller. POD attached.\n\n"
         "Yellowtail Air Freight Operations" % bk), tid)
    feed("customer: we have paid the invoice", raw(tid + 208, cust, "Re: " + s["subject"],
         "Hello,\n\nwe have paid the invoice today by bank transfer.\n\nBest regards\nMarkus Brandt", thread=tid), tid)
    call("forwarder marks paid: invoice.mark_paid(INV-%d)" % tid, tid, lambda: invoice.mark_paid("INV-%d" % tid))


def s2():
    """German customer; delay mail in German with only our reference (no BK)."""
    tid, cust, bk = 42001, "katrin.vogel@vogel-antriebstechnik.de", "BK-4HN8T2WQ"
    quote_and_book(tid, cust, "de")
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    feed("airline confirms booking", confirmation(tid, bk, ch.get("airline"), YT, ch.get("flight_total") or ch.get("total"), tid + 200), tid)
    feed("airline: Verspätung, German, only GOOGLE ref, no BK", raw(tid + 201, YT, "Verspätung Ihrer Sendung GOOGLE-%d" % tid,
         "Sehr geehrte Damen und Herren,\n\nIhre Sendung mit Ihrer Referenz GOOGLE-%d (FRA-ORD, 400 kg) konnte wegen "
         "eines Fluggerätewechsels nicht mit YT 880 abfliegen. Neuer Flug YT 4412 am 26.11.2026, neue Ankunft in "
         "Chicago am 28.11.2026 gegen 09:15 Uhr.\n\nMit freundlichen Grüßen\nYellowtail Air Freight Operations" % tid), tid)
    feed("airline: Verspätung as reply in the confirmation thread", raw(tid + 202, YT, "AW: Booking %s confirmed" % bk,
         "Nachtrag: neuer Flug YT 4412, Ankunft ORD 28.11.2026. Referenz GOOGLE-%d.\n\nYellowtail Air Freight" % tid,
         thread=tid + 200), tid)
    s = db.session(tid)
    feed("Kundin: wo ist die Sendung?", raw(tid + 203, cust, "AW: " + s["subject"],
         "Hallo,\n\nwo ist unsere Sendung gerade? Wann kommt sie in Chicago an?\n\nGruß\nKatrin Vogel", thread=tid), tid)


def s3():
    """Airline cancels / offloads after confirmation and offers another flight."""
    tid, cust, bk = 43001, "markus.brandt@brandt-maschinenbau.de", "BK-9ZK3P6RE"
    quote_and_book(tid, cust)
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    feed("airline confirms booking", confirmation(tid, bk, ch.get("airline"), YT, ch.get("flight_total") or ch.get("total"), tid + 200), tid)
    feed("airline: OFFLOADED, rebooked on next flight (no 'cancel' word)", raw(tid + 201, YT, "Booking %s - offloaded" % bk,
         "Dear partner,\n\nyour shipment %s (GOOGLE-%d) was offloaded from YT 880 due to weight restrictions. "
         "We have protected it on YT 884 departing 27 Nov 2026, ETA ORD 29 Nov 2026. Please advise if you do not "
         "agree.\n\nYellowtail Air Freight Operations" % (bk, tid)), tid)
    s = db.session(tid)
    feed("customer: status?", raw(tid + 202, cust, "Re: " + s["subject"],
         "Hi,\n\nany update on our shipment? Has it left Frankfurt?\n\nMarkus", thread=tid), tid)
    feed("airline: booking CANCELLED, offers another flight", raw(tid + 203, YT, "Booking %s cancelled" % bk,
         "Dear partner,\n\nwe regret that booking %s (your reference GOOGLE-%d) is cancelled: no capacity on YT 884. "
         "We can offer YT 890 on 28 Nov 2026 at the same rate. Please confirm if you want it.\n\n"
         "Yellowtail Air Freight Operations" % (bk, tid)), tid)
    feed("customer: status after airline cancel", raw(tid + 204, cust, "Re: " + s["subject"],
         "Hello,\n\nwhere is our shipment now?\n\nMarkus", thread=tid), tid)


def s4():
    """Customer cancels after the booking is confirmed (control case)."""
    tid, cust, bk = 44001, "markus.brandt@brandt-maschinenbau.de", "BK-2MD7V5LC"
    quote_and_book(tid, cust)
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    feed("airline confirms booking", confirmation(tid, bk, ch.get("airline"), YT, ch.get("flight_total") or ch.get("total"), tid + 200), tid)
    s = db.session(tid)
    feed("customer cancels", raw(tid + 201, cust, "Re: " + s["subject"],
         "Hello,\n\nunfortunately our customer has postponed the order. Could you please cancel booking %s?\n\n"
         "Best regards\nMarkus Brandt" % bk, thread=tid), tid)
    feed("airline confirms the cancellation", raw(tid + 202, YT, "Booking %s cancelled as requested" % bk,
         "Booking %s / GOOGLE-%d has been cancelled as per your request. No charges.\n\nYellowtail" % (bk, tid)), tid)


def s5():
    """Extra: price change at mail booking, delay mail to a new thread with no reference, cancel before confirmation."""
    tid, cust, bk = 45001, "markus.brandt@brandt-maschinenbau.de", "BK-8RT4N1HX"
    quote_and_book(tid, cust)
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    higher = "%.2f" % (float(ch.get("flight_total") or ch.get("total")) * 1.15)
    feed("airline confirms at a 15%% HIGHER price (%s)" % higher, confirmation(tid, bk, ch.get("airline"), YT, higher, tid + 200), tid)
    feed("airline: delay to a NEW thread, no reference at all", raw(tid + 201, YT, "Flight YT 880 FRA-ORD 25 Nov delayed",
         "Dear partner,\n\nflight YT 880 FRA-ORD of 25 Nov is delayed by 24 hours due to a technical issue. "
         "All shipments on board will arrive one day later.\n\nYellowtail Air Freight Operations"), tid)
    feed("airline: delay with GOOGLE ref, subject without 'Booking BK-'", raw(tid + 202, YT, "Delay notice GOOGLE-%d" % tid,
         "Your shipment GOOGLE-%d (%s) is delayed, new ETA 27 Nov 2026.\n\nYellowtail" % (tid, bk)), tid)
    feed("airline: FLIGHT cancelled but shipment REBOOKED (still flying)", raw(tid + 203, YT, "Booking %s - flight change" % bk,
         "Dear partner,\n\nflight YT 880 of 25 Nov has been cancelled for technical reasons. Your shipment %s (GOOGLE-%d) "
         "is rebooked on YT 884 on 26 Nov 2026, ETA ORD 27 Nov 2026. No action needed.\n\nYellowtail Air Freight Operations"
         % (bk, tid)), tid)
    s = db.session(tid)
    feed("customer: status after the flight change", raw(tid + 204, cust, "Re: " + s["subject"],
         "Hi,\n\nany news on our shipment?\n\nMarkus", thread=tid), tid)
    feed("5U tracking desk asks after the flight change", raw(tid + 205, "tracking@hackloop.mail", "Status of booking %s" % bk,
         "Hello,\n\nwhat is the status of booking %s?\n\nThanks" % bk), tid)


def s6():
    """Extra: a delay mail from an airline we are waiting on for a price is read as its price answer."""
    tid, cust, bk = 46001, "markus.brandt@brandt-maschinenbau.de", "BK-5WQ2J8MT"
    quote_and_book(tid, cust)
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    feed("airline confirms booking", confirmation(tid, bk, ch.get("airline"), YT, ch.get("flight_total") or ch.get("total"), tid + 200), tid)
    # a second customer asks for a lane with no sheet/portal price that Yellowtail serves: Yellowtail is asked and REQUIRED
    tid2, cust2 = 46501, "einkauf@hessen-optik.de"
    from pricing import price as sheets
    assert not sheets.options("HAM", "ORD", 250, 1.0)
    feed("2nd customer RFQ HAM-ORD (no sheet price: airlines asked and REQUIRED)", raw(tid2, cust2,
         "Air freight HAM to ORD, 250 kg", "Hello,\n\nplease quote HAM to ORD, 250 kg, 1.0 cbm, 2 boxes of "
         "optical instruments, ready now.\n\nRegards\nSabine Kraus"), tid2)
    feed("Yellowtail mails a DELAY notice for booking %s (no BID ref)" % bk, raw(tid + 201, YT, "Shipment update GOOGLE-%d" % tid,
         "Dear partner,\n\nyour shipment GOOGLE-%d / %s is delayed: new flight YT 4412, ETA 28 Nov 2026.\n\n"
         "Yellowtail Air Freight Operations" % (tid, bk)), tid2)
    STEPS[-1]["bids_thread2"] = [{k: b[k] for k in ("id", "carrier", "role", "required", "status", "note", "replied_at")}
                                 for b in bids_of(tid2) if b["carrier"] in ("Yellowtail Air Freight",)]


def s7():
    """Extras: invoices (issue, reminder clock, paid, copy, dispute), carrier flags, doc request / retraction /
    new request after booking."""
    cust = "markus.brandt@brandt-maschinenbau.de"
    # carrier reliability: 5 normal requests FRA-ORD; BID_EXPERIMENT asks Yellowtail (+ others) and nobody answers
    for i in range(5):
        t = 47501 + i
        feed("flag setup: RFQ %d FRA-ORD (experiment bids, never answered)" % (i + 1), raw(t, "buyer%d@rhein-logistik-test.de" % (i + 1),
             "Rate request FRA-ORD 120 kg", "Hello,\n\nplease quote FRA to ORD, 120 kg, 0.6 cbm, general cargo.\n\nThanks"), t)
    call("carriers.refresh(now = +10 min): no_answer counted", None,
         lambda: [(r["carrier"], r["level"], r["reasons"]) for r in carriers.refresh(now=time.time() + 600)])
    STEPS[-1]["carrier_flags"] = [dict(r) for r in db.con().execute("SELECT carrier, level, jobs, issues, reasons FROM carrier_flags ORDER BY level")]
    tid, bk = 47001, "BK-3KD9F7QA"
    quote_and_book(tid, cust)
    STEPS[-1]["session_note"] = db.session(tid)["note"]
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    feed("airline confirms booking", confirmation(tid, bk, ch.get("airline"), YT, ch.get("flight_total") or ch.get("total"), tid + 200), tid)
    s = db.session(tid)
    inv = invoice.get(tid)
    call("invoice.tick(now = due - 1 day): nothing yet", tid, lambda: invoice.tick(now=inv["due_at"] - 86400))
    call("invoice.tick(now = due + 1 day): reminder 1", tid, lambda: invoice.tick(now=inv["due_at"] + 86400))
    call("invoice.tick(now = due + 3 days): no 2nd reminder yet", tid, lambda: invoice.tick(now=inv["due_at"] + 3 * 86400))
    call("invoice.tick(now = due + 9 days): reminder 2", tid, lambda: invoice.tick(now=inv["due_at"] + 9 * 86400))
    call("invoice.tick(now = due + 17 days): overdue_human", tid, lambda: invoice.tick(now=inv["due_at"] + 17 * 86400))
    feed("customer: please send the invoice", raw(tid + 301, cust, "Re: " + s["subject"],
         "Hello,\n\ncould you please send us the invoice for this shipment? Our accounting needs it.\n\nMarkus", thread=tid), tid)
    feed("customer: the invoice is wrong", raw(tid + 302, cust, "Re: " + s["subject"],
         "Hello,\n\nthe invoice amount is wrong, it does not match your quote.\n\nMarkus", thread=tid), tid)
    db.update_session(tid, status="confirmed")              # a person handled the dispute; back to a normal booking
    feed("customer: please send AWB copy (document request)", raw(tid + 303, cust, "Re: " + s["subject"],
         "Hi,\n\ncan you send us a copy of the air waybill please?\n\nMarkus", thread=tid), tid)
    db.update_session(tid, status="confirmed")
    feed("customer: retraction (wrong thread)", raw(tid + 304, cust, "Re: " + s["subject"],
         "Sorry, please ignore my last mail, sent it by mistake.\n\nMarkus", thread=tid), tid)
    db.update_session(tid, status="confirmed")
    feed("customer: new request in the booked thread", raw(tid + 305, cust, "Re: " + s["subject"],
         "Hi,\n\nwe have another shipment next week, same lane, 650 kg. Can you quote it?\n\nMarkus", thread=tid), tid)
    db.update_session(tid, status="confirmed")
    feed("customer: we have paid", raw(tid + 306, cust, "Re: " + s["subject"],
         "Hello,\n\nthe payment has been made today.\n\nMarkus", thread=tid), tid)
    call("invoice.tick after paid_reported: no reminder", tid, lambda: invoice.tick(now=inv["due_at"] + 40 * 86400))
    call("invoice.mark_paid", tid, lambda: invoice.mark_paid(str(tid)))
    # with INVOICE_MAIL flipped in-process only (DRY_RUN still logs, network still blocked): what would the mails say?
    def mail_on():
        invoice.INVOICE_MAIL = True
        try:
            t2 = 47901
            quote_and_book(t2, "lena.hoffmann@hoffmann-feinwerk.de", base=100)
            ch2 = json.loads(db.session(t2)["chosen"] or "{}")
            feed("[INVOICE_MAIL=1 in-process] airline confirms", confirmation(t2, "BK-6PL2W9ZN", ch2.get("airline"), YT,
                 ch2.get("flight_total") or ch2.get("total"), t2 + 200), t2)
            i2 = invoice.get(t2)
            call("[INVOICE_MAIL=1] invoice.tick(due + 1 day)", t2, lambda: invoice.tick(now=i2["due_at"] + 86400))
        finally:
            invoice.INVOICE_MAIL = False
    mail_on()




# ================================================================== carrierops extension
import contextlib, io, traceback  # noqa: E402
if not os.path.isdir(os.path.join(REPO, "carrierops")):
    die("no carrierops/ in %s" % REPO)
sys.path.append(REPO)                                     # AFTER the worktree: core/, booking/ ... still come from the worktree
from carrierops import run as co_run, state as co_state, tracking as co_tracking, invoice as co_invoice  # noqa: E402
assert os.path.abspath(co_run.__file__).startswith(os.path.join(REPO, "carrierops"))
assert os.path.abspath(main.__file__).startswith(os.path.abspath(WT)), "clerk must come from the worktree"
DAY, HOUR = 86400.0, 3600.0
_CO_LAST = {"upd": 0, "out": 0, "log": 0}


def raw_at(mid, frm, subject, body, at, thread=None, reply_to=None):
    r = raw(mid, frm, subject, body, thread=thread, reply_to=reply_to)
    r["created_at"] = at                                   # the sim clock: when the carrier/customer wrote
    return r


def _iso(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def co_snapshot(con, tid):
    s = co_state.shipment(con, tid) if tid else None
    inv = co_invoice.get(con, tid) if tid else None
    return (s and {k: s[k] for k in ("status", "milestone", "eta_planned", "eta_current", "flight", "awb", "tracking_url",
                                     "picked_up_at", "delivered_at", "offer_flight", "airline_price")},
            inv and {k: inv[k] for k in ("number", "status", "amount", "currency", "reminders")} and
            dict({k: inv[k] for k in ("number", "status", "amount", "currency", "reminders")},
                 issued=_iso(inv["issued_at"]), due=_iso(inv["due_at"])))


def co(label, now, tid, args=None):
    """Run carrierops in-process (same network block) and record what it changed."""
    nb = len(BLOCKED)
    buf, err, rc = io.StringIO(), None, None
    argv = ["--db", dbp, "--now", repr(now)] + (args or ["--once"])
    try:
        with contextlib.redirect_stdout(buf):
            rc = co_run.main(argv)
    except BaseException:
        err = traceback.format_exc()[-1500:]
    con = co_state.connect(dbp)
    upd = [dict(r) for r in con.execute("SELECT * FROM shipment_updates WHERE id>? ORDER BY id", (_CO_LAST["upd"],))]
    out = [dict(r) for r in con.execute("SELECT * FROM outbox WHERE id>? ORDER BY id", (_CO_LAST["out"],))]
    log = [dict(r) for r in con.execute("SELECT * FROM carrier_log WHERE id>? ORDER BY id", (_CO_LAST["log"],))]
    for k, rows_ in (("upd", upd), ("out", out), ("log", log)):
        if rows_:
            _CO_LAST[k] = rows_[-1]["id"]
    st, inv = co_snapshot(con, tid)
    con.close()
    for u in upd:
        u.pop("raw", None)
    step = {"label": label, "kind": "carrierops", "argv": argv[2:], "sim_now": now, "sim_now_iso": _iso(now), "rc": rc,
            "stdout": buf.getvalue()[-3000:], "updates": upd,
            "drafts": [{k: d[k] for k in ("id", "thread_id", "party", "to_addr", "subject", "reason", "status", "body")} for d in out],
            "carrier_log": log, "state": st, "invoice": inv, "network_attempts": BLOCKED[nb:], "harness_error": err,
            "mails_out": [], "events": []}
    STEPS.append(step)
    return step


def carrier(label, tid, r, at):
    """A mail goes through the clerk first (stored + whatever the clerk does with it), then carrierops runs."""
    feed(label, r, tid)
    return co("carrierops after: " + label, at + 120, tid)


def setup(tid, cust, bk, lang="en", price=None, extra=""):
    """Steps 1-5 through the clerk, then the airline confirmation and the first carrierops pass. -> sim time T0."""
    quote_and_book(tid, cust, lang)
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    p = price or ch.get("flight_total") or ch.get("total")
    conf = confirmation(tid, bk, ch.get("airline"), YT, p, tid + 200)
    if extra:
        conf["body"] = conf["body"].replace("Status: booked", extra + "\nStatus: booked")
    feed("airline confirms booking (real 5U format)%s" % (" at %s" % p if price else ""), conf, tid)
    t0 = crm.get(tid)["confirmed_at"]
    co("carrierops pass 1 (step 6)", t0 + 60, tid)
    return t0


def subj(tid):
    return db.session(tid)["subject"]


def c1():
    """Normal shipment: step 6, truck pickup, departed, delay, arrived, delivered, invoice, 'we have paid', mark paid."""
    tid, cust, bk = 51001, "markus.brandt@brandt-maschinenbau.de", "BK-7Q2M9XKD"
    t0 = setup(tid, cust, bk, extra="AWB: 160-51001004")
    carrier("trucker: picked up + handed over at FRA", tid, raw_at(tid + 301, "westfalenroute@hackloop.mail",
            "Re: Pickup order GOOGLE-%d" % tid, "Hello,\n\npicked up today 09:10 at Brandt Maschinenbau and delivered to the "
            "Yellowtail cargo terminal FRA at 13:30. Receipt attached.\n\nWestfalenroute" % (), t0 + 1 * DAY), t0 + 1 * DAY)
    carrier("airline: DEPARTED", tid, raw_at(tid + 302, YT, "Booking %s - departed" % bk,
            "Dear partner,\n\nshipment %s / GOOGLE-%d departed today on flight YT 880 FRA-ORD, AWB 160-51001004.\n"
            "Track: https://track.yellowtail.example/160-51001004\n\nYellowtail Air Freight Operations" % (bk, tid), t0 + 2 * DAY), t0 + 2 * DAY)
    carrier("airline: DELAYED (new flight + ETA)", tid, raw_at(tid + 303, YT, "Booking %s - DELAYED" % bk,
            "Dear partner,\n\ndue to an aircraft change your shipment %s (your ref GOOGLE-%d) was moved from YT 880 to "
            "YT 4412. New departure 26 Nov 2026 14:30, new ETA ORD 28 Nov 2026 09:15 (was 25 Nov).\n"
            "We apologise for the inconvenience.\n\nYellowtail Air Freight Operations" % (bk, tid), t0 + 2 * DAY + 3 * HOUR),
            t0 + 2 * DAY + 3 * HOUR)
    carrier("airline: ARRIVED", tid, raw_at(tid + 304, YT, "Booking %s - arrived ORD" % bk,
            "Shipment %s / GOOGLE-%d arrived ORD 28 Nov 2026 09:40 on YT 4412. Ready for pickup by consignee.\n\n"
            "Yellowtail Air Freight Operations" % (bk, tid), t0 + 6 * DAY), t0 + 6 * DAY)
    carrier("airline: DELIVERED / POD", tid, raw_at(tid + 305, YT, "Booking %s - delivered, POD attached" % bk,
            "Shipment %s delivered to consignee 28 Nov 2026 15:10, signed by J. Miller. POD attached.\n\n"
            "Yellowtail Air Freight Operations" % bk, t0 + 6 * DAY + 6 * HOUR), t0 + 6 * DAY + 6 * HOUR)
    carrier("customer: we have paid", tid, raw_at(tid + 306, cust, "Re: " + subj(tid),
            "Hello,\n\nwe have paid the invoice today by bank transfer.\n\nBest regards\nMarkus Brandt", t0 + 20 * DAY, thread=tid),
            t0 + 20 * DAY)
    co("forwarder: --mark-paid INV-%d" % tid, t0 + 22 * DAY, tid, ["--mark-paid", "INV-%d" % tid])


def c2():
    """German customer; German delay mail with only our reference; the same news again in the confirmation thread."""
    tid, cust, bk = 52001, "katrin.vogel@vogel-antriebstechnik.de", "BK-4HN8T2WQ"
    t0 = setup(tid, cust, bk, "de")
    carrier("airline: Verspätung, German, only GOOGLE ref", tid, raw_at(tid + 301, YT, "Verspätung Ihrer Sendung GOOGLE-%d" % tid,
            "Sehr geehrte Damen und Herren,\n\nIhre Sendung mit Ihrer Referenz GOOGLE-%d (FRA-ORD, 400 kg) konnte wegen "
            "eines Fluggerätewechsels nicht mit YT 880 abfliegen. Neuer Flug YT 4412 am 26.11.2026, neue Ankunft in "
            "Chicago am 28.11.2026 gegen 09:15 Uhr.\n\nMit freundlichen Grüßen\nYellowtail Air Freight Operations" % tid,
            t0 + 2 * DAY), t0 + 2 * DAY)
    carrier("airline: same news as reply in the confirmation thread", tid, raw_at(tid + 302, YT, "AW: Booking %s confirmed" % bk,
            "Nachtrag: neuer Flug YT 4412, Ankunft ORD 28.11.2026 09:15. Referenz GOOGLE-%d.\n\nYellowtail Air Freight" % tid,
            t0 + 2 * DAY + HOUR, thread=tid + 200), t0 + 2 * DAY + HOUR)
    carrier("Kundin: wo ist die Sendung?", tid, raw_at(tid + 303, cust, "AW: " + subj(tid),
            "Hallo,\n\nwo ist unsere Sendung gerade? Wann kommt sie in Chicago an?\n\nGruß\nKatrin Vogel", t0 + 2 * DAY + 5 * HOUR,
            thread=tid), t0 + 2 * DAY + 5 * HOUR)


def c3():
    """Airline cancels the booking and offers another flight; customer says yes; airline confirms the new flight."""
    tid, cust, bk = 53001, "markus.brandt@brandt-maschinenbau.de", "BK-9ZK3P6RE"
    t0 = setup(tid, cust, bk)
    carrier("airline: booking CANCELLED, offers YT 890", tid, raw_at(tid + 301, YT, "Booking %s cancelled" % bk,
            "Dear partner,\n\nwe regret that booking %s (your reference GOOGLE-%d) is cancelled: no capacity on YT 884. "
            "We can offer YT 890 on 28 Nov 2026 at the same rate. Please confirm if you want it.\n\n"
            "Yellowtail Air Freight Operations" % (bk, tid), t0 + 1 * DAY), t0 + 1 * DAY)
    carrier("customer: yes, rebook", tid, raw_at(tid + 302, cust, "Re: " + subj(tid),
            "Hi,\n\nyes, please rebook on YT 890.\n\nMarkus", t0 + 1 * DAY + 2 * HOUR, thread=tid), t0 + 1 * DAY + 2 * HOUR)
    carrier("airline: new booking confirmed on YT 890", tid, raw_at(tid + 303, YT, "Booking %s confirmed" % bk,
            "Dear customer,\n\nyour booking %s is confirmed on flight YT 890, departure 28 Nov 2026, ETA ORD 29 Nov 2026 07:30.\n"
            "Your reference: GOOGLE-%d\n\nYellowtail Bookings" % (bk, tid), t0 + 1 * DAY + 6 * HOUR), t0 + 1 * DAY + 6 * HOUR)
    carrier("customer: where is it now?", tid, raw_at(tid + 304, cust, "Re: " + subj(tid),
            "Hello,\n\nwhere is our shipment now?\n\nMarkus", t0 + 1 * DAY + 8 * HOUR, thread=tid), t0 + 1 * DAY + 8 * HOUR)


def c4():
    """Offloaded, protected on the next flight; then that flight is cancelled and the shipment rebooked (still flies)."""
    tid, cust, bk = 54001, "markus.brandt@brandt-maschinenbau.de", "BK-2MD7V5LC"
    t0 = setup(tid, cust, bk)
    carrier("airline: OFFLOADED, protected on YT 884", tid, raw_at(tid + 301, YT, "Booking %s - offloaded" % bk,
            "Dear partner,\n\nyour shipment %s (GOOGLE-%d) was offloaded from YT 880 due to weight restrictions. "
            "We have protected it on YT 884 departing 27 Nov 2026, ETA ORD 29 Nov 2026. Please advise if you do not "
            "agree.\n\nYellowtail Air Freight Operations" % (bk, tid), t0 + 3 * DAY), t0 + 3 * DAY)
    carrier("airline: FLIGHT cancelled, shipment REBOOKED on YT 890", tid, raw_at(tid + 302, YT, "Booking %s - flight change" % bk,
            "Dear partner,\n\nflight YT 884 of 27 Nov has been cancelled for technical reasons. Your shipment %s (GOOGLE-%d) "
            "is rebooked on YT 890 on 28 Nov 2026, ETA ORD 30 Nov 2026. No action needed.\n\nYellowtail Air Freight Operations"
            % (bk, tid), t0 + 4 * DAY), t0 + 4 * DAY)


def c5():
    """Airline confirms 15% above the flight price we quoted; later a fuel surcharge mail."""
    tid, cust, bk = 55001, "markus.brandt@brandt-maschinenbau.de", "BK-8RT4N1HX"
    quote_and_book(tid, cust)
    ch = json.loads(db.session(tid)["chosen"] or "{}")
    higher = "%.2f" % (float(ch.get("flight_total") or ch.get("total")) * 1.15)
    feed("airline confirms at a 15%% HIGHER price (%s)" % higher, confirmation(tid, bk, ch.get("airline"), YT, higher, tid + 200), tid)
    t0 = crm.get(tid)["confirmed_at"]
    co("carrierops pass 1 (step 6 + price check)", t0 + 60, tid)
    carrier("airline: fuel surcharge", tid, raw_at(tid + 301, YT, "Booking %s - surcharge" % bk,
            "Dear partner,\n\na fuel surcharge of 0.15 EUR/kg applies to booking %s (GOOGLE-%d) from today.\n\nYellowtail" % (bk, tid),
            t0 + DAY), t0 + DAY)


def c6():
    """Delay mail with no reference: matched by airline + lane. A non-matching airline is ignored. With two shipments
    on the lane, a lane-only mail is NOT guessed (forwarder note)."""
    tid, cust, bk = 56001, "markus.brandt@brandt-maschinenbau.de", "BK-5WQ2J8MT"
    t0 = setup(tid, cust, bk)
    carrier("airline: 'Flight YT 880 FRA-ORD delayed', NO reference", tid, raw_at(tid + 301, YT, "Flight YT 880 FRA-ORD 25 Nov delayed",
            "Dear partner,\n\nflight YT 880 FRA-ORD of 25 Nov is delayed by 24 hours due to a technical issue. "
            "All shipments on board will arrive one day later.\n\nYellowtail Air Freight Operations", t0 + 2 * DAY), t0 + 2 * DAY)
    carrier("other airline (Orion) delay, not ours", tid, raw_at(tid + 302, ORION, "Flight OC 12 FRA-ORD delayed",
            "Flight OC 12 FRA-ORD is delayed by 5 hours.\n\nOrion Cargo Air", t0 + 2 * DAY + HOUR), t0 + 2 * DAY + HOUR)
    tid2, bk2 = 56701, "BK-7XN3C4RB"
    setup(tid2, "einkauf@hessen-optik.de", bk2)
    carrier("airline: lane-only delay while 2 shipments fly FRA-ORD", tid, raw_at(tid + 303, YT, "FRA-ORD shipments of 26 Nov",
            "Dear partner,\n\nall FRA-ORD shipments of 26 Nov are delayed by 12 hours due to weather.\n\nYellowtail", t0 + 3 * DAY),
            t0 + 3 * DAY)
    STEPS[-1]["state_second_shipment"] = co_snapshot(co_state.connect(dbp), tid2)[0]


def c7():
    """'Where is my shipment?' before any airline report, then after departure + delay: new ETA, AWB, flight, link."""
    tid, cust, bk = 57001, "markus.brandt@brandt-maschinenbau.de", "BK-3KD9F7QA"
    t0 = setup(tid, cust, bk)
    carrier("customer: where is my shipment? (nothing reported yet)", tid, raw_at(tid + 301, cust, "Re: " + subj(tid),
            "Hi,\n\nwhere is our shipment now?\n\nMarkus", t0 + 2 * HOUR, thread=tid), t0 + 2 * HOUR)
    carrier("airline: DEPARTED with AWB + tracking link", tid, raw_at(tid + 302, YT, "Booking %s - departed" % bk,
            "Shipment %s / GOOGLE-%d departed on flight YT 880 FRA-ORD, AWB 160-57001003.\n"
            "Track it here: https://track.yellowtail.example/160-57001003\n\nYellowtail Air Freight Operations" % (bk, tid),
            t0 + 2 * DAY), t0 + 2 * DAY)
    carrier("airline: DELAYED", tid, raw_at(tid + 303, YT, "Booking %s - DELAYED" % bk,
            "Shipment %s moved from YT 880 to YT 4412, new ETA ORD 28 Nov 2026 09:15 due to an aircraft change.\n\n"
            "Yellowtail Air Freight Operations" % bk, t0 + 2 * DAY + 4 * HOUR), t0 + 2 * DAY + 4 * HOUR)
    carrier("customer: where is my shipment? (after the delay)", tid, raw_at(tid + 304, cust, "Re: " + subj(tid),
            "Hi,\n\nwhere is our shipment now? When will it arrive in Chicago?\n\nThanks\nMarkus", t0 + 2 * DAY + 6 * HOUR,
            thread=tid), t0 + 2 * DAY + 6 * HOUR)
    carrier("5U tracking desk: status of BK", tid, raw_at(tid + 305, "tracking@hackloop.mail", "Status of booking %s" % bk,
            "Hello,\n\nthe consignee asks for the current status and ETA of booking %s.\n\nThanks" % bk, t0 + 2 * DAY + 7 * HOUR),
            t0 + 2 * DAY + 7 * HOUR)


def c8():
    """Invoice only after delivery; overdue -> reminder; 'we have paid' -> paid_reported (reminders stop); mark paid."""
    tid, cust, bk = 58001, "markus.brandt@brandt-maschinenbau.de", "BK-6PL2W9ZN"
    t0 = setup(tid, cust, bk)
    carrier("airline: DELIVERED / POD", tid, raw_at(tid + 301, YT, "Booking %s - delivered, POD attached" % bk,
            "Shipment %s / GOOGLE-%d delivered to consignee 26 Nov 2026 11:05. POD attached.\n\nYellowtail" % (bk, tid),
            t0 + 4 * DAY), t0 + 4 * DAY)
    con = co_state.connect(dbp)
    due = co_invoice.get(con, tid)["due_at"]
    con.close()
    co("clock: due - 1 day", due - DAY, tid)
    co("clock: due + 1 day (reminder 1)", due + DAY + 60, tid)
    co("clock: due + 1 day again (no double reminder)", due + DAY + 600, tid)
    carrier("customer: payment has been made", tid, raw_at(tid + 302, cust, "Re: " + subj(tid),
            "Hello,\n\nthe payment has been made today.\n\nMarkus", due + 2 * DAY, thread=tid), due + 2 * DAY)
    co("clock: due + 9 days (no reminder 2: paid reported)", due + 9 * DAY, tid)
    co("forwarder: --mark-paid INV-%d" % tid, due + 10 * DAY, tid, ["--mark-paid", "INV-%d" % tid])


def _with_catch_up(fn):
    def go():
        fn()
        tids = [r[0] for r in db.con().execute("SELECT thread_id FROM bookings WHERE confirmed_at IS NOT NULL")]
        co("carrierops catch-up pass over the whole scenario", time.time() + 60, tids[0] if tids else None)
    go.__doc__ = (fn.__doc__ or "") + " + carrierops catch-up pass"
    return go


SCENARIOS = {"s1": _with_catch_up(s1), "s2": _with_catch_up(s2), "s3": _with_catch_up(s3), "s4": _with_catch_up(s4),
             "s5": _with_catch_up(s5), "s6": _with_catch_up(s6), "s7": _with_catch_up(s7),
             "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6, "c7": c7, "c8": c8}

if __name__ == "__main__":
    SCENARIOS[SCEN]()
    os.makedirs(OUT, exist_ok=True)
    meta = {"scenario": SCEN, "doc": SCENARIOS[SCEN].__doc__, "commit": os.popen("git -C %s rev-parse --short HEAD" % WT).read().strip(),
            "network_attempts_total": BLOCKED, "dry_run": config.DRY_RUN, "api_key_set": bool(config.API_KEY),
            "llm_fake": config.LLM_FAKE, "invoice_mail_env": os.environ.get("INVOICE_MAIL"), "db": dbp,
            "carrierops_from": os.path.dirname(co_run.__file__)}
    json.dump({"meta": meta, "steps": STEPS}, open(os.path.join(OUT, SCEN + ".json"), "w"), indent=1, default=str)
    print(SCEN, "steps:", len(STEPS), "network attempts:", len(BLOCKED),
          "harness errors:", sum(1 for s in STEPS if s.get("harness_error")),
          "carrierops passes:", sum(1 for s in STEPS if s.get("kind") == "carrierops"))
