"""The clerk: the one program that runs all night.

    DRY_RUN=1 python -m core.main                      # everyone: reads the mailbox, never sends
    DRY_RUN=0 caffeinate -i python -m core.main        # ERIK'S MACBOOK ONLY
    LLM_FAKE=1 python -m core.main --fake examples/rfq.json   # no key, no network: one fake mail

Loop: poll mailbox -> save mail -> router decides the route -> HANDLERS[route](mail).
To add a feature, write a handler in your own folder and register it in HANDLERS below.
"""
import csv, json, os, re, sys, time, traceback, urllib.error
from decimal import Decimal
from . import attachments, config, db, imports, mailbox, safety, offer_file, recall, scope
from router.route import route, lookalike, ADDRESS_SWITCH
from llm import extract as llm
from pricing import price as sheets, insurance, customs
from sourcing import portal, portal_page
from actions import queue as actions            # take-over queue: sends human replies typed in the UI
from shared.rfq import gate as rfq_gate
from pricing import multi, tariff_mail
from llm import clarify

from sourcing import bids                               # truckers, rare lanes, rate desk: prices by mail (Kai)
from booking import tracking
from booking import handlers as booking                 # task 04: accept -> book -> keep the customer informed
import humanize                                         # last touch on the quote mail (Riky)
import dg                                               # dangerous goods in attachments -> the quote (Riky)

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
    pieces = [p for p in pieces if isinstance(p, dict)] if isinstance(pieces, list) else []   # the model once sent [6] for
    # "six pieces" (22 Nov 02:20, the answer to our question): 'int' object has no attribute 'get', the request went to a person
    pieces_kg = sum((p.get("count") or 1) * (p.get("kg_each") or 0) for p in pieces)
    pieces_cbm = sum((p.get("count") or 1) * (p.get("l_cm") or 0) * (p.get("w_cm") or 0) * (p.get("h_cm") or 0)
                     for p in pieces) / 1e6
    group_kg = [(p.get("count") or 1) * (p.get("kg_each") or 0) for p in pieces]
    group_cbm = [(p.get("count") or 1) * (p.get("l_cm") or 0) * (p.get("w_cm") or 0) * (p.get("h_cm") or 0) / 1e6
                 for p in pieces]
    weight = _total(float(f.get("weight_kg") or 0), pieces_kg, group_kg)
    volume = _total(float(f.get("volume_cbm") or 0), pieces_cbm, group_cbm)
    return float(weight or 0), float(volume or 0)


def _is_one_group(stated, groups):
    """The stated total is exactly ONE of several piece groups: the model copied lot 1 into weight_kg AND listed it
    as the first piece. Live round 62 (21 Nov, CGN-SCL): lots 465 + 3x160 + 3x59 kg = 1,122 kg, weight_kg 465 and
    the 465 kg lot again in pieces -> priced 1,587 kg, accuracy 37.5 of 45. Within 1 %: a real extra lot that
    weighs the same as a listed one to the kilo is far rarer than this copy."""
    return len([g for g in groups if g]) >= 2 and any(g and abs(stated - g) <= 0.01 * stated for g in groups)


def _total(stated, from_pieces, groups=()):
    """The model often gives the SAME total twice: 'weight_kg': 676 and pieces 12 x 56.33 kg (= 676). That is one
    shipment, not two lots: adding them doubled the weight (real requests 268, 1631, 5246 -> priced as 1,352 kg,
    rejected too high). Equal within 2 % -> one total. Different -> separate lots, add them (round 9). (Riky)"""
    if stated and from_pieces and abs(stated - from_pieces) <= 0.15 * max(stated, from_pieces):   # rounded piece weights (500 vs 4x120) are one total; real separate lots differ far more (round 9: 67 %)
        return stated
    if stated and from_pieces and _is_one_group(stated, groups):
        return from_pieces
    return stated + from_pieces


