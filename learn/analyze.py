"""Learn from the scorer, round after round. Owner: Erik. Pure functions (no network, no DB): easy to test.

Every change of our leaderboard total is one equation. We know the time points exactly, the tracking bonus is +10, and
the accuracy points tell us the best price the scorer used. Candidate pricing rules are scored by how well their
predicted best price explains the accuracy points; their odds are updated with a Gaussian likelihood (Bayes).
"""
import json, math
from decimal import Decimal

from . import scorer as S

RULES = ("what_we_quoted", "without_trucker", "cheapest_any", "fastest_any")


def classify_change(delta, answered_requests, tracking_answered):
    """One change of our total -> what it probably is.
    answered_requests: [(round_no, seconds_to_answer)] whose verdict just changed from open.
    tracking_answered: True if we sent a matched tracking answer since the last change."""
    if delta <= 0.01:
        return {"kind": "none"}
    if not answered_requests:
        if abs(delta - 10) <= 0.5:
            return {"kind": "tracking_bonus", "tracking": 10.0}
        if delta > 60:
            return {"kind": "cost_points_or_mixed", "delta": delta}
        return {"kind": "unknown", "delta": delta}
    if len(answered_requests) > 1:
        return {"kind": "mixed", "rounds": [r for r, _ in answered_requests], "delta": delta}
    rnd, secs = answered_requests[0]
    t = S.time_points(secs)
    options = []
    for tr in ((10.0, 0.0) if tracking_answered else (0.0, 10.0)):   # likelier variant first
        acc = delta - t - tr
        if -0.5 <= acc <= S.ACC_MAX + 0.5:
            options.append({"kind": "round", "round": rnd, "time": round(t, 2), "tracking": tr, "accuracy": round(max(0.0, min(acc, S.ACC_MAX)), 2)})
    if not options:
        return {"kind": "unclean_round", "round": rnd, "delta": delta, "time": round(t, 2)}
    best = options[0]
    best["alt"] = options[1] if len(options) > 1 else None
    return best


def _dec(x):
    return Decimal(str(x))


def predicted_bests(session):
    """What each rule says the scorer's best price is, from the options and the choice we stored for this request.
    session: dict with 'chosen' (dict or None), 'options' (list), 'fields' (dict)."""
    ch, opts, f = session.get("chosen"), session.get("options") or [], session.get("fields") or {}
    out = {}
    if ch:
        out["what_we_quoted"] = float(_dec(ch["total_eur"] if ch.get("total_eur") else ch["total"]))
    flights = [float(_dec(o["flight_total"])) for o in opts if o.get("flight_total") and o.get("flight_currency") == "EUR"]
    if flights:
        out["without_trucker"] = min(flights)             # the scorer ignores the trucker leg (we would be above it)
    if opts:
        out["cheapest_any"] = min(float(_dec(o["total_eur"])) for o in opts)
        fastest = min(o["transit_days"] for o in opts)
        out["fastest_any"] = min(float(_dec(o["total_eur"])) for o in opts if o["transit_days"] == fastest)
    return out


def explain(quote, accuracy, session):
    """-> {rule: accuracy-points error} and the implied best price range."""
    lo, hi = S.implied_best(quote, accuracy)
    errs = {r: round(abs(S.accuracy_points(quote, b) - accuracy), 2) for r, b in predicted_bests(session).items()}
    return {"implied_best": [round(lo, 2), None if hi == float("inf") else round(hi, 2)], "rule_errors": errs}


def update_odds(odds, rule_errors, sigma=2.0):
    """Bayes: odds[rule] *= exp(-err^2 / (2 sigma^2)). A rule that predicts nothing for this round keeps its odds."""
    new = {r: odds.get(r, 1.0) * (math.exp(-(rule_errors[r] ** 2) / (2 * sigma ** 2)) if r in rule_errors else 1.0) for r in RULES}
    z = sum(new.values()) or 1.0
    return {r: round(v / z, 4) for r, v in new.items()}


def verdict(rule_errors, accuracy=None, tol=1.5):
    """Plain words for the report."""
    if accuracy is not None and accuracy >= S.ACC_MAX - 0.5:
        return "full points: our quote was at or below the scorer's best"
    if not rule_errors:
        return "no candidate rule could be computed"
    good = [r for r, e in rule_errors.items() if e <= tol]
    if good:
        return "explained by: " + ", ".join(sorted(good))
    return "NOT explained by any candidate rule (the scorer's best came from something we do not model)"
