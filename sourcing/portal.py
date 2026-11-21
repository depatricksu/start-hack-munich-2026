"""Rate portal API: prices for the 15 portal airlines. Capped at about 10 calls per minute.

    from sourcing.portal import options
    options("FRA", "LAX", 120, 0.9)   # same shape as pricing.price.options, plus rate_id for booking
"""
import json, os
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from core import config, mailbox

import time

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "portal-lanes.json")
LANES = {(l["origin"], l["destination"]): l["airlines"] for l in json.load(open(_PATH))["lanes"]}

# 5U changes the setup about once an hour without notice. Lanes and weight breaks are free to read (not rate
# limited), so we re-read them every few minutes instead of trusting this morning's copy, and log every difference.
REFRESH_S = float(os.environ.get("PORTAL_REFRESH_S", "180"))
BREAK_DEPTH = int(os.environ.get("PORTAL_BREAK_DEPTH", "4"))          # how many higher brackets we may try
BREAK_TOLERANCE = float(os.environ.get("PORTAL_BREAK_TOLERANCE", "0.10"))  # keep climbing while within 10 %
# A 429 with a short Retry-After is waited out once and the dropped reads are asked again; a long one (the
# limit is a fixed one-minute window) is not: we quote with what we have. RETRY_BUDGET_S caps the extra time
# one options() call may spend on waits and second tries (time score: full under 120 s).
RETRY_MAX_WAIT_S = float(os.environ.get("PORTAL_RETRY_MAX_WAIT_S", "5"))
RETRY_BUDGET_S = float(os.environ.get("PORTAL_RETRY_BUDGET_S", "10"))
_clock, _sleep = time.monotonic, time.sleep              # tests swap these for a fake clock
_lanes_at = 0.0
_BREAKS = {}                     # airline code -> (read_at, weight breaks)


class _Miss(str):
    """A rate read we did not get. Equal to its kind as a string: 'limit' (429) or 'error' (5xx, timeout,
    connection error, payload we could not read). Carries Retry-After and the reason for the log."""
    retry_after, detail = 0.0, ""


def _miss(kind, detail="", retry_after=0.0):
    m = _Miss(kind)
    m.detail, m.retry_after = str(detail)[:200], retry_after
    return m


def _log(kind, **data):
    try:
        from core import db
        db.event(kind, **data)
    except Exception:
        pass


def refresh_lanes(force=False):
    """Re-read /v1/portal/ports at most every REFRESH_S; swap LANES in place and log what changed."""
    global _lanes_at
    if not config.API_KEY or (not force and time.time() - _lanes_at < REFRESH_S):
        return
    _lanes_at = time.time()
    status, r = mailbox.api("GET", "/v1/portal/ports")
    if status != 200 or not isinstance(r, dict) or not r.get("lanes"):
        return
    new = {(l["origin"], l["destination"]): l["airlines"] for l in r["lanes"]}
    codes = lambda d: {k: sorted(a["code"] for a in v) for k, v in d.items()}
    old_c, new_c = codes(LANES), codes(new)
    if old_c != new_c:
        added = sorted("%s-%s" % k for k in set(new_c) - set(old_c))
        removed = sorted("%s-%s" % k for k in set(old_c) - set(new_c))
        changed = sorted("%s-%s %s->%s" % (k[0], k[1], old_c[k], new_c[k]) for k in set(old_c) & set(new_c)
                         if old_c[k] != new_c[k])
        _log("setup_change", what="portal_lanes", added=added, removed=removed, changed=changed)
    LANES.clear()
    LANES.update(new)


