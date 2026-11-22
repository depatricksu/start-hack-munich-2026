"""Rates from the portal's web page, when the rate API is down. For an AUTOMATED source only.

5U, 22 Nov 01:15 to 02:08 and 04:03 to 04:28: the rate API answered 503 "The rate API is unavailable", and the rate
desk and the 15 portal airlines stopped answering mail. The prices existed in one place only: the "Rate portal" page
(https://start-hack.5u.ai/portal/ui, linked on the leaderboard), which puts a check in front of every rate.

RULE (5U, Discord #5u-ai, 22 Nov 04:03): "no human in the loop. The brief says everything runs without a human. That
includes the portal page: solving checks or copying prices by hand isn't allowed." And 04:06: an agent with its own
harness is fine "as long as the agent does it by itself ... If the harness asks a person to solve anything, that's a
human."

What happened here, for the record: rounds 98, 99 and 100 (01:55 to 02:05) and round 123 (04:25) were quoted with a
rate that Erik read on the page by hand and passed in through this module. That is a human in the loop. It was
stopped at 04:35 when the rule was read. Rounds 93 to 97 and 120 to 122 had no such rate.

Now: the clerk only waits for a portal page rate when config.PORTAL_PAGE_SOURCE names an automated source. Such a
source (a browser agent that works the page by itself) asks lookup() or reads the 'portal_down' event for what is
needed, and passes each rate in with add(..., by="<its name>"). Nothing in this module asks a person for anything.
No source configured: the quote goes out at the normal time with the prices we have.

    python3 -m sourcing.portal_page                      which held requests need which rates (for the harness)
    python3 -m sourcing.portal_page 29224 BX 645.60 1 R-CN-Uk_5BeqIhb2d4 --by my-harness   add a rate, quote at once

The portal bills by chargeable weight: the request's real weight and volume are the inputs.
"""
import json
import sys
import time

from core import config, db

URL = "https://start-hack.5u.ai/portal/ui"
SOURCE = "portal page"


def airlines(origin, destination):
    """[{name, code}] of the portal airlines on a lane (the ports list is not rate limited and stays up)."""
    from sourcing import portal
    return [{"name": a.get("name"), "code": a.get("code")} for a in portal.LANES.get((origin, destination), [])]


def known_days(origin, destination):
    """{airline name: transit days} from every portal rate we stored for this lane."""
    out = {}
    for r in db.con().execute("SELECT data FROM events WHERE kind IN ('options','portal_page_price')").fetchall():
        try:
            d = json.loads(r["data"])
        except ValueError:
            continue
        for o in (d.get("options") or ([d["option"]] if d.get("option") else [])):
            if o.get("origin") == origin and o.get("destination") == destination and o.get("source") in ("portal", SOURCE):
                out[o["airline"]] = o.get("transit_days")
    return out


def lookup(tid):
    """What a person has to type on the page for this request."""
    s = db.session(tid)
    f = json.loads(s["fields"] or "{}")
    o, d = f.get("origin"), f.get("destination")
    days = known_days(o, d)
    return {"thread": tid, "origin": o, "destination": d, "weight_kg": f.get("weight_kg_total"),
            "volume_cbm": f.get("volume_cbm_total"), "prefer": f.get("prefer"),
            "airlines": [dict(a, days=days.get(a["name"])) for a in airlines(o, d)]}


def text(look):
    names = ", ".join("%s (%s%s)" % (a["code"], a["name"], ", %s days" % a["days"] if a.get("days") is not None else "")
                      for a in look["airlines"]) or "none on this lane"
    return "RATE API DOWN, waiting for the portal page agent: airline %s | %s to %s | %g kg | %g cbm" % (
        names, look["origin"], look["destination"], look["weight_kg"] or 0, look["volume_cbm"] or 0)


def decides(look, options):
    """False only when we KNOW no portal airline can be the answer: the customer wants the fastest option and every
    portal airline on the lane is known to be slower than a price we already have."""
    if not look["airlines"]:
        return False
    have = [float(o["transit_days"]) for o in options if o.get("transit_days") is not None]
    known = [a["days"] for a in look["airlines"]]
    if (look.get("prefer") or "").lower() == "fastest" and have and all(k is not None for k in known):
        return min(float(k) for k in known) <= min(have)
    return True


