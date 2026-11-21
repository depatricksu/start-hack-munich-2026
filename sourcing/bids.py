"""Bids by mail: ask truckers and airlines for a price, read their answers, feed them into the quote.

Called by core/main.py:
  request(session, fields) -> int   mail the carriers; returns how many answers we must WAIT for
  on_reply(mail)                    a carrier or the rate desk answered: read it (one tiny gateway call), save it
  must_wait(thread_id) -> bool      a needed leg (trucker, or the only flight price) is still missing
  final_options(thread_id, options) -> options   add airline bids and the trucker leg to the price options

When we ask
  door pickup            all truckers of the postcode zone                      required: we wait
  no sheet/portal price  every airline serving the destination + the rate desk  required: we wait
  experiment             up to 3 airlines on a normal request                   NOT required: only logged
The experiment (BID_EXPERIMENT=1) tells us if a bid by mail beats sheet/portal. Look at the answers with
`python -m core.stats`, then decide. All waits are env vars in core/config.py, none of them is settled.
"""
import csv, json, os, re, time
from decimal import Decimal, InvalidOperation
from core import attachments, config, db, mailbox

_KIT = os.path.join(config.ROOT, "kit", "start-kit")
CARRIERS = list(csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv"))))
RATEDESK = "ratedesk@hackloop.mail"
REF = re.compile(r"\bBID-(\d+)\b", re.I)
PRICE = re.compile(r"\d[\d.,]*\s*(?:EUR|USD|CHF|GBP|€|\$)", re.I)
# A trucker's lead time as the offer files write it. Read by code, because the model took "27 hours from order to
# collection" for 3 hours on a PDF whose table lost its layout (live, 21 Nov 22:25), and hours decide the balanced pick.
LEAD = re.compile(r"(\d{1,3})\s*hours?\s+(?:from\s+(?:the\s+|your\s+)?order|after\s+(?:the\s+|your\s+)?order)"   # 27 hours from order to collection
                  r"|collection:?\s+in\s+(\d{1,3})\s*hours?"                                    # Collection in 31 hours
                  r"|lead\s*time:?\s+(\d{1,3})\s*hours?", re.I)                                 # Lead time 28 hours


_UNITS = {w: i for i, w in enumerate("one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
                                     "fifteen sixteen seventeen eighteen nineteen".split(), 1)}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70}
_SPOKEN = re.compile(r"\b(?:(%s)(?:[\s-]+(%s))?|(%s))(?=\s+hours?\b)" % ("|".join(_TENS), "|".join(list(_UNITS)[:9]), "|".join(_UNITS)), re.I)


def spoken_hours(text):
    """'we need seven hours from your order' -> 'we need 7 hours from your order'. A voice message transcript writes
    small numbers as words; the model returned no hours at all for 'seven hours' (live, 21 Nov 22:55, Rheinufer)."""
    def digits(m):
        if m.group(3):
            return str(_UNITS[m.group(3).lower()])
        return str(_TENS[m.group(1).lower()] + (_UNITS[m.group(2).lower()] if m.group(2) else 0))
    return _SPOKEN.sub(digits, text or "")


def lead_hours(text):
    """Hours from order to collection, when the text states it once and clearly. None otherwise."""
    found = {int(next(g for g in m.groups() if g)) for m in LEAD.finditer(spoken_hours(text))}
    return found.pop() if len(found) == 1 else None
EXTRA_COLUMNS = {"email": "TEXT", "role": "TEXT", "required": "INTEGER DEFAULT 1", "status": "TEXT",
                 "total_eur": "TEXT", "note": "TEXT", "hours": "REAL"}
_ready = False


def ensure():
    """Add our columns to the bids table (old DBs on the runner keep working)."""
    global _ready
    if _ready:
        return
    have = {r["name"] for r in db.con().execute("PRAGMA table_info(bids)")}
    for col, typ in EXTRA_COLUMNS.items():
        if col not in have:
            db.con().execute("ALTER TABLE bids ADD COLUMN %s %s" % (col, typ))
    _ready = True


def rows(thread_id):
    ensure()
    return db.bids_for(thread_id)


def serving(kind, code):
    return [c for c in CARRIERS if c["kind"] == kind and code in c["serves"].split()]


# ---------------------------------------------------------------- asking

