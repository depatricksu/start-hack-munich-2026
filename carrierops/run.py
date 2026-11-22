"""carrierops main: one pass = sync shipments from the clerk's bookings (step 6), read new mails (step 7, invoice,
tracking questions), then due work (reminders, no-news checks). Idempotent: run it as often as you like.

    python3 -m carrierops.run --db PATH [--ops-db PATH] [--once] [--now TS]
    python3 -m carrierops.run --db PATH --mark-paid INV-41001 [--now TS]
    python3 -m carrierops.run --db PATH --where BK-7Q2M9XKD          # tracking answer from our own state
    python3 -m carrierops.run --db PATH --outbox                     # list drafts
    python3 -m carrierops.run --db PATH --baseline                   # first run on an old DB: no drafts for the past

--now: epoch seconds or 'YYYY-MM-DD[THH:MM]' (UTC). The clock is only passed in; nothing ever waits for it.
Never sends mail, never calls an API: every message is a draft row in `outbox`.
"""
import argparse, csv, json, os, re, sys, time
from datetime import datetime, timedelta

from . import disruptions, invoice, match, messages, rules, state, tracking

TRACKING_DESK = "tracking@hackloop.mail"
OUR_ADDRESS = "google@hackloop.mail"
KIT_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "start-kit", "carrier-list.csv")
PARTNERS = {}                       # destination airport -> partner address; --partners FILE (JSON). Unknown = "" (draft only)
DAY = 86400.0


def iso(ts, with_time=True):
    return time.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d", time.gmtime(ts))


def parse_now(v):
    if v is None:
        return time.time()
    try:
        return float(v)
    except ValueError:
        pass
    for f in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return (datetime.strptime(v, f) - datetime(1970, 1, 1)).total_seconds()
        except ValueError:
            continue
    raise SystemExit("bad --now: %s" % v)


# ------------------------------------------------------------------ who is who
def carriers(con):
    """email -> {'name', 'kind'} from the start-kit carrier list plus the clerk's bids table."""
    out = {}
    if os.path.exists(KIT_CSV):
        with open(KIT_CSV, newline="") as f:
            for r in csv.DictReader(f):
                out[r["email"].strip().lower()] = {"name": r["name"], "kind": r["kind"]}
    if state.clerk_has(con, "bids"):
        cols = {r["name"] for r in con.execute("PRAGMA clerk.table_info(bids)")}
        if "email" in cols:
            role = "role" if "role" in cols else "kind"
            for r in con.execute("SELECT DISTINCT email, carrier, %s AS role FROM clerk.bids WHERE email IS NOT NULL" % role):
                out.setdefault(r["email"].lower(), {"name": r["carrier"], "kind": r["role"] or "airline"})
    return out


def email_of(cmap, name):
    for e, c in cmap.items():
        if c["name"].lower() == (name or "").lower():
            return e
    return None


# ------------------------------------------------------------------ shipment context from the clerk's step 1-5 data
def _line_with(body, rx):
    for line in (body or "").splitlines():
        if re.search(rx, line, re.I):
            return line.strip()
    return None


def _sentence_with(body, rx):
    line = _line_with(body, rx)
    if not line:
        return None
    return next((x.strip().rstrip(".") for x in re.split(r"(?<=[.!?])\s", line) if re.search(rx, x, re.I)), line)