def handle_rfq(mail):
    tid = mail["thread_id"]
    db.new_session(mail)
    age = time.time() - mail["received_at"]
    if age > config.RFQ_MAX_AGE_S:
        db.update_session(tid, status="expired", note="mail was %d s old when we saw it" % age)
        return db.event("rfq_expired", tid, mail["id"], age_s=round(age))

    fields, usage = llm.extract(attachments.for_llm(mail))  # the one gateway call (+ attachment text if ATTACH_LLM=1)
    db.event("llm", tid, mail["id"], fields=fields, usage=usage)
    fields["dg"] = dg.check_mail(mail)                      # DG declared only in the attachment (5U change ~17:00)
    if fields["dg"]:
        db.event("dg", tid, mail["id"], dg=fields["dg"], mode=dg.mode())
    fields["origin"] = _airport(fields.get("origin"))        # the string "NULL" must not block zone->airport
    fields["destination"] = _airport(fields.get("destination"))
    try:
        recall.merge(mail, fields)                          # "the same shipment as in my earlier request ...": from our records
    except Exception as e:                                   # an extra: never lose the request over it
        db.event("error", tid, mail["id"], error="recall.merge: %s" % e)
    postcode = str(fields.get("pickup_postcode") or "")
    if not fields.get("origin") and postcode[:2] in ZONE_AIRPORT:
        fields["origin"] = ZONE_AIRPORT[postcode[:2]]
    weight, volume = shipment(fields)
    diff = dg.compare(dict(fields, weight_kg_total=weight, volume_cbm_total=volume), mail)   # attachment vs mail (Riky)
    if diff:
        disowned = dg.mail_disowns_attachment(mail.get("body"))   # "the attached packing list is outdated": the mail wins
        db.event("attachment_mismatch", tid, mail["id"], diff=diff, override=dg.override() and not disowned, disowned=disowned)
        if dg.override() and not disowned:                   # the packing list is the shipping document: price on it
            used = {}
            if "gross_kg" in diff and dg.winner(diff["gross_kg"]) != weight:
                weight, used["gross_kg"] = dg.winner(diff["gross_kg"]), diff["gross_kg"]
            if "volume_cbm" in diff and dg.winner(diff["volume_cbm"]) != volume:
                volume, used["volume_cbm"] = dg.winner(diff["volume_cbm"]), diff["volume_cbm"]
            if used:
                fields["attachment_used"] = used             # dg.note() says so in the quote
    fields["weight_kg_total"], fields["volume_cbm_total"] = weight, volume
    db.update_session(tid, fields=fields, reply_template=fields.get("reply") or "", llm_cost_usd=usage.get("cost_usd"))
    price_and_quote(tid, mail, fields)


def origin_from_pickup(tid, fields):
    """Door pickup: the departure airport comes from the pickup postcode (kit/start-kit/pickup_zones.csv), not from
    the model. Round 17 (21 Nov): the customer gave only "72146 Tuebingen", the model filled in FRA, we priced
    FRA-EZE and trucked to FRA, and 5U rejected it as too_low: the right lane was STR-EZE. All 11 real door-pickup
    requests so far that were accepted had origin == zone airport.
    The model's airport only stays when the CUSTOMER wrote that airport or city in their own mails."""
    postcode = str(fields.get("pickup_postcode") or "")
    zone_airport = ZONE_AIRPORT.get(postcode[:2])
    current = str(fields.get("origin") or "").upper()
    if not zone_airport or current == zone_airport:
        return
    s = db.session(tid) or {}
    text = "\n".join("%s\n%s" % (r["subject"] or "", r["body"] or "") for r in db.con().execute(
        "SELECT subject, body FROM mails WHERE thread_id=? AND sender=? ORDER BY id", (tid, s.get("customer") or "")))
    from shared.rfq import extract_rfq
    said = (extract_rfq("", text).origin or "").upper()
    if current and said == current:                          # the customer really asked for another airport
        return db.event("origin_kept", tid, origin=current, zone_airport=zone_airport, postcode=postcode)
    fields["origin"] = zone_airport
    fields.setdefault("filled_by_code", []).append("origin")
    db.update_session(tid, fields=fields)
    db.event("origin_from_pickup", tid, was=current or None, now=zone_airport, postcode=postcode)


