"""Rate portal API: prices for the 15 portal airlines. Capped at about 10 calls per minute.

    from sourcing.portal import options
    options("FRA", "LAX", 120, 0.9)   # same shape as pricing.price.options, plus rate_id for booking
"""
import json, os
from decimal import Decimal
from core import config, mailbox

import time

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "portal-lanes.json")
LANES = {(l["origin"], l["destination"]): l["airlines"] for l in json.load(open(_PATH))["lanes"]}

# 5U changes the setup about once an hour without notice. Lanes and weight breaks are free to read (not rate
# limited), so we re-read them every few minutes instead of trusting this morning's copy, and log every difference.
REFRESH_S = float(os.environ.get("PORTAL_REFRESH_S", "180"))
BREAK_DEPTH = int(os.environ.get("PORTAL_BREAK_DEPTH", "4"))          # how many higher brackets we may try
BREAK_TOLERANCE = float(os.environ.get("PORTAL_BREAK_TOLERANCE", "0.10"))  # keep climbing while within 10 %
_lanes_at = 0.0
_BREAKS = {}                     # airline code -> (read_at, weight breaks)


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
    status, r = mailbox.api("GET", "/v1/portal/brackets", params={"airline": code})
    breaks = [float(b) for b in (r.get("breaks_kg") or [])] if status == 200 else (hit[1] if hit else [])
    if hit and breaks != hit[1]:
        _log("setup_change", what="weight_breaks", airline=code, before=hit[1], after=breaks)
    _BREAKS[code] = (time.time(), breaks)
    return breaks


def _rate(origin, destination, code, weight_kg, volume_cbm):
    """One rate read -> option dict, or 'limit' on 429, or None."""
    status, r = mailbox.api("GET", "/v1/portal/rates", params={
        "origin": origin, "destination": destination, "airline": code,
        "weight_kg": weight_kg, "volume_cbm": volume_cbm})
    if status == 429:            # out of budget this minute: quote with what we have
        return "limit"
    if status != 200:
        return None
    fx = Decimal(r.get("fx_eur_per_usd") or "1")
    return {"airline": r["airline"], "airline_code": r.get("airline_code") or code, "origin": origin,
            "destination": destination, "transit_days": r["transit_days"], "currency": r["currency"],
            "total": r["total"], "total_eur": str((Decimal(r["total"]) * fx).quantize(Decimal("0.01"))),
            "chargeable_kg": r.get("chargeable_weight_kg"), "billed_kg": str(weight_kg), "source": "portal",
            "rate_id": r["rate_id"], "valid_until": r.get("valid_until")}


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
    for a in airlines:
        o = _rate(origin, destination, a["code"], weight_kg, volume_cbm)
        if o == "limit":
            return out
        if o:
            out.append(o)
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
                if o == "limit":
                    return out
                level[c] += 1
                if not o:
                    continue
                o["weight_break"] = True
                out.append(o)
                prev = best.get(c, 1e18)
                best[c] = min(prev, eur(o))
                if level[c] < len(ladders[c]) and eur(o) <= prev * (1 + BREAK_TOLERANCE):
                    nxt_live.append(c)                   # still getting cheaper (or close): try the next bracket
            live = nxt_live
    return out