def build(con, b, cmap):
    """One shipment_state row from a clerk booking (+ session, RFQ mail, bids)."""
    tid = b["thread_id"]
    sess = state.one(con, "SELECT * FROM clerk.sessions WHERE thread_id=?", (tid,)) if state.clerk_has(con, "sessions") else None
    sess = sess or {}
    fields = state.jload(sess.get("fields"), {}) or {}
    chosen = state.jload(sess.get("chosen"), {}) or {}
    rfq = state.one(con, "SELECT body FROM clerk.mails WHERE id=?", (tid,)) if state.clerk_has(con, "mails") else None
    body = (rfq or {}).get("body") or ""
    pc = fields.get("pickup_postcode")
    pickup = None
    if pc:
        line = _line_with(body, r"\b%s\b" % re.escape(str(pc)))
        pickup = (line.split(":", 1)[1].strip() if line and ":" in line else line) or str(pc)
        pickup = pickup.rstrip(".")
    trucker = chosen.get("trucker")
    trucker_email = None
    if trucker and state.clerk_has(con, "bids"):
        r = state.one(con, "SELECT * FROM clerk.bids WHERE thread_id=? AND carrier=?", (tid, trucker))
        trucker_email = (r or {}).get("email")
    trucker_email = trucker_email or (email_of(cmap, trucker) if trucker else None)
    lines = fields.get("customer_lines") or []
    company = next((l for l in reversed(lines) if re.search(r"\b(gmbh|ag|ltd|inc|kg|llc|sarl|srl|bv|co\.?)\b", l, re.I)), None)
    conf = b.get("confirmed_at") or time.time()
    planned = (datetime.utcfromtimestamp(conf) + timedelta(days=int(b.get("transit_days") or chosen.get("transit_days") or 0)))
    lang = b.get("language") or fields.get("language") or "en"
    return dict(
        booking_ref=b.get("booking_reference"), our_ref=b.get("team_reference") or "GOOGLE-%s" % tid,
        airline=b.get("airline") or chosen.get("airline"), airline_code=b.get("airline_code"),
        airline_email=email_of(cmap, b.get("airline") or chosen.get("airline")), trucker=trucker, trucker_email=trucker_email,
        customer=b.get("customer") or sess.get("customer"), customer_name=fields.get("customer_first_name"), company=company,
        language=lang, subject=b.get("subject") or sess.get("subject"),
        origin=b.get("origin") or chosen.get("origin"), destination=b.get("destination") or chosen.get("destination"),
        lane="%s-%s" % (b.get("origin") or chosen.get("origin"), b.get("destination") or chosen.get("destination")),
        weight_kg=b.get("weight_kg") or fields.get("weight_kg"), volume_cbm=b.get("volume_cbm") or fields.get("volume_cbm"),
        pickup=pickup, goods=_sentence_with(body, r"\d\s*(kg|kgs|kilo)\b"),
        ready=_sentence_with(body, r"\bready\b|versandbereit|bereit ab"),
        quote_total=chosen.get("total") or b.get("price"), flight_quote=chosen.get("flight_total") or chosen.get("total"),
        trucker_quote=chosen.get("trucker_total"), currency=chosen.get("currency") or b.get("currency") or "EUR",
        status="confirmed", milestone="confirmed", eta_planned=planned.strftime("%Y-%m-%d"),
        eta_current=planned.strftime("%Y-%m-%d"), last_customer_mail_id=b.get("last_customer_mail_id"), confirmed_at=conf)


def _d(con, s, party, to, subj_body, reason, key, now, update_id=None, reply=False):
    if not subj_body:
        return None
    subj, body = subj_body
    return state.draft(con, s["thread_id"], party, to, subj, body, reason, key, now,
                       s.get("last_customer_mail_id") if reply else None, s.get("booking_ref"), update_id)


def inform_parties(con, s, now):
    """Step 6: customer, trucker, airline, destination partner, the bidders we did not choose."""
    tid = s["thread_id"]
    uid = state.add_update(con, tid, None, "us", "shipment_opened", now, summary="booking confirmed, all parties informed")
    _d(con, s, "customer", s["customer"], messages.customer_next_steps(s), "step 6: next steps and papers",
       "step6:customer:%s" % tid, now, uid, reply=True)
    if s.get("trucker"):
        _d(con, s, "trucker", s.get("trucker_email"), messages.trucker_pickup_order(s), "step 6: pickup order",
           "step6:trucker:%s" % tid, now, uid)
    _d(con, s, "airline", s.get("airline_email"), messages.airline_details(s), "step 6: shipment details",
       "step6:airline:%s" % tid, now, uid)
    _d(con, s, "partner", PARTNERS.get(s.get("destination"), ""), messages.partner_prealert(s),
       "step 6: pre-alert" + ("" if PARTNERS.get(s.get("destination")) else " (partner address unknown, fill in)"),
       "step6:partner:%s" % tid, now, uid)
    sess = state.one(con, "SELECT deadline FROM clerk.sessions WHERE thread_id=?", (tid,)) if state.clerk_has(con, "sessions") else None
    deadline = (sess or {}).get("deadline")
    if state.clerk_has(con, "bids"):
        for bid in state.rows(con, "SELECT * FROM clerk.bids WHERE thread_id=?", (tid,)):
            name, mail = bid.get("carrier"), bid.get("email")
            if bid.get("replied_at"):
                chosen = name in (s.get("trucker"), s.get("airline"))
                if not chosen and (bid.get("status") or "ok") not in ("declined", "unclear", "no"):
                    _d(con, s, "bidder", mail, messages.bidder_thanks(s, name), "step 6: thank-you, not chosen",
                       "step6:thanks:%s:%s" % (tid, mail or name), now, uid)
                if deadline and bid["replied_at"] > deadline:
                    state.log_carrier(con, name, tid, "late_answer", now, "late:%s:%s" % (tid, bid["id"]),
                                      round((bid["replied_at"] - deadline) / 3600.0, 2),
                                      "price answer %.0f s after our bid wait ended" % (bid["replied_at"] - deadline))
            else:
                state.log_carrier(con, name, tid, "no_answer", now, "noans:%s:%s" % (tid, bid["id"]), None,
                                  "no answer to our price request (%s, required=%s)" % (bid.get("role") or bid.get("kind"),
                                                                                        bid.get("required")))
    b = state.one(con, "SELECT created_at, confirmed_at FROM clerk.bookings WHERE thread_id=?", (tid,))
    if b and b.get("created_at") and b.get("confirmed_at") and b["confirmed_at"] - b["created_at"] > 3600:
        state.log_carrier(con, s["airline"], tid, "late_answer", now, "slowconf:%s" % tid,
                          round((b["confirmed_at"] - b["created_at"]) / 3600.0, 2), "booking confirmed after more than 1 h")
    state.save_shipment(con, tid, now, informed_at=now)