def price_and_quote(tid, mail, fields, asked=False):
    """Everything after the gateway call. Also re-entered by llm/clarify.py when the customer answered our question."""
    origin_from_pickup(tid, fields)
    postcode = str(fields.get("pickup_postcode") or "")
    weight, volume = fields.get("weight_kg_total") or 0, fields.get("volume_cbm_total") or 0
    if scope.sea(mail):                                      # a container by sea: not ours, say so at once (5U 09:50)
        return scope.decline_sea(tid, mail, fields)
    if len(fields.get("shipments") or []) > 1:               # several shipments in one mail (pricing/multi.py, Patrick)
        return multi.handle(tid, mail, fields)
    ok, note = rfq_gate(fields, mail)                       # shared/rfq.py (Patrick): stop or warn, with reason codes
    db.event("gate", tid, mail["id"], ok=ok, note=note)
    if not ok:
        into = imports.lane(fields, mail)                    # a flight INTO Germany: nobody offers it, say so (5U 08:01)
        if into:
            return imports.decline(tid, mail, fields, *into)
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
        options += [x for x in portal.options(o, d, weight, volume) if not x.get("fx_missing")]   # a USD price with no
        # exchange rate must never be summed with an EUR trucker and labelled EUR (multi.py already drops these)
    except Exception as e:                                   # portal down: sheets still work
        db.event("portal_error", tid, mail["id"], error=str(e))
    db.update_session(tid, options=options)
    db.event("options", tid, mail["id"], count=len(options), options=options)

    pending = bids.request(db.session(tid), fields)          # mails to carriers/truckers
    if pending:
        db.update_session(tid, status="waiting_bids")
        if getattr(portal, "LAST_DOWN", False):              # rate API 503: its airlines' prices are only on the portal page
            try:
                portal_page.hold(tid, mail["id"], options)   # waits only for an automated portal page source, never for a person
            except Exception as e:                           # the hold is an extra: never lose the quote over it
                db.event("error", tid, mail["id"], error="portal_page.hold: %s" % e)
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


# Pauses before the 2nd and 3rd try of a quote send that FAILED. After the last one the session is `failed`.
SEND_RETRY_WAITS_S = tuple(float(x) for x in os.environ.get("SEND_RETRY_WAITS_S", "2,5").split(",") if x.strip())


def send_quote(tid, to, subject, body, attachments=None):
    """Send the one quote of a thread; a failed send is tried again, a send that may have worked never is.

    Retried: mailbox.send returned False (5U answered with an error status instead of 201; its own 429 waits are
    already used up) or the connection failed before the request left (URLError: DNS, refused, connect timeout).
    NOT retried: anything raised after the request went out (read timeout, dropped connection). 5U may have
    stored the mail and we cannot list our sent mails, so a second send could be a second quote: that error goes
    up to the caller, as before. The caller holds the claim_for_sending lock, so nothing else sends meanwhile.
    Left over: a 5xx counts as "not sent", which is what HTTP promises but 5U does not state."""
    for attempt, wait in enumerate((0,) + SEND_RETRY_WAITS_S):
        if attempt:
            db.event("quote_send_retry", tid, attempt=attempt, wait_s=wait)
            time.sleep(wait)
        try:
            if mailbox.send(to, subject, body, in_reply_to=tid, thread_id=tid, attachments=attachments):
                return True
        except urllib.error.URLError as e:                   # never reached 5U: safe to send again
            db.event("quote_send_error", tid, attempt=attempt, error=str(e))
        except Exception as e:                               # outcome unknown: do not risk a second quote
            db.event("quote_send_unknown", tid, attempt=attempt, error="%s: %s" % (type(e).__name__, e))
            raise
    return False