TRUCK_MAILS = [
    "Hello,\n\ncould you quote a pickup for us?\n\nFrom: postcode {postcode}, Germany\nTo: {origin} airport\n{cargo}\n\n"
    "Please send your all-in price with currency and how soon you can deliver to the airport.\n\nThank you\nGoogle Forwarding",
    "Hi,\n\nwe need a truck for an air export shipment.\n\nPickup: {postcode} (Germany)\nDelivery: {origin} airport\n{cargo}\n\n"
    "What is your all-in price (with currency) and your lead time?\n\nBest regards\nGoogle Forwarding",
    "Good day,\n\nplease send us your rate for this pickup:\n\nCollection at postcode {postcode}, delivery to {origin} airport\n{cargo}\n\n"
    "We need one all-in price, the currency, and the time until delivery at the airport.\n\nMany thanks\nGoogle Forwarding",
]
AIR_MAILS = [
    "Hello,\n\ncould you quote this air freight shipment?\n\nRoute: {origin} to {destination}\n{cargo}\n\n"
    "Please send your all-in price (freight, fuel and security included) with currency and transit time in days.\n\nThank you\nGoogle Forwarding",
    "Hi,\n\nwe have a shipment {origin} to {destination} and would like your rate.\n\n{cargo}\n\n"
    "What is your all-in price with currency, and how many days transit?\n\nBest regards\nGoogle Forwarding",
    "Good day,\n\nplease send us your best rate:\n\n{origin} to {destination}\n{cargo}\n\n"
    "One all-in total including surcharges, the currency, and the transit time in days, please.\n\nMany thanks\nGoogle Forwarding",
]


def _cargo(fields):
    lines = ["Weight: %g kg" % fields["weight_kg_total"]]
    if fields.get("volume_cbm_total"):
        lines.append("Volume: %g cbm" % fields["volume_cbm_total"])
    for p in fields.get("pieces") or []:
        if p.get("l_cm") and p.get("w_cm") and p.get("h_cm"):
            lines.append("%s x %gx%gx%g cm" % (p.get("count") or 1, p["l_cm"], p["w_cm"], p["h_cm"]))
    return "\n".join(lines)


def _ask(tid, carrier, email, role, required, subject, templates, ctx):
    cur = db.con().execute("INSERT INTO bids(thread_id,carrier,kind,email,role,required,status,requested_at) VALUES(?,?,?,?,?,?,?,?)",
                           (tid, carrier, role, email.lower(), role, 1 if required else 0, "asked", time.time()))
    bid_id = cur.lastrowid
    body = templates[bid_id % len(templates)].format(**ctx)
    ok = mailbox.send(email, "%s [BID-%d]" % (subject, bid_id), body, thread_id=tid, event="bid_mail_out")
    if not ok:
        db.con().execute("UPDATE bids SET status='send_failed', replied_at=? WHERE id=?", (time.time(), bid_id))
    db.event("bid_requested", tid, bid_id=bid_id, carrier=carrier, role=role, required=required, sent=ok)
    return ok


def request(session, fields):
    """Mail everyone we need a price from. Returns the number of REQUIRED answers we now wait for."""
    ensure()
    tid = session["thread_id"]
    if rows(tid):                                     # already asked (clarify re-entry, restart): never ask twice
        return sum(1 for b in rows(tid) if b["required"] and not b["replied_at"])
    o, d = fields["origin"].upper(), fields["destination"].upper()
    options = json.loads(session.get("options") or "[]")
    ctx = {"origin": o, "destination": d, "cargo": _cargo(fields), "postcode": str(fields.get("pickup_postcode") or "")}
    pending = 0

    if ctx["postcode"]:                               # door pickup: every trucker of the zone
        for c in serving("trucker", ctx["postcode"][:2]):
            pending += _ask(tid, c["name"], c["email"], "trucker", True,
                            "Pickup %s to %s airport, %g kg" % (ctx["postcode"], o, fields["weight_kg_total"]), TRUCK_MAILS, ctx)

    subject = "Rate request %s-%s, %g kg" % (o, d, fields["weight_kg_total"])
    banned = _banned(tid)
    airlines = [c for c in serving("airline", d) if c["name"].lower() not in banned]   # do not even ask an excluded airline
    from sourcing import portal
    portal_down = getattr(portal, "LAST_DOWN", False)     # 5U turned the portal rate API off (503): its airlines are missing from options
    if not options or portal_down:                    # no price, OR the portal is down: ask the airlines and the rate desk, and wait
        for c in airlines:
            pending += _ask(tid, c["name"], c["email"], "airline", True, subject, AIR_MAILS, ctx)
        pending += _ask(tid, "Rate desk", RATEDESK, "ratedesk", True, subject, AIR_MAILS, ctx)
    elif config.BID_ALWAYS:                           # we have a price, but a bid usually beats it: ask carriers + desk and WAIT
        priced = {x["airline"] for x in options}      # unpriced airlines first: those give us new prices to compare
        for c in sorted(airlines, key=lambda c: c["name"] in priced)[:config.BID_MAX_CARRIERS]:
            pending += _ask(tid, c["name"], c["email"], "airline", True, subject, AIR_MAILS, ctx)
        pending += _ask(tid, "Rate desk", RATEDESK, "ratedesk", True, subject, AIR_MAILS, ctx)
    elif config.BID_EXPERIMENT:                       # learn only: asked, logged, never waited for
        priced = {x["airline"] for x in options}
        for c in sorted(airlines, key=lambda c: c["name"] not in priced)[:3]:
            _ask(tid, c["name"], c["email"], "airline", False, subject, AIR_MAILS, ctx)
    return pending


