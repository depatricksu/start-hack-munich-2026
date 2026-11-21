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
from core import config, db, mailbox

_KIT = os.path.join(config.ROOT, "kit", "start-kit")
CARRIERS = list(csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv"))))
RATEDESK = "ratedesk@hackloop.mail"
REF = re.compile(r"\bBID-(\d+)\b", re.I)
EXTRA_COLUMNS = {"email": "TEXT", "role": "TEXT", "required": "INTEGER DEFAULT 1", "status": "TEXT",
                 "total_eur": "TEXT", "note": "TEXT"}
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
    airlines = serving("airline", d)
    if not options:                                   # nobody priced the lane: ask them all, and the rate desk, at once
        for c in airlines:
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
 "transit_days": transit or delivery time in days as a number (same day = 0), or null,
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
    if config.LLM_FAKE:
        m = re.search(r"(\d[\d.,]*)\s*(EUR|USD|CHF|GBP)", text, re.I)
        d = re.search(r"(\d+)\s*(?:days?|tage?)", text, re.I)
        declined = bool(re.search(r"\b(cannot|can't|unable|no capacity|decline|leider nicht)\b", text, re.I))
        return {"declined": declined, "total": float(m.group(1).replace(",", "")) if m and not declined else None,
                "currency": m.group(2).upper() if m else None, "transit_days": int(d.group(1)) if d else None}, None
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


def on_reply(mail):
    ensure()
    bid = _find(mail)
    if not bid:                                       # e.g. an answer to Patrick's booking mail: not ours
        return db.event("carrier_mail_unmatched", mail["thread_id"], mail["id"], sender=mail["sender"])
    if bid["replied_at"]:
        return db.event("bid_extra_reply_ignored", bid["thread_id"], mail["id"], bid_id=bid["id"])
    tid, now = bid["thread_id"], time.time()
    session = db.session(tid) or {}
    try:
        form, cost = read_answer(mail)
    except Exception as e:                            # gateway down: the bid counts as answered but unusable
        form, cost = {"unclear": "could not read: %s" % e}, None
    fields = json.loads(session.get("fields") or "{}")
    chargeable = max(fields.get("weight_kg_total") or 0, (fields.get("volume_cbm_total") or 0) * 167)
    currency = (form.get("currency") or "EUR").upper()
    total = None if form.get("declined") else bid_total(form, chargeable)
    fx = _fx(currency, form, session) if total is not None else None
    status = ("declined" if form.get("declined") else "unclear" if total is None   # a parsed total is kept; the note says why it was unsure
              else "no_fx" if fx is None else "ok")
    total_eur = str((total * fx).quantize(Decimal("0.01"))) if status == "ok" else None
    carrier = form.get("airline") if bid["role"] == "ratedesk" and form.get("airline") else bid["carrier"]
    db.con().execute("UPDATE bids SET replied_at=?, total=?, currency=?, transit_days=?, total_eur=?, status=?, note=?, carrier=?, raw=? WHERE id=?",
                     (now, str(total) if total is not None else None, currency, form.get("transit_days"), total_eur, status,
                      form.get("unclear"), carrier, mail["body"][:4000], bid["id"]))
    if cost and session:
        db.update_session(tid, llm_cost_usd=(session.get("llm_cost_usd") or 0) + cost)
    db.event("bid_received", tid, mail["id"], bid_id=bid["id"], carrier=carrier, role=bid["role"], status=status,
             total=str(total) if total is not None else None, currency=currency, total_eur=total_eur,
             transit_days=form.get("transit_days"), seconds=round(now - bid["requested_at"], 1),
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


def best_balanced(options):
    """5U's rule for carrier bids: price and speed count 50/50. Lower score is better."""
    pmin = min(Decimal(x["total_eur"]) for x in options)
    tmin = max(min(x["transit_days"] for x in options), 1)
    return min(options, key=lambda x: (Decimal(x["total_eur"]) / pmin + Decimal(max(x["transit_days"], 1)) / tmin) / 2)


def final_options(thread_id, options):
    """Sheet/portal options + airline bids, each with the trucker leg added when it is a door pickup."""
    bs = rows(thread_id)
    if not bs:
        return options
    s = db.session(thread_id)
    fields = json.loads(s["fields"])
    if not options:                                   # lane priced by bids only: balanced pick among them
        flights = [{"airline": b["carrier"], "origin": fields.get("origin"), "destination": fields.get("destination"),
                    "transit_days": int(b["transit_days"]), "currency": b["currency"], "total": b["total"],
                    "total_eur": b["total_eur"], "source": "bid", "bid_id": b["id"]}
                   for b in _usable(thread_id, "airline") if b["required"] and b["transit_days"] is not None]
        options = [best_balanced(flights)] if flights else []
    if any(b["role"] == "trucker" for b in bs):       # door pickup: no trucker price means no quote
        trucks = _usable(thread_id, "trucker")
        if not trucks:
            db.event("no_trucker_bid", thread_id, asked=sum(1 for b in bs if b["role"] == "trucker"))
            return []
        t = min(trucks, key=lambda b: Decimal(b["total_eur"]))
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
