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
    cols = {r["name"] for r in c.execute("PRAGMA table_info(bids)")}
    if "status" not in cols:
        print("bids: none asked yet")
    else:
        n = c.execute("SELECT COUNT(*) FROM bids WHERE status!='send_failed'").fetchone()[0]
        print("bids by role and status:", {"%s/%s" % (r[0], r[1]): r[2] for r in
              c.execute("SELECT role, status, COUNT(*) FROM bids GROUP BY role, status")})
        b = [r[0] for r in c.execute("SELECT replied_at-requested_at FROM bids WHERE replied_at IS NOT NULL AND status!='send_failed'")]
        print("bid answers: %d of %d asked. seconds: median=%s p80=%s p90=%s max=%s" % (len(b), n, pct(b, .5), pct(b, .8), pct(b, .9), pct(b, 1)))
        print("BID_WAIT_S is %s now. Rule of thumb: set it near the p80 bid time, and keep it under ~100." % config.BID_WAIT_S)
        # the experiment: would a bid by mail have beaten what we quoted?
        import json
        better = total = 0
        for s in c.execute("SELECT thread_id, chosen FROM sessions WHERE status='quoted' AND chosen IS NOT NULL"):
            best = c.execute("SELECT MIN(CAST(total_eur AS REAL)) FROM bids WHERE thread_id=? AND role!='trucker' AND status='ok' AND required=0",
                             (s["thread_id"],)).fetchone()[0]
            if best is None:
                continue
            total += 1
            quoted = float(json.loads(s["chosen"]).get("flight_total") or json.loads(s["chosen"])["total_eur"])
            if best < quoted * 0.999:
                better += 1
                print("  thread %s: quoted %.2f EUR, a bid offered %.2f EUR" % (s["thread_id"], quoted, best))
        print("experiment: in %d of %d quoted requests a bid by mail was cheaper than our quote" % (better, total))
    cost = c.execute("SELECT AVG(llm_cost_usd), COUNT(llm_cost_usd) FROM sessions").fetchone()
    print("LLM cost per RFQ (our estimate): avg=%s over %s" % (cost[0], cost[1]))


if __name__ == "__main__":
    main()
