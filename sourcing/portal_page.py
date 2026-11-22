"""A rate a PERSON read on the portal's web page, when the rate API is down.

5U, 22 Nov 01:15 to 02:08 (rounds 93 to 100): the rate API answered 503 "The rate API is unavailable", and the rate
desk and the 15 portal airlines stopped answering mail. The prices existed in one place only: the "Rate portal" page
(https://start-hack.5u.ai/portal/ui, linked on the leaderboard). That page asks a person to solve a sum for every
rate, so it is not automated here: a person types the lane, reads the rate, and passes it in with this module.
Rounds 93 to 97 were quoted from the sheets alone: all rejected too_low (the fastest airline was a portal airline
each time). Rounds 98, 99, 100 used a rate read by hand: accuracy 45 of 45 each.

    python3 -m sourcing.portal_page                      what to look up for the request that is on hold
    python3 -m sourcing.portal_page 29224 BX 645.60 1 R-CN-Uk_5BeqIhb2d4     add the rate and quote at once
    python3 -m sourcing.portal_page 29224 go             quote now with what we have

Type the REAL weight and volume of the request on the page. The portal bills by chargeable weight, a heavier weight
does not find a cheaper bracket for bulky cargo (checked on 285 stored rates and on round 98).
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
    return "RATE PORTAL DOWN. Read the rate on %s: airline %s | %s to %s | %g kg | %g cbm" % (
        URL, names, look["origin"], look["destination"], look["weight_kg"] or 0, look["volume_cbm"] or 0)


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
    if not decides(look, options):
        db.event("portal_down", tid, mail_id, held=False, why="no portal airline can be the answer here", lookup=look)
        return False
    s = db.session(tid)
    until = s["received_at"] + config.PORTAL_DOWN_HOLD_S
    db.update_session(tid, deadline=until, note=text(look))
    db.event("portal_down", tid, mail_id, held=True, hold_s=config.PORTAL_DOWN_HOLD_S, lookup=look, say=text(look))
    return True


def add(tid, airline, total, days, rate_id=None, release=True):
    """A rate read on the page -> one more option of the waiting session. release: the clerk quotes on its next tick."""
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
    db.event("portal_page_price", tid, option=opt, released=release)
    return opt


def go(tid):
    """Quote now with what we have (nobody can read the page, or no portal airline matters)."""
    db.update_session(tid, deadline=time.time())
    db.event("portal_down", tid, held=False, why="released by a person")


def main(argv):
    if not argv:
        rows = db.con().execute("SELECT thread_id FROM sessions WHERE status='waiting_bids' AND note LIKE 'RATE PORTAL DOWN%'").fetchall()
        for r in rows:
            s = db.session(r["thread_id"])
            print("request %s, %d s left: %s" % (r["thread_id"], s["received_at"] + 360 - time.time(), text(lookup(r["thread_id"]))))
        return print("no request is on hold for a portal rate") if not rows else None
    tid = int(argv[0])
    if len(argv) == 2 and argv[1] == "go":
        go(tid)
        return print("request %s: quoting now with what we have" % tid)
    if len(argv) < 4:
        return print(__doc__)
    opt = add(tid, argv[1], argv[2], argv[3], argv[4] if len(argv) > 4 else None)
    print("request %s: %s %s EUR, %s days added, quoting now" % (tid, opt["airline"], opt["total"], opt["transit_days"]))


if __name__ == "__main__":
    main(sys.argv[1:])