ARRIVE_BY = r"arriv\w*|latest|no later|deadline|spätestens|must|needed|benötigt|before|ankommen|eintreffen|vor Ort"


def max_transit_days(text):
    """'Ready 24 Nov, MUST arrive by 27 Nov' -> 3. None when the mail states no arrival deadline (or no ready date).
    Red-team run 21 Nov: 'cheapest, but must arrive by ...' got the 6-day flight that lands 3 days late.
    Only strong arrival words count: 'we deliver to FRA on <date>' is a drop-off, not a deadline."""
    from humanize.polish import _dates_near, _ready_date, READY_WORDS
    ready = _ready_date(text or "")
    ready_all = set(_dates_near(text or "", READY_WORDS, before=25, whole_word=False))   # tight: own words only
    dl = [d for d in _dates_near(text or "", ARRIVE_BY) if d not in ready_all]
    if not ready or not dl or min(dl) <= ready:
        return None
    return (min(dl) - ready).days


def _days(x):
    try:
        return float(x["transit_days"])
    except (KeyError, TypeError, ValueError):
        return None


# A price this far from the middle of the request's own options is a reading error, not a deal: a per-kg rate read
# as the total, a thousands separator, a missing exchange rate. Real spread on 21 Nov: 0.51x to 2.43x of the median.
OUTLIER_LOW = Decimal(os.environ.get("PRICE_OUTLIER_LOW", "0.35"))
OUTLIER_HIGH = Decimal(os.environ.get("PRICE_OUTLIER_HIGH", "4"))


_NO = re.compile(r"\b(?:do not|don'?t|never|no longer|not|exclude\w*|avoid\w*|nicht|keine?n?|ohne|niemals)\b", re.I)
_USE = re.compile(r"\b(?:offer\w*|use|using|book\w*|quot\w*|fly|flying|ship\w*|send|rout\w*|via|with|carrier|airline|"
                  r"anbiet\w*|buch\w*|nehm\w*|flieg\w*|mit|exclude\w*|avoid\w*)\b", re.I)


def _airline_names():
    """name -> name for every airline we can quote (sheets, carrier list, portal), plus 2-letter codes."""
    names = {r["airline"] for r in sheets._TARIFFS} | {c["name"] for c in bids.CARRIERS if c["kind"] == "airline"}
    for airlines in getattr(portal, "LANES", {}).values():
        names |= {a.get("name") if isinstance(a, dict) else a for a in airlines}
    return {n for n in names if n}


def excluded_airlines(tid):
    """Airlines the customer told us never to offer: 'Please do not offer Zephyr Steppe Cargo (ZS) for this shipment
    or for any of our future inquiries' (5U, 21 Nov 20:09). Read from ALL mails of this customer, earlier threads too,
    so 'future inquiries' are honoured. A sentence counts when it has a no-word, a use-word and the airline's full name,
    its first word or its code in brackets."""
    s = db.session(tid) or {}
    sender = (s.get("customer") or "").lower()
    if not sender:
        return set()
    text = "\n".join("%s\n%s" % (r["subject"] or "", re.split(r"\n\s*(?:>|On .+wrote:|Am .+schrieb)", r["body"] or "")[0])
                     for r in db.con().execute("SELECT subject, body FROM mails WHERE sender=?", (sender,)))
    out = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if not (_NO.search(sentence) and _USE.search(sentence)):
            continue
        codes = set(re.findall(r"\(([A-Z0-9]{2})\)", sentence))
        low = sentence.lower()
        for name in _airline_names():
            first = name.split()[0]
            if name.lower() in low or (len(first) >= 5 and re.search(r"\b%s\b" % re.escape(first.lower()), low)):
                out.add(name)
        if codes:
            for o in getattr(portal, "LANES", {}).values():
                for a in o:
                    if isinstance(a, dict) and a.get("code") in codes and a.get("name"):
                        out.add(a["name"])
    return out