def _breaks(code):
    hit = _BREAKS.get(code)
    if hit and time.time() - hit[0] < REFRESH_S:
        return hit[1]
    try:
        status, r = mailbox.api("GET", "/v1/portal/brackets", params={"airline": code})
        breaks = [float(b) for b in (r.get("breaks_kg") or [])] if status == 200 else (hit[1] if hit else [])
    except Exception as e:                           # one failed read: this airline gets no ladder, the rest go on
        _log("portal_read_error", what="brackets", airline=code, error="%s: %s" % (type(e).__name__, e))
        return hit[1] if hit else []                 # not cached, so the next quote asks again
    if hit and breaks != hit[1]:
        _log("setup_change", what="weight_breaks", airline=code, before=hit[1], after=breaks)
    _BREAKS[code] = (time.time(), breaks)
    return breaks


def _rate(origin, destination, code, weight_kg, volume_cbm):
    """One rate read -> option dict, 'limit' on 429, 'error' on a transient failure, or None (not priced here).
    Never raises: one broken read must not cost the other airlines. It runs in worker threads, so it does not
    log (the DB connection belongs to the main thread); options() logs what a _Miss carries."""
    try:
        status, r = mailbox.api("GET", "/v1/portal/rates", params={
            "origin": origin, "destination": destination, "airline": code,
            "weight_kg": weight_kg, "volume_cbm": volume_cbm})
        if status == 429:            # out of budget this minute
            return _miss("limit", r, float(r.get("retry_after", 5)) if isinstance(r, dict) else 5.0)
        if status in (500, 502, 504):                    # 503 is not transient here: "get this rate elsewhere"
            return _miss("error", "HTTP %s: %s" % (status, r))
        if status != 200:
            return None
        return _option(r, origin, destination, code, weight_kg)
    except Exception as e:           # timeout, connection reset, a payload without the documented fields
        return _miss("error", "%s: %s" % (type(e).__name__, e))


def _option(r, origin, destination, code, weight_kg):
    stated = r.get("fx_eur_per_usd")                 # EUR per 1 unit of the price's currency, only for non-EUR prices
    fx_missing = r["currency"] != "EUR" and not stated
    if fx_missing:                                   # we cannot turn it into EUR: never relabel the number as EUR
        _log("portal_no_fx", airline=r["airline"], currency=r["currency"], total=r["total"])
    fx = Decimal(stated or "1")
    opt = {"airline": r["airline"], "airline_code": r.get("airline_code") or code, "origin": origin,
           "destination": destination, "transit_days": r["transit_days"], "currency": r["currency"],
           "total": r["total"], "total_eur": str((Decimal(r["total"]) * fx).quantize(Decimal("0.01"))),
           "chargeable_kg": r.get("chargeable_weight_kg"), "billed_kg": str(weight_kg), "source": "portal",
           "rate_id": r["rate_id"], "valid_until": r.get("valid_until"), "fx": stated}
    if fx_missing:
        opt["fx_missing"] = True                     # ranked by its raw number, quoted in its own currency
    return opt


