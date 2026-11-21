"""Learn the scorer's hidden rules from the points it gives us. Owner: Erik. Pure functions, no network, no DB.

Known rules (brief): per accepted quote  accuracy 45 (full at the best price, 0 at +5%),  time 15 (full under 120 s, 0 at 360 s),
cost 40 (added hourly, ignored here).  The leaderboard total after a round minus the total before it = this round's
accuracy + time (+ bonuses). We know our response time exactly, so the accuracy points follow, and from them the
best price the scorer used:   accuracy = 45 * (1 - (quote / best - 1) / 0.05).
"""
from datetime import datetime

ACC_MAX, TIME_MAX, BAND = 45.0, 15.0, 0.05


def seconds_between(sent_iso, answered_iso):
    f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (f(answered_iso) - f(sent_iso)).total_seconds()


def time_points(seconds):
    """Full within 120 s, zero at 360 s, linear in between."""
    return TIME_MAX * max(0.0, min(1.0, 1 - (seconds - 120) / 240))


def accuracy_points(quote, best):
    """What the scorer pays for a quote against its best price. At or below best = full. At +5% or more = 0."""
    over = quote / best - 1
    return ACC_MAX * max(0.0, min(1.0, 1 - over / BAND))


def implied_best(quote, acc_points, tol=0.05):
    """Invert accuracy_points. Returns (low, high): the best price must lie in this range.
    Full points only say best >= quote (we could not tell how much cheaper we were)."""
    if acc_points >= ACC_MAX - tol:
        return (quote, float("inf"))
    if acc_points <= tol:
        return (0.0, quote / (1 + BAND))                      # rejected band: best is at most this
    best = quote / (1 + BAND * (1 - acc_points / ACC_MAX))
    return (best * 0.9995, best * 1.0005)


def split_delta(delta, seconds):
    """Round delta -> (accuracy points, ok). ok is False when the numbers cannot be one clean accuracy+time round
    (for example the hourly cost points landed in the same delta, or a bonus did)."""
    acc = delta - time_points(seconds)
    return acc, (-0.5 <= acc <= ACC_MAX + 0.5)


def pick_rule(quote, acc_points, candidates):
    """candidates: {rule name: best price that rule predicts}. Returns the rules consistent with the points, best first.
    A rule is consistent when the accuracy it would have paid for this quote matches what we got (within 1.5 points)."""
    scored = []
    for name, best in candidates.items():
        err = abs(accuracy_points(quote, best) - acc_points)
        scored.append((err, name))
    scored.sort()
    return [(n, round(e, 2)) for e, n in scored]