# ---------------------------------------------------------------- reading answers

SYSTEM = """You read a carrier's answer to our price request and return JSON only:
{
 "declined": true if they cannot or will not quote, else false,
 "total": the all-in total price as a number if they state one total, else null,
 "rate_per_kg": price per kg if they quote per kg, else null,
 "surcharges_per_kg": sum of all per-kg surcharges (fuel, security, ...) if stated separately, else 0,
 "flat_fees": sum of all fixed fees stated separately, else 0,
 "min_charge": minimum charge if stated, else null,
 "currency": 3-letter currency code, or null,
 "fx_to_eur": how many EUR one unit of that currency is, only if the mail states an exchange rate, else null,
 "transit_days": transit or delivery time in days as a number if stated in days, else null,
 "transit_hours": transit or delivery time in hours as a number if stated in hours, else null,
 "airline": airline name if the mail names the airline that would fly, else null,
 "unclear": short note if the answer is a question, conditional, or for a different weight/route, else null
}
Copy numbers as written. Do not calculate."""


def _num(x):
    try:
        return Decimal(str(x)) if x not in (None, "") else None
    except InvalidOperation:
        return None


def read_answer(mail):
    """One tiny gateway call. Returns (form, cost_usd)."""
    text = "Subject: %s\n\n%s" % (mail["subject"], mail["body"][:4000])
    files = attachments.as_text(mail)                 # 5U 22:17: the offer is in the attached file, the mail only points to it
    if files:
        text += "\n\n[The offer is in the attached file. The file as text:]\n" + files
    if config.LLM_FAKE:
        m = re.search(r"(\d[\d.,]*)\s*(EUR|USD|CHF|GBP)", text, re.I)
        d = re.search(r"(\d+)\s*(?:days?|tage?)", text, re.I)
        h = re.search(r"(\d+)\s*(?:hours?|stunden|h\b)", text, re.I)
        declined = bool(re.search(r"\b(cannot|can't|unable|no capacity|decline|leider nicht)\b", text, re.I))
        return {"declined": declined, "total": float(m.group(1).replace(",", "")) if m and not declined else None,
                "currency": m.group(2).upper() if m else None, "transit_days": int(d.group(1)) if d else None,
                "transit_hours": int(h.group(1)) if h else None}, None
    status, data = mailbox.api("POST", "/v1/gateway/chat/completions", timeout=20, body={
        "model": config.LLM_MODEL, "max_completion_tokens": 200, "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]})
    if status != 200:
        raise RuntimeError("gateway %s: %s" % (status, str(data)[:200]))
    u = data.get("usage") or {}
    cost = round(((u.get("prompt_tokens") or 0) * 0.15 + (u.get("completion_tokens") or 0) * 0.60) / 1e6, 6)
    return json.loads(data["choices"][0]["message"]["content"]), cost


def bid_total(form, chargeable_kg):
    """The all-in total from the form. All math is here, not in the LLM. None if the form has no usable price."""
    total, rate = _num(form.get("total")), _num(form.get("rate_per_kg"))
    if total is None and rate is not None and chargeable_kg:
        cw = Decimal(str(chargeable_kg))
        freight = max(rate * cw, _num(form.get("min_charge")) or Decimal(0))
        total = freight + (_num(form.get("surcharges_per_kg")) or 0) * cw + (_num(form.get("flat_fees")) or 0)
    return total.quantize(Decimal("0.01")) if total is not None and total > 0 else None


def _hours(form):
    """Transit time in hours, from hours or days. Truckers answer in hours ("29 hours"), airlines in days."""
    h, d = _num(form.get("transit_hours")), _num(form.get("transit_days"))
    return float(h) if h is not None else float(d * 24) if d is not None else None


def _fx(currency, form, session):
    """EUR per 1 unit of currency: stated in the mail, else taken from a portal price of this session."""
    if currency == "EUR":
        return Decimal(1)
    if _num(form.get("fx_to_eur")):
        return _num(form["fx_to_eur"])
    for x in json.loads(session.get("options") or "[]"):
        if x.get("currency") == currency and Decimal(x["total"]) > 0:
            return Decimal(x["total_eur"]) / Decimal(x["total"])
    return None


def _find(mail):
    m = REF.search(mail["subject"] + " " + mail["body"])
    if m:
        r = db.con().execute("SELECT * FROM bids WHERE id=?", (int(m.group(1)),)).fetchone()
        if r and r["email"] == mail["sender"]:
            return dict(r)
    # No reference in the mail: accept it only for a bid we are waiting on (never for experiment bids, so an
    # answer to someone else's mail, e.g. a booking request, is not read as a price).
    r = db.con().execute("SELECT * FROM bids WHERE email=? AND required=1 AND replied_at IS NULL AND requested_at>? ORDER BY id DESC LIMIT 1",
                         (mail["sender"], time.time() - 1800)).fetchone()
    return dict(r) if r else None


def on_bounce(mail):
    """Our bid mail came back undelivered: that carrier will never answer, so the quote must not wait for it."""
    ensure()
    m = REF.search((mail.get("subject") or "") + " " + (mail.get("body") or ""))
    r = db.con().execute("SELECT * FROM bids WHERE id=?", (int(m.group(1)),)).fetchone() if m else None
    if r and not r["replied_at"]:
        db.con().execute("UPDATE bids SET replied_at=?, status='send_failed', note=? WHERE id=?",
                         (time.time(), "our bid mail bounced", r["id"]))
    db.event("bid_bounced" if r else "bounce", r["thread_id"] if r else mail.get("thread_id"), mail.get("id"),
             bid_id=r["id"] if r else None, sender=mail.get("sender"), subject=mail.get("subject"))


def on_reply(mail):
    ensure()
    bid = _find(mail)
    if not bid:                                       # e.g. an answer to Patrick's booking mail: not ours
        return db.event("carrier_mail_unmatched", mail["thread_id"], mail["id"], sender=mail["sender"])
    if bid["replied_at"]:
        return db.event("bid_extra_reply_ignored", bid["thread_id"], mail["id"], bid_id=bid["id"])
    tid, now = bid["thread_id"], time.time()
    session = db.session(tid) or {}
    if mail.get("attachments") and "attachments_text" not in mail:
        attachments.read(mail)
    lost = attachments.unreadable(mail)
    try:
        if lost and not attachments.as_text(mail) and not PRICE.search(mail["body"]):
            # a voice message (.mp3) or a photo: answered, but not a price we can use. No gateway call, and the quote
            # does not wait for this carrier any longer.
            form, cost = {"unclear": "offer is in a file we cannot read: %s" % ", ".join(lost)}, None
        else:
            form, cost = read_answer(mail)
    except Exception as e:                            # gateway down: the bid counts as answered but unusable
        form, cost = {"unclear": "could not read: %s" % e}, None
    stated = lead_hours(mail["body"] + "\n" + attachments.as_text(mail)) if bid["role"] == "trucker" else None
    if stated is not None and not form.get("declined") and form.get("transit_hours") != stated:
        form["transit_hours_model"], form["transit_hours"] = form.get("transit_hours"), stated
    fields = json.loads(session.get("fields") or "{}")
    chargeable = max(fields.get("weight_kg_total") or 0, (fields.get("volume_cbm_total") or 0) * 167)
    currency = (form.get("currency") or "EUR").upper()
    total = None if form.get("declined") else bid_total(form, chargeable)
    fx = _fx(currency, form, session) if total is not None else None
    status = ("declined" if form.get("declined") else "unclear" if total is None   # a parsed total is kept; the note says why it was unsure
              else "no_fx" if fx is None else "ok")
    total_eur = str((total * fx).quantize(Decimal("0.01"))) if status == "ok" else None
    carrier = form.get("airline") if bid["role"] == "ratedesk" and form.get("airline") else bid["carrier"]
    hours = _hours(form)
    days = form.get("transit_days") if form.get("transit_days") is not None else (round(hours / 24, 2) if hours is not None else None)
    db.con().execute("UPDATE bids SET replied_at=?, total=?, currency=?, transit_days=?, hours=?, total_eur=?, status=?, note=?, carrier=?, raw=? WHERE id=?",
                     (now, str(total) if total is not None else None, currency, days, hours, total_eur, status,
                      form.get("unclear"), carrier, (mail["body"] + "\n\n" + attachments.as_text(mail))[:4000], bid["id"]))
    if cost and session:
        db.update_session(tid, llm_cost_usd=(session.get("llm_cost_usd") or 0) + cost)
    db.event("bid_received", tid, mail["id"], bid_id=bid["id"], carrier=carrier, role=bid["role"], status=status,
             total=str(total) if total is not None else None, currency=currency, total_eur=total_eur,
             transit_days=days, hours=hours, seconds=round(now - bid["requested_at"], 1),
             late=session.get("status") not in ("new", "waiting_bids"), form=form)


# ---------------------------------------------------------------- using the answers

def _usable(thread_id, role):
    return [b for b in rows(thread_id) if b["status"] == "ok" and (b["role"] == role or (role == "airline" and b["role"] == "ratedesk"))]


def must_wait(thread_id):
    """True while a leg we cannot quote without is still missing AND someone may still answer."""
    bs = rows(thread_id)
    open_roles = {("airline" if b["role"] == "ratedesk" else b["role"]) for b in bs if b["required"] and not b["replied_at"]}
    s = db.session(thread_id)
    need_truck = any(b["role"] == "trucker" for b in bs)
    no_flight = not json.loads(s.get("options") or "[]")
    return ((need_truck and not _usable(thread_id, "trucker") and "trucker" in open_roles)
            or (no_flight and not _usable(thread_id, "airline") and "airline" in open_roles))


def _f(x):
    """float or None: a transit time written as text ('1-2', '2 days') must never crash a quote (review 21 Nov)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        m = re.findall(r"\d+(?:[.,]\d+)?", str(x or ""))
        return float(m[-1].replace(",", ".")) if m else None   # '1-2' -> 2: the slower end, never an optimistic promise


def bid_hours(b):
    """Hours of a bid row. Old rows have only transit_days."""
    if _f(b.get("hours")) is not None:
        return _f(b["hours"])
    return _f(b.get("transit_days")) * 24 if _f(b.get("transit_days")) is not None else None


def pick_bid(bids_, prefer):
    """Which bid is the right one. Default BID_PICK=balanced: the board shows 5U's scorer always takes the balanced
    bid (see core/config.py). BID_PICK=auto uses the booth's answer (21 Nov) instead:
      customer asks for fast            -> the fastest bid (price breaks a tie)
      customer asks for cheapest        -> the cheapest bid
      customer states no preference     -> BALANCED: price and speed count 50/50, not simply the cheapest
    Balanced score = (price / lowest price + time / shortest time) / 2, lowest wins. The exact formula of 5U's
    scorer is not known: check door-pickup rounds on the board and change it HERE if it is off.
    BID_PICK=cheapest|balanced|fastest overrides the rule."""
    mode = config.BID_PICK if config.BID_PICK != "auto" else {"fastest": "fastest", "cheapest": "cheapest"}.get(
        (prefer or "").lower(), "balanced")
    price = lambda b: Decimal(b["total_eur"])                      # noqa: E731
    known = [bid_hours(b) for b in bids_ if bid_hours(b) is not None]
    if mode == "cheapest" or not known:                            # no speed known at all: price is all we have
        return min(bids_, key=price), "cheapest" if mode == "cheapest" else "cheapest_no_times"
    slowest = max(known)
    hours = lambda b: bid_hours(b) if bid_hours(b) is not None else slowest   # noqa: E731  unknown time = slowest
    if mode == "fastest":
        return min(bids_, key=lambda b: (hours(b), price(b))), "fastest"
    pmin, tmin = min(price(b) for b in bids_), max(min(hours(b) for b in bids_), 1.0)
    return min(bids_, key=lambda b: (float(price(b) / pmin) + max(hours(b), 1.0) / tmin) / 2), "balanced"


def _banned(thread_id):
    """Lower-case names of the airlines this customer told us never to offer (core/main.py excluded_airlines)."""
    try:
        from core import main
        return {n.lower() for n in main.excluded_airlines(thread_id)}
    except Exception as e:                            # never let this stop a quote
        db.event("excluded_airlines_error", thread_id, error=str(e))
        return set()


def final_options(thread_id, options):
    """Sheet/portal options + airline bids, each with the trucker leg added when it is a door pickup."""
    bs = rows(thread_id)
    if not bs:
        return options
    s = db.session(thread_id)
    fields = json.loads(s["fields"])
    prefer = fields.get("prefer")
    air = [b for b in _usable(thread_id, "airline") if b["required"]]
    banned = _banned(thread_id)                       # "please do not offer Zephyr (ZS)": never pick that bid, so the
    air = [b for b in air if (b["carrier"] or "").lower() not in banned]   # next best one is quoted, not nothing
    if options and air:                               # portal down (503): sheets AND mailed airline bids compete
        for b in air:                                 # a mailed price competes even when the same airline has a portal/
            # sheet price: since 5U's 19:15 change the bid is often CHEAPER (round 33: winners booked Borealis, a portal
            # airline). The cheaper/faster of the two wins in finalize; Patrick's outlier check drops a misread bid.
            days = b["transit_days"] if b["transit_days"] is not None else 99   # unknown speed never wins "fastest"
            options = options + [{"airline": b["carrier"], "origin": fields.get("origin"),
                                  "destination": fields.get("destination"), "transit_days": int(-(-(_f(days) if _f(days) is not None else 99) // 1)),
                                  "currency": b["currency"], "total": b["total"], "total_eur": b["total_eur"],
                                  "source": "bid", "bid_id": b["id"]}]
        db.event("bids_merged", thread_id, added=[[b["carrier"], b["total_eur"], b["transit_days"]] for b in air])
    if not options and air:                           # lane priced by bids only
        if (prefer or "").lower() in ("cheapest", "fastest"):   # explicit wish: add EVERY bid, let finalize honour it.
            # A single balanced pre-pick quoted the faster bid on a 'cheapest' request (round 47 STR-EZE: Nova Atlas 1833
            # was cheapest, we quoted Fjordline 2604 -> too_high).
            for b in air:
                days = b["transit_days"] if b["transit_days"] is not None else 99   # unknown speed never wins "fastest"
                options = options + [{"airline": b["carrier"], "origin": fields.get("origin"),
                                      "destination": fields.get("destination"), "transit_days": int(-(-float(days) // 1)),
                                      "currency": b["currency"], "total": b["total"], "total_eur": b["total_eur"],
                                      "source": "bid", "bid_id": b["id"]}]
            db.event("bids_only_options", thread_id, prefer=prefer,
                     candidates=[[b["carrier"], b["total_eur"], b["transit_days"]] for b in air])
        else:                                         # no stated preference: the balanced bid (5U's scorer default)
            b, how = pick_bid(air, prefer)
            db.event("bid_picked", thread_id, role="airline", how=how, carrier=b["carrier"], total_eur=b["total_eur"],
                     candidates=[[x["carrier"], x["total_eur"], bid_hours(x)] for x in air])
            days = b["transit_days"] if b["transit_days"] is not None else 0
            options = [{"airline": b["carrier"], "origin": fields.get("origin"), "destination": fields.get("destination"),
                        "transit_days": int(-(-(_f(days) if _f(days) is not None else 99) // 1)), "currency": b["currency"], "total": b["total"],
                        "total_eur": b["total_eur"], "source": "bid", "bid_id": b["id"]}]
    if any(b["role"] == "trucker" for b in bs):       # door pickup: no trucker price means no quote
        trucks = _usable(thread_id, "trucker")
        if not trucks:
            db.event("no_trucker_bid", thread_id, asked=sum(1 for b in bs if b["role"] == "trucker"))
            return []
        t, how = pick_bid(trucks, prefer)
        db.event("bid_picked", thread_id, role="trucker", how=how, carrier=t["carrier"], total_eur=t["total_eur"],
                 candidates=[[x["carrier"], x["total_eur"], bid_hours(x)] for x in trucks])
        out = []
        for x in options:
            eur = Decimal(x["total_eur"]) + Decimal(t["total_eur"])
            same = x["currency"] == t["currency"]         # mixed currencies: quote the sum in EUR
            out.append(dict(x, total_eur=str(eur), currency=x["currency"] if same else "EUR",
                            total=str(Decimal(x["total"]) + Decimal(t["total"])) if same else str(eur),
                            flight_total=x["total"], flight_currency=x["currency"], trucker=t["carrier"],
                            trucker_total=t["total"], trucker_currency=t["currency"], trucker_total_eur=t["total_eur"]))
        options = out
    db.update_session(thread_id, options=options)
    return options