def options(origin, destination, weight_kg, volume_cbm=0, weight_break=None):
    """Portal options for every portal airline on the lane.

    Weight break (WEIGHT_BREAK=1, same flag as the sheets): also price each airline at the start of the next
    weight bracket. A heavier bracket has a lower rate per kg, so e.g. 676 kg billed as 1000 kg can be cheaper.
    Round 1 and 2 of the live game: the full-score teams booked at the next break (676 -> 1000, 1233 -> 2000 kg).
    The extra reads come last, so the rate limit (429) only ever costs the extra ones.
    """
    from pricing import price as sheets
    use_break = sheets.WEIGHT_BREAK if weight_break is None else weight_break
    out = []
    if not config.API_KEY:
        return out
    try:
        refresh_lanes()
    except Exception as e:                              # never let a refresh break a quote
        _log("portal_refresh_error", error=str(e))
    airlines = LANES.get((origin, destination), [])
    # Base bracket: one read per airline, fired in parallel (independent GETs) so the quote is faster.
    lane, deadline = "%s-%s" % (origin, destination), _clock() + RETRY_BUDGET_S

    def read_all(todo):
        if not todo:
            return []
        with ThreadPoolExecutor(max_workers=min(len(todo), 8)) as ex:
            return list(ex.map(lambda a: _rate(origin, destination, a["code"], weight_kg, volume_cbm), todo))

    rated = read_all(airlines)
    if "limit" in rated:                                  # hit the per-minute rate limit: keep hits, skip the weight-break
        use_break = False
    missed = [i for i, r in enumerate(rated) if isinstance(r, _Miss)]
    if missed:                                            # 429 or a transient error: one more try, if it is cheap
        code = lambda i: airlines[i]["code"]
        limited = [code(i) for i in missed if rated[i] == "limit"]
        errors = {code(i): rated[i].detail for i in missed if rated[i] != "limit"}
        wait = max(rated[i].retry_after for i in missed)
        retried = wait <= RETRY_MAX_WAIT_S and _clock() + wait <= deadline
        if retried:
            if wait > 0:
                _sleep(wait)
            for i, r in zip(missed, read_all([airlines[i] for i in missed])):
                rated[i] = r
            if "limit" in rated:
                use_break = False
        lost = [code(i) for i in missed if isinstance(rated[i], _Miss)]
        if limited:
            _log("portal_limit", lane=lane, phase="base", airlines=limited, retry_after=wait, retried=retried, lost=lost)
        if errors:
            _log("portal_read_error", lane=lane, phase="base", errors=errors, retried=retried, lost=lost)
    out.extend(o for o in rated if isinstance(o, dict))
    if use_break:
        # Round 9: nobody got full price points, our next-bracket price was > 5 % above the best -> look deeper.
        # Pass 1 = the next bracket for every airline. Then, per airline, keep climbing one bracket at a time while
        # the last climb was cheaper (or within BREAK_TOLERANCE of the best so far), up to BREAK_DEPTH brackets.
        # Cheapest-first order, so the rate limit (429) only ever drops the least promising reads.
        chargeable = max(float(weight_kg), float(volume_cbm or 0) * 167)
        eur = lambda o: float(o["total_eur"])
        best = {}                                        # airline code -> best total_eur so far
        for o in out:
            c = o.get("airline_code")
            best[c] = min(best.get(c, 1e18), eur(o))
        ladders = {a["code"]: [b for b in _breaks(a["code"]) if b > chargeable][:BREAK_DEPTH] for a in airlines}
        level = {c: 0 for c in ladders}
        live = [c for c in ladders if ladders[c]]
        while live:
            live.sort(key=lambda c: best.get(c, 1e18))  # most promising airline first
            nxt_live = []
            for c in live:
                o = _rate(origin, destination, c, ladders[c][level[c]], volume_cbm)
                if o == "limit":                         # short Retry-After and budget left: wait once, ask again
                    wait = o.retry_after
                    retried = wait <= RETRY_MAX_WAIT_S and _clock() + wait <= deadline
                    if retried:
                        _sleep(wait)
                        o = _rate(origin, destination, c, ladders[c][level[c]], volume_cbm)
                    _log("portal_limit", lane=lane, phase="weight_break", airlines=[c], billed_kg=ladders[c][level[c]],
                         retry_after=wait, retried=retried, lost=[c] if o == "limit" else [])
                    if o == "limit":
                        return out
                level[c] += 1
                if isinstance(o, _Miss):                 # this airline's ladder ends here, the others go on
                    _log("portal_read_error", lane=lane, phase="weight_break", errors={c: o.detail}, retried=False, lost=[c])
                if not isinstance(o, dict):
                    continue
                o["weight_break"] = True
                out.append(o)
                prev = best.get(c, 1e18)
                best[c] = min(prev, eur(o))
                if level[c] < len(ladders[c]) and eur(o) <= prev * (1 + BREAK_TOLERANCE):
                    nxt_live.append(c)                   # still getting cheaper (or close): try the next bracket
            live = nxt_live
    return out
