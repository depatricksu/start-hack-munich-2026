"""Spot 5U's hourly setup changes the minute they happen.

    python3 -m monitor.changes            # every 60 s, prints one CHANGE line per difference (run next to the runner)
    python3 -m monitor.changes --once     # one check against the saved baseline

Watches, with free reads only (no rate-limited portal rate reads, no gateway spend):
  - API spec (/openapi.json): new or removed endpoints, changed parameters, limits and descriptions
  - portal lanes (/v1/portal/ports): lanes and airlines added or removed
  - weight breaks (/v1/portal/brackets) of every portal airline
  - gateway models (/v1/gateway/models): models added, removed, renamed
  - the public scoring rules on the board (/v1/board "rules")
Each difference is printed, logged as a `setup_change` event (the UI and monitor.timeline can show it) and saved to
data/setup_baseline.json so it is reported once. The clerk adapts to lanes and breaks on its own (sourcing/portal.py
re-reads them every 3 min); everything else here is for a human to act on, with a hint what to check.
"""
import difflib, json, os, sys, time
from core import config, db, mailbox

BASE = os.path.join(config.ROOT, "data", "setup_baseline.json")
HINT = {
    "openapi": "read the changed text: new rules, limits or fields; check mailbox.normalize, portal and booking calls",
    "ports": "the clerk re-reads lanes itself; check that quotes on these lanes still go out",
    "brackets": "the clerk re-reads breaks itself; the weight-break trick and sheet prices may shift",
    "models": "if our LLM_MODEL disappeared, set LLM_MODEL to a listed one and restart",
    "rules": "scoring changed: re-read the board rules and adjust what we optimise",
}


def _flat(o, p=""):
    out = {}
    if isinstance(o, dict):
        for k, v in o.items():
            out.update(_flat(v, p + "/" + str(k)))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out.update(_flat(v, p + "/" + str(i)))
    else:
        out[p] = o
    return out


def snapshot():
    snap = {}
    st, spec = mailbox.api("GET", "/openapi.json")
    if st == 200 and isinstance(spec, dict):
        snap["openapi"] = spec
    st, ports = mailbox.api("GET", "/v1/portal/ports")
    if st == 200 and isinstance(ports, dict):
        snap["ports"] = sorted("%s-%s:%s" % (l["origin"], l["destination"], ",".join(sorted(a["code"] for a in l["airlines"])))
                               for l in ports.get("lanes", []))
        codes = sorted({a["code"] for l in ports.get("lanes", []) for a in l["airlines"]})
        br = {}
        for c in codes:
            st, b = mailbox.api("GET", "/v1/portal/brackets", params={"airline": c})
            if st == 200 and isinstance(b, dict):
                br[c] = b.get("breaks_kg")
        snap["brackets"] = br
    st, models = mailbox.api("GET", "/v1/gateway/models")
    if st == 200:
        items = models.get("data", models) if isinstance(models, dict) else models
        snap["models"] = sorted(str(m.get("id") if isinstance(m, dict) else m) for m in (items or []))
    st, board = mailbox.api("GET", "/v1/board")
    if st == 200 and isinstance(board, dict):
        snap["rules"] = board.get("rules")
    return snap


def diff(kind, old, new):
    """Short human lines for one kind of difference."""
    if kind == "openapi":
        fo, fn = _flat(old), _flat(new)
        lines = []
        for k in sorted(set(fo) | set(fn)):
            a, b = fo.get(k), fn.get(k)
            if a == b or "/422/" in k or "ValidationError" in k:
                continue
            if isinstance(a, str) and isinstance(b, str) and len(a) > 60:
                for d in difflib.ndiff(a.split(". "), b.split(". ")):
                    if d[:1] in "+-":
                        lines.append("%s %s" % (k, d[:200]))
            else:
                lines.append("%s: %s -> %s" % (k, str(a)[:80], str(b)[:120]))
        return lines[:40]
    if kind in ("ports", "models"):
        o, n = set(old or []), set(new or [])
        return ["+ " + x for x in sorted(n - o)] + ["- " + x for x in sorted(o - n)]
    if kind == "brackets":
        return ["%s: %s -> %s" % (c, (old or {}).get(c), (new or {}).get(c))
                for c in sorted(set(old or {}) | set(new or {})) if (old or {}).get(c) != (new or {}).get(c)]
    return ["%s -> %s" % (json.dumps(old)[:200], json.dumps(new)[:200])]


def check():
    snap = snapshot()
    try:
        base = json.load(open(BASE))
    except Exception:
        base = {}
    found = 0
    for kind, new in snap.items():
        if kind not in base:
            continue                                  # first sight: baseline only
        if json.dumps(base[kind], sort_keys=True) != json.dumps(new, sort_keys=True):
            lines = diff(kind, base[kind], new)
            found += 1
            print("%s CHANGE %s (%d differences). What to check: %s" % (time.strftime("%H:%M:%S"), kind, len(lines),
                                                                        HINT[kind]), flush=True)
            for l in lines[:15]:
                print("    " + l, flush=True)
            db.event("setup_change", what=kind, differences=lines)
    base.update(snap)
    os.makedirs(os.path.dirname(BASE), exist_ok=True)
    json.dump(base, open(BASE, "w"))
    return found


def run(once=False):
    if not config.API_KEY:
        sys.exit("FIVEU_API_KEY missing (.env)")
    print("%s watching the 5U setup every 60 s (baseline %s)" % (time.strftime("%H:%M:%S"), BASE), flush=True)
    while True:
        try:
            n = check()
            if once:
                print("no change" if not n else "%d kinds changed" % n)
                return
        except Exception as e:
            print("%s check failed: %s" % (time.strftime("%H:%M:%S"), e), flush=True)
        time.sleep(60)


if __name__ == "__main__":
    run(once="--once" in sys.argv)