def sync_shipments(con, now, cmap):
    """New confirmed bookings -> shipment_state + step 6. Customer cancellations by the clerk -> trucker/partner told."""
    out = []
    if not state.clerk_has(con, "bookings"):
        return out
    for b in state.rows(con, "SELECT * FROM clerk.bookings WHERE confirmed_at IS NOT NULL ORDER BY confirmed_at"):
        tid = b["thread_id"]
        s = state.shipment(con, tid)
        with state.tx(con):
            if not s and b.get("status") == "cancelled":
                # cancelled by the customer before we ever saw it: keep the record, tell nobody (nothing was ordered)
                state.save_shipment(con, tid, now, informed_at=now, **dict(build(con, b, cmap), status="cancelled"))
                state.add_update(con, tid, None, "us", "cancelled_by_customer", now, status_after="cancelled",
                                 summary="already cancelled when carrierops first saw it: no step 6 messages")
                out.append(("seen_cancelled", tid))
            elif not s:
                state.save_shipment(con, tid, now, **build(con, b, cmap))
                inform_parties(con, state.shipment(con, tid), now)
                out.append(("opened", tid))
            elif b.get("status") == "cancelled" and s["status"] != "cancelled":
                st, ms = state.next_status(s["status"], s["milestone"], "cancelled_by_customer")
                uid = state.add_update(con, tid, None, "us", "cancelled_by_customer", now, status_after=st,
                                       summary="customer cancelled (clerk handled customer + airline)")
                state.save_shipment(con, tid, now, status=st, milestone=ms)
                s = state.shipment(con, tid)
                if s.get("trucker") and not s.get("picked_up_at"):
                    _d(con, s, "trucker", s.get("trucker_email"), messages.trucker_cancel(s), "customer cancelled",
                       "cancel:trucker:%s" % tid, now, uid)
                _d(con, s, "partner", PARTNERS.get(s.get("destination"), ""), messages.partner_update(s, "cancelled_by_customer", {}),
                   "customer cancelled", "cancel:partner:%s" % tid, now, uid)
                out.append(("cancelled_by_customer", tid))
    return out


# ------------------------------------------------------------------ mails
REASON = re.compile(r"(?:due to|because of|owing to|wegen|aufgrund)\s+([^.,;:\n(]{3,80})", re.I)
_REASON_CUT = re.compile(r"\s(?:your|the shipment|our|we|is|was|has|ihre|ihr|die sendung|konnte|nicht|wurde|ist|verspätet|verzögert|delayed|will|wird)\b.*$", re.I)


def reason_in(body):
    """'due to an aircraft change your shipment ...' -> 'an aircraft change'."""
    m = REASON.search(rules.own_text(body))
    if not m:
        return None
    r = _REASON_CUT.sub("", m.group(1)).strip()
    g = re.match(r"^(?:eines|des)\s+(\S+?)s$", r)          # 'wegen eines Fluggerätewechsels' -> 'Fluggerätewechsel'
    if g:
        r = g.group(1)
    r = re.sub(r"^(?:einer|der|dem|den)\s+", "", r)
    return r if len(r) >= 3 else None


