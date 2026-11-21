"""Rate portal API: prices for the 15 portal airlines. Capped at about 10 calls per minute.

    from sourcing.portal import options
    options("FRA", "LAX", 120, 0.9)   # same shape as pricing.price.options, plus rate_id for booking
"""
import json, os
from decimal import Decimal
from core import config, mailbox

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "portal-lanes.json")
LANES = {(l["origin"], l["destination"]): l["airlines"] for l in json.load(open(_PATH))["lanes"]}


def options(origin, destination, weight_kg, volume_cbm=0):
    out = []
    if not config.API_KEY:
        return out
    for a in LANES.get((origin, destination), []):
        status, r = mailbox.api("GET", "/v1/portal/rates", params={
            "origin": origin, "destination": destination, "airline": a["code"],
            "weight_kg": weight_kg, "volume_cbm": volume_cbm})
        if status == 429:        # out of budget this minute: quote with what we have
            break
        if status != 200:
            continue
        fx = Decimal(r.get("fx_eur_per_usd") or "1")
        out.append({"airline": r["airline"], "origin": origin, "destination": destination,
                    "transit_days": r["transit_days"], "currency": r["currency"], "total": r["total"],
                    "total_eur": str((Decimal(r["total"]) * fx).quantize(Decimal("0.01"))),
                    "chargeable_kg": r.get("chargeable_weight_kg"), "source": "portal",
                    "rate_id": r["rate_id"], "valid_until": r.get("valid_until")})
    return out
