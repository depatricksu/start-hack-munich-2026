"""Price a shipment from the parsed tariff sheets (no LLM, no network).

    from pricing.price import options
    options("FRA", "LAX", weight_kg=120, volume_cbm=0.9)   # cheapest first

chargeable = max(weight_kg, volume_cbm * 167)
freight    = max(min_charge, rate(bracket of chargeable) * chargeable)
total      = freight + (fuel + security) * chargeable     (minimum applies before surcharges)
"""
import json, os
from decimal import Decimal, ROUND_HALF_UP

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tariffs.json")
_TARIFFS = json.load(open(_PATH))
VOL_FACTOR = Decimal("167")


def _d(x):
    return Decimal(str(x))


def chargeable_kg(weight_kg, volume_cbm=0):
    return max(_d(weight_kg), _d(volume_cbm) * VOL_FACTOR)


def price_lane(rec, weight_kg, volume_cbm=0):
    cw = chargeable_kg(weight_kg, volume_cbm)
    idx = max(i for i, b in enumerate(rec["breaks_kg"]) if cw >= b)
    rate = _d(rec["rates_per_kg"][idx])
    freight = max(_d(rec["min_charge"]), rate * cw)
    total = freight + (_d(rec["fuel_per_kg"]) + _d(rec["security_per_kg"])) * cw
    return {
        "airline": rec["airline"], "origin": rec["origin"], "destination": rec["destination"],
        "transit_days": rec["transit_days"], "currency": rec["currency"],
        "chargeable_kg": str(cw), "rate_per_kg": str(rate), "min_applied": rate * cw < _d(rec["min_charge"]),
        "total": str(total.quantize(Decimal("0.01"), ROUND_HALF_UP)), "source": "sheet",
    }


def options(origin, destination, weight_kg, volume_cbm=0):
    out = [price_lane(r, weight_kg, volume_cbm) for r in _TARIFFS
           if r["origin"] == origin and r["destination"] == destination]
    return sorted(out, key=lambda o: Decimal(o["total"]))


def cheapest(origin, destination, weight_kg, volume_cbm=0):
    o = options(origin, destination, weight_kg, volume_cbm)
    return o[0] if o else None


def fastest(origin, destination, weight_kg, volume_cbm=0):
    o = options(origin, destination, weight_kg, volume_cbm)
    return min(o, key=lambda x: (x["transit_days"], Decimal(x["total"]))) if o else None


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    for o in options(a[0], a[1], a[2], a[3] if len(a) > 3 else 0):
        print(o)