def handle_carrier(con, m, who, now):
    subject, body = m["subject"] or "", m["body"] or ""
    text = subject + "\n" + body
    if who["kind"] == "trucker":
        t = rules.classify_trucker(subject, body)
        typ = t if t in ("picked_up", "handed_over", "info") else "trucker_" + t
        ui = rules.classify(subject, body)
    else:
        typ, ui = rules.classify_carrier(subject, body)
    problem = disruptions.detect(subject, body) if who["kind"] == "airline" else None
    if problem:
        if problem["type"] in ("damaged", "missing") and typ != "cancelled":
            typ = problem["type"]                              # also inside a 'delivered' mail: no invoice on damaged cargo
        elif typ in ("info", "confirmed", "booked") or (
                typ == "cancelled" and not rules._BOOKING_CANCEL.search(text.lower()) and not rules._REFUSED.search(text.lower())):
            typ = "delayed"                                    # 'storm, flight cancelled' is not a cancelled booking
        if typ == "delayed":
            ui = "delayed"
    tid, how = match.match(con, m, who["name"], who["kind"], typ)
    at = m.get("received_at") or now
    if not tid:
        if typ in match.FUZZY_TYPES or how != "no_match":
            uid = state.add_update(con, None, m["id"], "carrier", typ, at, sender=m["sender"], ui_type=ui, match=how,
                                   summary=rules.key_sentence(body, rules.KEY.get(typ, ".")), raw=body)
            if how != "no_match" and who["kind"] == "airline":
                subj, b = messages.forwarder(None, "airline mail not matched (%s)" % how, [
                    "From %s: %s" % (who["name"], subject), "", rules.own_text(body)[:800], "",
                    "carrierops could not tie this to one shipment (%s). Please check by hand." % how])
                state.draft(con, None, "forwarder", "", subj, b, "unmatched carrier news", "unmatched:%s" % m["id"], now,
                            update_id=uid)
        return ("unmatched", how, typ)
    s = state.shipment(con, tid)
    year = int(iso(at)[:4])
    new_f, old_f = rules.flights(text, s.get("airline_code"))
    eta = rules.eta_in(text, year)
    by = rules.delay_by_hours(text)
    awb = rules.awb_in(text)
    url = rules.tracking_url_in(text)
    reason = reason_in(body)
    summary = rules.key_sentence(body, rules.KEY.get(typ, r"."))
    if problem:                                                # our own words: a cut-out half sentence reads broken
        reason = problem["de" if messages.lang_of(s) == "de" else "en"]
    upd = {"reason": reason, "old_flight": old_f, "awb": awb, "cause": problem and problem["key"]}
    cols = {}
    new_eta, delay, flight = None, None, None
    if typ in ("delayed", "offloaded", "rebooked"):
        new_eta = eta or (rules.add_hours(s["eta_current"], by) if by else None)
        delay = rules.hours_between(s["eta_current"], new_eta) if new_eta and s["eta_current"] else by
        flight = new_f if (new_f and new_f != old_f) else None
    elif typ == "departed":
        flight = new_f
        new_eta = eta
        cols["departed_at"] = iso(at)
    elif typ == "arrived":
        hits = rules.date_hits(text, year)
        arr = eta or (hits[0][1] + (" " + hits[0][2] if hits[0][2] else "") if hits else iso(at))
        cols["arrived_at"] = arr
        new_eta = arr
        flight = new_f
    elif typ == "delivered":
        hits = rules.date_hits(text, year)
        cols["delivered_at"] = hits[0][1] + (" " + hits[0][2] if hits[0][2] else "") if hits else iso(at)
        upd["delivered_at"] = cols["delivered_at"]
    elif typ in ("confirmed", "booked", "info"):
        flight = new_f if typ != "info" else None
        new_eta = eta
        first = not state.one(con, "SELECT 1 FROM shipment_updates WHERE thread_id=? AND source='carrier' AND type='confirmed'", (tid,))
        if new_eta and s["eta_current"] and not first and s["status"] not in ("cancelled_by_airline", "rebook_requested"):
            dh = rules.hours_between(s["eta_current"], new_eta) or 0
            if dh > 0:              # a later arrival hidden in a reply ('AW: Booking ... confirmed' + new ETA) is a delay
                typ, delay = "delayed", dh
                flight = flight if flight and flight != s.get("flight") else None
            else:                   # same (or earlier) date again: kept in the update row, state unchanged
                new_eta, flight = None, (flight if flight and flight != s.get("flight") else None)
    elif typ in ("picked_up", "handed_over"):
        cols["picked_up_at"] = s.get("picked_up_at") or iso(at)
    elif typ == "cancelled":
        of, od = rules.offer_in(text)
        cols["offer_flight"], cols["offer_date"] = of, od
        upd["offer_flight"], upd["offer_date"] = of, od
    summary = rules.key_sentence(body, rules.KEY.get(typ, r"."))
    if problem and typ == problem["type"]:
        summary = problem["sentence"]
    new_cause = bool(problem) and not any(
        (disruptions.detect("", r["raw"] or "") or {}).get("key") == problem["key"]
        for r in state.rows(con, "SELECT raw FROM shipment_updates WHERE thread_id=? AND source='carrier'", (tid,)))
    repeat = False                       # the same news twice (e.g. a 'Nachtrag' with the same flight and ETA)
    if typ in ("delayed", "offloaded", "rebooked") and s["status"] in ("delayed", "offloaded", "rebooked"):
        repeat = (not new_eta or new_eta == s["eta_current"]) and (not flight or flight == s.get("flight")) and not new_cause
    st, ms = state.next_status(s["status"], s["milestone"], typ)
    was_rebook = s["status"] in ("cancelled_by_airline", "rebook_requested") and typ == "confirmed" and st == "confirmed"
    if new_eta and s["status"] not in state.FINAL:
        cols["eta_current"] = new_eta
    if flight:
        cols["flight"] = flight
    if awb:
        cols["awb"] = awb
    if url:
        cols["tracking_url"] = url
    cols.update(status=st, milestone=ms)
    uid = state.add_update(con, tid, m["id"], "carrier", typ, at, sender=m["sender"], ui_type=ui, match=how, summary=summary,
                           new_eta=new_eta, flight=flight, awb=awb, delay_hours=delay, status_after=st,
                           eta_after=cols.get("eta_current") or s["eta_current"], raw=body)
    state.save_shipment(con, tid, now, **cols)
    s2 = state.shipment(con, tid)
    upd.update(new_eta=new_eta, flight=flight, delay_hours=delay)
    carrier = who["name"]
    drafts = []

    def cust(kind, key):
        drafts.append(_d(con, s2, "customer", s2["customer"], messages.customer_update(s2, kind, upd),
                         "carrier update: %s" % kind, key, now, uid, reply=True))

    def partner(kind, key):
        drafts.append(_d(con, s2, "partner", PARTNERS.get(s2.get("destination"), ""), messages.partner_update(s2, kind, upd),
                         "carrier update: %s" % kind, key, now, uid))

    def fwd(title, lines, key):
        drafts.append(_d(con, s2, "forwarder", "", messages.forwarder(s2, title, lines), title, key, now, uid))

    news_key = "%s:%s:%s" % (typ, new_eta or "", flight or "")
    if problem and not new_eta and not flight:
        news_key += ":" + problem["key"]
    if s["status"] in state.FINAL and typ not in ("price", "info"):
        pass                                                   # stored above; a final shipment is not re-opened by mail
    elif typ in ("delayed", "offloaded", "rebooked"):
        kind = {"delayed": "delay", "offloaded": "offload", "rebooked": "rebook"}[typ]
        if not repeat:                                         # the same news again is not a second carrier event
            state.log_carrier(con, carrier, tid, kind, at, "%s:%s:%s" % (kind, tid, news_key if new_eta or flight else m["id"]),
                              delay, "%s%s%s" % (summary, (" | new ETA %s" % new_eta) if new_eta else "",
                                                 (" | planned %s" % s["eta_planned"]) if s.get("eta_planned") else ""), m["id"])
            cust(typ, "cust:%s:%s" % (tid, news_key))
            partner(typ, "partner:%s:%s" % (tid, news_key))
    elif typ == "cancelled":
        state.log_carrier(con, carrier, tid, "cancelled", at, "cancelled:%s:%s" % (tid, m["id"]), None, summary, m["id"])
        cust("cancelled", "cust:%s:cancelled:%s" % (tid, m["id"]))
        partner("cancelled", "partner:%s:cancelled:%s" % (tid, m["id"]))
        if s2.get("trucker") and not s2.get("picked_up_at"):
            drafts.append(_d(con, s2, "trucker", s2.get("trucker_email"), messages.trucker_hold(s2, "the airline cancelled the booking"),
                             "airline cancelled", "hold:trucker:%s:%s" % (tid, m["id"]), now, uid))
        fwd("airline cancelled the booking", ["%s cancelled booking %s: %s" % (carrier, s2.get("booking_ref"), summary),
                                              "Offer: %s %s" % (upd.get("offer_flight") or "none", upd.get("offer_date") or ""),
                                              "A rebook offer is drafted for the customer. Their yes creates the rebook request."],
            "fwd:cancelled:%s:%s" % (tid, m["id"]))
    elif typ in ("damaged", "missing"):
        if new_cause:
            cust(typ, "cust:%s:%s" % (tid, typ))
            fwd("cargo %s" % typ, ["%s: %s" % (carrier, summary), "Customer update drafted. Open a claim with the airline."],
                "fwd:%s:%s" % (typ, tid))
    elif typ == "cancel_confirmed":
        pass
    elif typ in ("departed", "arrived", "delivered", "picked_up", "handed_over"):
        if st == typ:                                          # a real step forward, not an old milestone arriving late
            cust(typ, "cust:%s:%s" % (tid, typ))
            if typ == "departed":
                partner(typ, "partner:%s:departed" % tid)
            if typ == "delivered":
                inv = invoice.issue(con, s2, now)
                if inv:
                    drafts.append(inv["outbox_id"])
    elif typ == "confirmed":
        if was_rebook:
            cust("rebook_confirmed", "cust:%s:rebook_confirmed:%s" % (tid, m["id"]))
            partner("rebook_confirmed", "partner:%s:rebook_confirmed:%s" % (tid, m["id"]))
        price = rules.price_in(text)
        if price is not None:
            state.save_shipment(con, tid, now, airline_price="%.2f" % price)
            try:
                quoted = float(s2.get("flight_quote") or 0)
            except ValueError:
                quoted = 0
            if quoted and price > quoted * 1.005 + 0.5:
                pct = (price / quoted - 1) * 100
                state.log_carrier(con, carrier, tid, "price_increase", at, "price:%s:%s" % (tid, m["id"]), None,
                                  "confirmed %.2f vs our quoted flight part %.2f (+%.1f%%)" % (price, quoted, pct), m["id"])
                cost = price + float(s2.get("trucker_quote") or 0)
                fwd("airline price above our quote", [
                    "%s confirmed %s at %.2f %s, our quote used %.2f for the flight (+%.1f%%)."
                    % (carrier, s2.get("booking_ref"), price, s2.get("currency"), quoted, pct),
                    "Sold to the customer for %s %s, cost now %.2f (margin %.2f)." % (
                        s2.get("quote_total"), s2.get("currency"), cost, float(s2.get("quote_total") or 0) - cost),
                    "Customer not told. Decide: accept, push back on the airline, or talk to the customer."],
                    "fwd:price:%s:%s" % (tid, m["id"]))
    elif typ == "price":
        state.log_carrier(con, carrier, tid, "price_increase", at, "price:%s:%s" % (tid, m["id"]), None, summary, m["id"])
        fwd("airline price change", ["%s wrote about %s: %s" % (carrier, s2.get("booking_ref"), summary),
                                     "Customer not told. Please check against our quote."], "fwd:price:%s:%s" % (tid, m["id"]))
    elif typ in ("trucker_delayed", "trucker_cancelled"):
        kind = "delay" if typ == "trucker_delayed" else "cancelled"
        state.log_carrier(con, carrier, tid, kind, at, "%s:%s:%s" % (kind, tid, m["id"]), by, "trucker: " + summary, m["id"])
        fwd("trucker %s" % kind, ["%s wrote about the pickup for %s: %s" % (carrier, s2.get("our_ref"), summary),
                                  "Check if the flight is still reachable; the customer has not been told yet."],
            "fwd:%s:%s" % (typ, m["id"]))
    elif typ == "info" and who["kind"] == "airline":
        fwd("airline mail to read", ["%s: %s" % (carrier, subject), summary], "fwd:info:%s" % m["id"])
    return ("matched", how, typ, [d for d in drafts if d])