_ONLY = re.compile(r"\b(?:only (?:use|with|via|book|fly|offer|quote)|exclusively|must (?:be|fly with|go with)|contracted carrier|"
                   r"our (?:contract|framework|preferred) (?:carrier|airline)|nur (?:mit|über)|ausschlie(?:ß|ss)lich|"
                   r"solo con|uniquement (?:avec|par))\b", re.I)


def required_airlines(tid):
    """'Please only use Meridian Freightways, it is our contracted carrier': the mirror of an excluded airline.
    Read from the request thread only (a carrier wish is per shipment)."""
    s = db.session(tid) or {}
    sender = (s.get("customer") or "").lower()
    text = "\n".join("%s\n%s" % (r["subject"] or "", re.split(r"\n\s*(?:>|On .+wrote:|Am .+schrieb)", r["body"] or "")[0])
                     for r in db.con().execute("SELECT subject, body FROM mails WHERE thread_id=? AND sender=?", (tid, sender)))
    out = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        if not _ONLY.search(sentence) or _NO.search(sentence):
            continue
        low = sentence.lower()
        for name in _airline_names():
            first = name.split()[0]
            if name.lower() in low or (len(first) >= 5 and re.search(r"\b%s\b" % re.escape(first.lower()), low)):
                out.add(name)
    return out


def keep_required(tid, options):
    """Only the airline(s) the customer asked for. No price from them -> [] (a human asks that airline)."""
    want = {n.lower() for n in required_airlines(tid)}
    if not want:
        return options
    keep = [x for x in options if str(x.get("airline") or "").lower() in want]
    db.event("airline_required", tid, required=sorted(want), kept=len(keep), dropped=len(options) - len(keep))
    return keep


def drop_excluded(tid, options):
    """Never quote an airline the customer excluded. None left -> [] (finalize hands it to a human)."""
    banned = {n.lower() for n in excluded_airlines(tid)}
    if not banned:
        return options
    keep = [x for x in options if str(x.get("airline") or "").lower() not in banned]
    db.event("airline_excluded", tid, excluded=sorted(banned), dropped=[x.get("airline") for x in options if x not in keep],
             kept=len(keep))
    return keep


def drop_price_outliers(tid, options):
    """Options of ONE request, same shipment (the trucker leg is in all of them): drop the absurd ones before we pick.
    Needs >= 3 priced options, never drops below 2, never stops a quote. Logged as price_outlier_dropped."""
    def eur(x):
        try:
            return Decimal(str(x["total_eur"]))
        except Exception:
            return None
    priced = [(x, eur(x)) for x in options if eur(x) is not None and eur(x) > 0]
    if len(priced) < 3:
        return options
    vals = sorted(v for _, v in priced)
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    keep = [x for x, v in priced if OUTLIER_LOW * median <= v <= OUTLIER_HIGH * median]
    if len(keep) == len(priced) or len(keep) < 2:
        return options
    db.event("price_outlier_dropped", tid, median=str(median), kept=len(keep),
             dropped=[[x.get("airline"), str(v), x.get("source")] for x, v in priced if x not in keep])
    return keep


def by_deadline(tid, options, fields):
    """Keep the options that land in time. None lands in time -> all of them, and the fastest is taken."""
    first = db.con().execute("SELECT body FROM mails WHERE id=?", (tid,)).fetchone()
    limit = max_transit_days(first[0] if first else "")
    if limit is None:
        return options, False
    ok = [x for x in options if _days(x) is not None and _days(x) <= limit]
    db.event("deadline", tid, max_transit_days=limit, in_time=len(ok), options=len(options))
    return (ok, False) if ok else (options, True)


REVISED = {"en": "Thanks for the updated details. This offer replaces my earlier one%s.",
           "de": "Danke für die aktualisierten Angaben. Dieses Angebot ersetzt mein vorheriges%s.",
           "fr": "Merci pour les nouvelles informations. Cette offre remplace la précédente%s.",
           "it": "Grazie per i dati aggiornati. Questa offerta sostituisce la precedente%s.",
           "es": "Gracias por los datos actualizados. Esta oferta sustituye a la anterior%s."}


