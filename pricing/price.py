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
# Airlines mail new tariffs during the night: pricing/tariff_mail.py stores them here (git-ignored) and
# swaps them in live. One entry per airline replaces ALL of that airline's start-kit lanes.
OVERRIDES = os.environ.get("TARIFF_OVERRIDES", os.path.join(os.path.dirname(_PATH), "..", "data", "tariff_overrides.json"))
VOL_FACTOR = Decimal("167")


def _overrides():
    if not os.path.exists(OVERRIDES):
        return {}
    with open(OVERRIDES) as f:
        return json.load(f)


def _load():
    with open(_PATH) as f:
        base = json.load(f)
    over = _overrides()
    keep = [r for r in base if r["airline"].lower() not in {a.lower() for a in over}]
    return keep + [r for recs in over.values() for r in recs]


_TARIFFS = _load()


def replace_airline(airline, records):
    """Swap one airline's lanes now (no restart) and persist the override."""
    over = _overrides()
    over = {a: v for a, v in over.items() if a.lower() != airline.lower()}
    over[airline] = records
    os.makedirs(os.path.dirname(OVERRIDES), exist_ok=True)
    tmp = OVERRIDES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(over, f, indent=1)
    os.replace(tmp, OVERRIDES)
    _TARIFFS[:] = _load()                    # in place: every importer sees the new prices


def lanes_of(airline):
    return [r for r in _TARIFFS if r["airline"].lower() == airline.lower()]


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