def handle_customer(con, m, s, now):
    at = m.get("received_at") or now
    if s.get("confirmed_at") and at < s["confirmed_at"] - 1:
        return ("before_confirmation",)
    intent = rules.customer_intent(m["subject"], m["body"], s["status"])
    if not intent:
        return ("not_ours",)
    tid = s["thread_id"]
    state.save_shipment(con, tid, now, last_customer_mail_id=m["id"])
    s = state.shipment(con, tid)
    uid = state.add_update(con, tid, m["id"], "customer", intent, at, sender=m["sender"],
                           summary=rules.first_sentence(m["body"]), raw=m["body"], status_after=s["status"])
    if intent == "paid":
        return ("paid", invoice.report_paid(con, s, now, m["id"]))
    if intent == "status_question":
        body = tracking.answer_text(con, tid)
        state.draft(con, tid, "customer", s["customer"], messages.cust_subject(s), body, "tracking answer (customer asked)",
                    "track:%s" % m["id"], now, m["id"], s.get("booking_ref"), uid)
        return ("status_answer",)
    if intent == "rebook_yes":
        st, ms = state.next_status(s["status"], s["milestone"], "rebook_requested")
        state.save_shipment(con, tid, now, status=st, milestone=ms)
        s = state.shipment(con, tid)
        _d(con, s, "airline", s.get("airline_email"), messages.airline_rebook_request(s, s.get("offer_flight"), s.get("offer_date")),
           "customer accepted rebook offer", "rebook:airline:%s" % m["id"], now, uid)
        _d(con, s, "customer", s["customer"], messages.customer_update(s, "rebook_ack", {"offer_flight": s.get("offer_flight")}),
           "rebook acknowledged", "rebook:customer:%s" % m["id"], now, uid, reply=True)
        _d(con, s, "forwarder", "", messages.forwarder(s, "customer accepted the rebook offer", [
            "Customer said yes to %s. A rebook request to %s is drafted." % (s.get("offer_flight") or "the next flight", s["airline"])]),
           "rebook accepted", "rebook:fwd:%s" % m["id"], now, uid)
        return ("rebook_requested",)
    if intent == "rebook_no":
        _d(con, s, "forwarder", "", messages.forwarder(s, "customer declined the rebook offer", [
            "Customer wrote: %s" % rules.first_sentence(m["body"]), "Please call them: cancel or find another flight."]),
           "rebook declined", "rebook_no:%s" % m["id"], now, uid)
        return ("rebook_declined",)
    return (intent,)