def revised_note(body, fields, lang):
    """One line after the greeting on a re-quote, so the customer sees which offer counts."""
    old = (fields.get("revised") or {}).get("total")
    line = REVISED.get(lang, REVISED["en"]) % ((" (%s EUR)" % old) if old else "")
    head, sep, rest = body.partition("\n\n")
    return head + "\n\n" + line + "\n\n" + rest if sep else line + "\n\n" + body


def finalize(tid):
    """Pick the best option and send the one quote. Called right away, or when the bid wait is over."""
    s = db.session(tid)
    fields, options = json.loads(s["fields"]), json.loads(s["options"] or "[]")
    options = bids.final_options(tid, options)               # add bids, add trucker leg
    if not options:
        return needs_human(tid, None, "no price found for this lane")
    options = drop_excluded(tid, options)                    # "please do not offer Zephyr (ZS)": never quote it
    if not options:
        return needs_human(tid, None, "customer excluded every airline we have a price from")
    options = keep_required(tid, options)                    # "please only use Meridian": only that airline
    if not options:
        return needs_human(tid, None, "customer wants only %s, we have no price from them: ask that airline" %
                           ", ".join(sorted(required_airlines(tid))))
    options = drop_price_outliers(tid, options)              # a misread bid (per-kg as total, x1000) never wins
    options, too_late = by_deadline(tid, options, fields)    # "must arrive by <date>": drop flights that land late
    if fields.get("prefer") == "fastest" or too_late:
        best = min(options, key=lambda x: (x["transit_days"], Decimal(x["total_eur"])))
    else:
        best = min(options, key=lambda x: Decimal(x["total_eur"]))
    best = quote_in_eur(best)
    asked_mail = db.con().execute("SELECT body FROM mails WHERE id=?", (tid,)).fetchone()
    ins = insurance.wanted(asked_mail[0] if asked_mail else "")   # "include cargo insurance in the all-in price: value, 110 %, 0.40 %"
    if ins:
        best = insurance.add(best, ins)
        db.event("insurance", tid, **ins)
    cus = customs.wanted(asked_mail[0] if asked_mail else "")     # "include customs clearance in the all-in price: 45 EUR"
    if cus and customs.add(best, cus) is not best:
        best = customs.add(best, cus)
        db.event("customs", tid, **cus)
    else:
        cus = None
    if fields.get("dg") and dg.mode() == "human":
        return needs_human(tid, None, "dangerous goods: " + dg.describe(fields["dg"]))
    if not db.claim_for_sending(tid):                        # someone already quoted this thread
        return db.event("quote_skipped_already_sent", tid)

    body, why = llm.final_reply(s["reply_template"], best, fields, s["customer"], tid)   # llm/: filled + quality gate
    best, body, _ = dg.apply(best, fields, body)            # DG paragraph (and surcharge if DG_MODE=surcharge)
    body = dg.note(fields, body)                             # "priced on your packing list: 1729 kg, not 1210 kg"
    if fields.get("recall_note"):                            # totals we worked out from an earlier request: say them
        body = llm._add_expert_note(body, fields["recall_note"], str(best["total"]))
    if ins:                                                  # say what is in the price, before polish adds "not included"
        body = llm._add_expert_note(body, insurance.sentence(ins, llm.reply_lang(fields)), str(best["total"]))
    if cus:
        body = llm._add_expert_note(body, customs.sentence(cus, llm.reply_lang(fields)), str(best["total"]))
    try:                                                     # last human touch (Riky): signed name, answer their asks
        first = db.con().execute("SELECT body FROM mails WHERE id=?", (tid,)).fetchone()
        body, touched = humanize.polish(body, fields, best, first[0] if first else "")
        if touched:
            db.event("humanize", tid, changes=touched)
    except Exception as e:
        db.event("humanize_error", tid, error=str(e)[:200])
    if fields.get("revised"):                                # the customer changed the shipment after our first quote
        body = revised_note(body, fields, llm.reply_lang(fields))
    if why:                                                  # the model's text failed the gate: our own template went out
        db.event("reply_gate", tid, reasons=why, language=fields.get("language"))
    subject = s["subject"] if s["subject"].lower().startswith("re:") else "Re: " + s["subject"]
    files = []
    try:                                                     # the offer as a file (5U 23:36: "attach your offer as a PDF")
        asked_for = db.con().execute("SELECT body FROM mails WHERE id=?", (tid,)).fetchone()
        files, asked = offer_file.build(tid, s, best, fields, body, asked_for[0] if asked_for else "")
        body = offer_file.say_so(body, asked, llm.reply_lang(fields))
        db.event("offer_file", tid, files=[f["filename"] for f in files], asked=sorted(asked))
    except Exception as e:                                   # never lose a quote over the file
        db.event("offer_file_error", tid, error=str(e)[:200])
    ok = send_quote(tid, s["customer"], subject, body, files)   # retried when the send failed, never after a success
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
    "bounce": bids.on_bounce,                            # mailer-daemon: that carrier never got our bid mail
    "tariff": tariff_mail.handle,                        # Patrick: airline tariff mail -> live price update
}