def hold(tid, mail_id, options):
    """Called by the clerk when a rate read came back 503: wait for a person's rate instead of quoting blind.
    -> True when the quote is held."""
    look = lookup(tid)
    if not config.PORTAL_PAGE_SOURCE:                        # no automated source: never wait for a person (5U, 04:03)
        db.event("portal_down", tid, mail_id, held=False, why="no automated portal page source: quoting with what we have", lookup=look)
        return False
    if not decides(look, options):
        db.event("portal_down", tid, mail_id, held=False, why="no portal airline can be the answer here", lookup=look)
        return False
    s = db.session(tid)
    until = s["received_at"] + config.PORTAL_DOWN_HOLD_S
    db.update_session(tid, deadline=until, note=text(look))
    db.event("portal_down", tid, mail_id, held=True, hold_s=config.PORTAL_DOWN_HOLD_S, lookup=look, say=text(look))
    return True


def add(tid, airline, total, days, rate_id=None, release=True, by=None):
    """A rate an automated source read on the page -> one more option of the waiting session. release: the clerk quotes
    on its next tick. by: the name of that source, logged with the rate. Not for rates copied by a person (5U rule)."""
    s = db.session(tid)
    if not s or s["status"] != "waiting_bids":
        raise SystemExit("request %s is %s: too late for a rate" % (tid, s["status"] if s else "unknown"))
    f = json.loads(s["fields"] or "{}")
    on_lane = airlines(f.get("origin"), f.get("destination"))
    hit = [a for a in on_lane if airline.lower() in ((a["code"] or "").lower(), (a["name"] or "").lower())]
    name, code = (hit[0]["name"], hit[0]["code"]) if hit else (airline, None)
    total = "%.2f" % float(total)
    opt = {"airline": name, "airline_code": code, "origin": f.get("origin"), "destination": f.get("destination"),
           "transit_days": int(days), "currency": "EUR", "total": total, "total_eur": total,
           "billed_kg": str(f.get("weight_kg_total")), "source": SOURCE}
    if rate_id:
        opt["rate_id"] = rate_id
    options = [o for o in json.loads(s["options"] or "[]") if not (o.get("airline") == name and o.get("source") == SOURCE)]
    db.update_session(tid, options=options + [opt], **({"deadline": time.time()} if release else {}))
    db.event("portal_page_price", tid, option=opt, released=release, by=by or config.PORTAL_PAGE_SOURCE or "unnamed source")
    return opt


def go(tid, by=None):
    """Quote now with what we have (the source cannot get the rate, or no portal airline matters)."""
    db.update_session(tid, deadline=time.time())
    db.event("portal_down", tid, held=False, why="released", by=by or config.PORTAL_PAGE_SOURCE or "unnamed source")


def main(argv):
    by = None
    if "--by" in argv:
        i = argv.index("--by")
        by, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    if not argv:
        rows = db.con().execute("SELECT thread_id FROM sessions WHERE status='waiting_bids' AND note LIKE 'RATE API DOWN%'").fetchall()
        for r in rows:
            s = db.session(r["thread_id"])
            print(json.dumps(dict(lookup(r["thread_id"]), seconds_left=round(s["received_at"] + 360 - time.time()))))
        return print("no request is waiting for a portal page rate") if not rows else None
    tid = int(argv[0])
    if len(argv) == 2 and argv[1] == "go":
        go(tid, by)
        return print("request %s: quoting now with what we have" % tid)
    if len(argv) < 4:
        return print(__doc__)
    opt = add(tid, argv[1], argv[2], argv[3], argv[4] if len(argv) > 4 else None, by=by)
    print("request %s: %s %s EUR, %s days added, quoting now" % (tid, opt["airline"], opt["total"], opt["transit_days"]))


if __name__ == "__main__":
    main(sys.argv[1:])