def handle_desk(con, m, now):
    refs = rules.refs_in(m["subject"] + "\n" + m["body"])
    s = None
    for r in ["BK-" + x[3:] for x in refs["bk"]] + ["GOOGLE-%d" % g for g in refs["google"]]:
        s = tracking.find(con, ref=r)
        if s:
            break
    if not s:
        return ("desk_unknown",)
    uid = state.add_update(con, s["thread_id"], m["id"], "customer", "status_question", m.get("received_at") or now,
                           sender=m["sender"], match="bk", summary=rules.first_sentence(m["body"]), raw=m["body"])
    body = tracking.answer_text(con, s["thread_id"], lang="en", desk=True)
    subj = m["subject"] if m["subject"].lower().startswith("re:") else "Re: " + m["subject"]
    state.draft(con, s["thread_id"], "customer", m["sender"], subj, body, "tracking answer (5U tracking desk)",
                "track:%s" % m["id"], now, m["id"], s.get("booking_ref"), uid)
    return ("desk_answer", s["thread_id"])


def process_mails(con, now, cmap, limit=500):
    """Every clerk mail exactly once. 'seen' holds each processed mail id (5U ids are not guaranteed to arrive in
    order); the cursor keeps the highest id done, and 'floor' (set by --baseline) skips the past."""
    if not state.clerk_has(con, "mails"):
        return []
    floor = state.get_cursor(con, "floor")
    out = []
    todo = state.rows(con, "SELECT * FROM clerk.mails m WHERE m.id>? AND NOT EXISTS (SELECT 1 FROM carrierops_seen s "
                           "WHERE s.mail_id=m.id) ORDER BY m.received_at, m.id LIMIT ?", (floor, limit))
    for r in todo:
        m = dict(r, sender=(r["sender"] or "").lower(), raw=state.jload(r.get("raw"), {}) or {})
        with state.tx(con):
            if m["sender"] == OUR_ADDRESS:
                res = ("own",)
            elif m["sender"] == TRACKING_DESK:
                res = handle_desk(con, m, now)
            elif m["sender"] in cmap:
                res = handle_carrier(con, m, cmap[m["sender"]], now)
            else:
                s = state.shipment(con, m["thread_id"])
                res = handle_customer(con, m, s, now) if s and (s["customer"] or "").lower() == m["sender"] else ("skip",)
            state.mark_seen(con, m["id"], res[0], now)
            state.set_cursor(con, max(m["id"], state.get_cursor(con)), now=now)
        out.append((m["id"], res))
    return out


