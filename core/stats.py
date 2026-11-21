"""Numbers to calibrate with. Run: python -m core.stats

Shows how fast we quote and how fast carriers answer bids, so we can tune BID_WAIT_S with real data.
"""
from . import config, db


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 1) if xs else None


def main():
    c = db.con()
    print("sessions by status:", dict(c.execute("SELECT status, COUNT(*) FROM sessions GROUP BY status").fetchall()))
    q = [r[0] for r in c.execute("SELECT quoted_at-received_at FROM sessions WHERE status='quoted'")]
    print("seconds to quote: n=%d median=%s p90=%s max=%s (full points under 120)" % (len(q), pct(q, .5), pct(q, .9), pct(q, 1)))
    b = [r[0] for r in c.execute("SELECT replied_at-requested_at FROM bids WHERE replied_at IS NOT NULL")]
    n = c.execute("SELECT COUNT(*) FROM bids").fetchone()[0]
    print("bid answers: %d of %d asked. seconds: median=%s p80=%s p90=%s max=%s" % (len(b), n, pct(b, .5), pct(b, .8), pct(b, .9), pct(b, 1)))
    print("BID_WAIT_S is %s now. Rule of thumb: set it near the p80 bid time, and keep it under ~100." % config.BID_WAIT_S)
    cost = c.execute("SELECT AVG(llm_cost_usd), COUNT(llm_cost_usd) FROM sessions").fetchone()
    print("LLM cost per RFQ (our estimate): avg=%s over %s" % (cost[0], cost[1]))


if __name__ == "__main__":
    main()