def process(mail):
    if not db.save_mail(mail):
        return                                               # seen before (restart): never handle twice
    customers = [x[0] for x in db.con().execute("SELECT DISTINCT customer FROM sessions WHERE status != 'ignored'").fetchall()]
    r = route(mail, config.OUR_ADDRESS, customers)
    db.set_route(mail["id"], r)
    db.event("mail_in", mail["thread_id"], mail["id"], route=r, sender=mail["sender"], subject=mail["subject"])
    if r == "spam" and lookalike(mail["sender"], customers):  # say why, for the person who looks at the log
        db.event("lookalike_sender", mail["thread_id"], mail["id"], sender=mail["sender"],
                 looks_like=lookalike(mail["sender"], customers), replied=False)
    elif r == "spam" and ADDRESS_SWITCH.search(mail["subject"] + "\n" + mail["body"]) and mail["sender"] not in customers:
        db.event("address_switch_request", mail["thread_id"], mail["id"], sender=mail["sender"], replied=False)
    if r in ("rfq", "follow_up", "carrier_bid", "ratedesk") and mail["attachments"]:
        attachments.read(mail)                               # every file -> text, once (core/attachments.py)
        if r == "rfq":
            attachments.inline_request(mail)                 # 5U 22:17: the request is ONLY in the attached file
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
    next_poll = 0.0
    while True:
        now = time.time()
        if now >= next_poll:                                 # 5U allows one poll per 5 s per team key
            next_poll = now + config.POLL_S
            try:
                mails, nxt = mailbox.poll(since)
                for m in mails:
                    process(m)
                    since = max(since, m["id"])
                    db.set_state("since_id", since)
                if nxt > since:
                    since = nxt
                    db.set_state("since_id", since)
            except mailbox.RateLimited as e:                 # too early: wait what 5U asks, never hammer
                next_poll = time.time() + max(e.retry_after, config.POLL_S)
                db.event("poll_rate_limited", retry_after=e.retry_after)
            except Exception as e:                           # network hiccup: log and keep going
                db.event("loop_error", error=str(e))
        try:
            tick()                                           # bid waits and quotes run every TICK_S, not per poll
            actions.tick()                                   # human replies from the UI (actions/queue.py)
            db.set_state("heartbeat", time.time())           # the UI can show "clerk alive" from this
        except Exception as e:
            db.event("loop_error", error=str(e))
        if safety.restart_wanted():                          # asked by `python3 -m core.restart`, between two turns
            db.event("restart", commit=commit)
            sys.exit(0)                                      # core/supervise.py starts the new code
        time.sleep(config.TICK_S)


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