# ------------------------------------------------------------------ due work
def due_work(con, now):
    with state.tx(con):
        done = [("invoice",) + d for d in invoice.tick(con, now)]
        for s in state.active_shipments(con):
            d = rules.parse_eta(s["eta_current"])
            if not d or s["milestone"] in ("arrived", "delivered") or s["status"] in ("cancelled_by_airline", "rebook_requested"):
                continue
            late_h = (now - (d - datetime(1970, 1, 1)).total_seconds()) / 3600.0
            if late_h > 24:
                key = "nonews:%s:%s" % (s["thread_id"], s["eta_current"])
                state.log_carrier(con, s["airline"], s["thread_id"], "no_status_after_eta", now, key, round(late_h, 1),
                                  "ETA %s passed, last status %s, no arrival reported" % (s["eta_current"], s["status"]))
                _d(con, s, "forwarder", "", messages.forwarder(s, "no news from the airline after ETA", [
                    "ETA %s passed %.0f h ago, last status from %s: %s. Please ask the airline." % (
                        s["eta_current"], late_h, s["airline"], s["status"])]), "no status after ETA", key, now)
                done.append(("no_news", s["thread_id"]))
    return done


def run_once(con, now):
    cmap = carriers(con)
    return {"now": iso(now), "shipments": sync_shipments(con, now, cmap), "mails": process_mails(con, now, cmap),
            "due": due_work(con, now)}


def baseline(con, now):
    """First run on a DB with history: take over existing confirmed bookings and old mails WITHOUT drafting anything."""
    cmap = carriers(con)
    n = 0
    with state.tx(con):
        if state.clerk_has(con, "bookings"):
            for b in state.rows(con, "SELECT * FROM clerk.bookings WHERE confirmed_at IS NOT NULL"):
                if not state.shipment(con, b["thread_id"]):
                    state.save_shipment(con, b["thread_id"], now, informed_at=now, **build(con, b, cmap))
                    n += 1
        top = state.one(con, "SELECT COALESCE(MAX(id),0) AS m FROM clerk.mails") if state.clerk_has(con, "mails") else {"m": 0}
        state.set_cursor(con, max(top["m"], state.get_cursor(con, "floor")), name="floor", now=now)
        state.set_cursor(con, max(top["m"], state.get_cursor(con)), now=now)
    return {"baseline_shipments": n, "floor": state.get_cursor(con, "floor")}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m carrierops.run", description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, help="the clerk's SQLite DB (opened read-only for clerk tables)")
    ap.add_argument("--ops-db", help="write carrierops tables here instead of into --db")
    ap.add_argument("--once", action="store_true", help="one pass, then exit")
    ap.add_argument("--now", help="clock: epoch seconds or YYYY-MM-DD[THH:MM] UTC (default: real time)")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between passes without --once")
    ap.add_argument("--partners", help="JSON file {\"ORD\": \"agent@example\"} for pre-alerts")
    ap.add_argument("--mark-paid", metavar="INVOICE", help="forwarder: mark INV-<thread> as paid")
    ap.add_argument("--where", metavar="REF", help="tracking answer for BK-.../GOOGLE-.../AWB")
    ap.add_argument("--outbox", action="store_true", help="print the drafts")
    ap.add_argument("--baseline", action="store_true", help="adopt existing bookings and mails without drafting")
    a = ap.parse_args(argv)
    if a.partners:
        with open(a.partners) as f:
            PARTNERS.update(json.load(f))
    con = state.connect(a.db, a.ops_db)
    now = parse_now(a.now)
    if a.mark_paid:
        with state.tx(con):
            inv = invoice.mark_paid(con, a.mark_paid, now)
        print(json.dumps(inv, default=str))
        return 0 if inv else 1
    if a.where:
        print(tracking.answer_text(con, ref=a.where) or "unknown reference: %s" % a.where)
        return 0
    if a.outbox:
        for r in state.rows(con, "SELECT * FROM outbox ORDER BY id"):
            print("#%(id)s [%(status)s] %(party)s -> %(to_addr)s | %(subject)s | %(reason)s" % r)
        return 0
    if a.baseline:
        print(json.dumps(baseline(con, now)))
        return 0
    while True:
        res = run_once(con, now)
        print(json.dumps(res, default=str), flush=True)
        if a.once:
            return 0
        time.sleep(a.interval)
        now = time.time() if a.now is None else now + a.interval


if __name__ == "__main__":
    sys.exit(main())
