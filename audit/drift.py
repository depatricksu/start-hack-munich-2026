"""Spot 5U's hourly change in the FIRST round it shows up. Owner: Riky.

5U changes the setup about once an hour without notice (17:00: dangerous goods only in the attachment). We lost
rounds 10 and 11 before anyone knew why. This tool looks at two things and says what is NEW:

1. The requests themselves (our DB: live on the runner, or the snapshot): every customer RFQ is turned into a set
   of features (attachment types, logistics concepts like Incoterms / insurance / customs / temperature / lithium,
   currencies, airports, lots, languages, "deliver to" ...). A feature never seen in the first requests of the day is
   reported with the request that brought it.
2. The public board: a closed round where 5U accepted half or less of the answers = most teams fell for something.

    python3 -m audit.drift                    # report on examples/real/snapshot.db (or DB_PATH=...)
    python3 -m audit.drift --watch            # every 30 s; NEW findings are posted to the agent chat (issue #2)
    python3 -m audit.drift --watch --no-post  # same, print only

Read-only on the DB. Posting uses `gh issue comment 2`, each finding once (data/drift_seen.json).
"""
import json, os, re, sqlite3, subprocess, sys, time, urllib.request

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DB = os.environ.get("DB_PATH") or os.path.join(ROOT, "data", "forwarder.db")
SNAPSHOT = os.path.join(ROOT, "examples", "real", "snapshot.db")
SEEN = os.path.join(ROOT, "data", "drift_seen.json")
BOARD = os.environ.get("FIVEU_BASE_URL", "https://api.start-hack.5u.ai") + "/v1/board"
BASELINE_N = int(os.environ.get("DRIFT_BASELINE", "8"))   # the first N requests of the day define "normal"

OUR_AIRPORTS = {"CGN", "DUS", "FRA", "HAM", "MUC", "STR"}
CONCEPTS = {
    "dangerous_goods": r"dangerous|\bdgr\b|hazmat|gefahrgut|\bUN\s?\d{4}\b|class \d(?:\.\d)?\b",
    "lithium_battery": r"lithium|battery|batteries|akku",
    "incoterm": r"\b(?:EXW|FCA|FOB|CPT|CIP|DAP|DPU|DDP|CFR|CIF)\b",
    "insurance": r"insurance|insured|versicherung",
    "customs": r"customs|export declaration|zoll|\bEORI\b|\bHS code\b|tariff code",
    "temperature": r"temperature|°c|refrigerat|cool chain|cold chain|frozen|kühl",
    "oversize_or_heavy_piece": r"oversize|non-stackable|not stackable|nicht stapelbar|over-?height|single piece of \d{3,}",
    "door_delivery": r"deliver(?:y)? to (?:the )?(?:consignee|door|address)|door[- ]to[- ]door|zustellung",
    "deadline": r"must arrive|latest arrival|no later than|deadline|by (?:monday|tuesday|wednesday|thursday|friday)",
    "import_wording": r"\bimport\b",
    "multiple_lots": r"\blot \d|\blots\b|several shipments|two shipments|separate shipments",
    "valuable_or_special": r"valuable|high value|perishable|live animal|human remains|pharma",
    "rate_or_contract_ref": r"contract rate|our agreed rate|reference rate|as per (?:our|the) (?:contract|agreement)",
    "vague_request": r"as usual|same as last time|like before",
}
CURRENCIES = r"\b(USD|EUR|GBP|CHF|CNY|JPY|PLN|SEK)\b|\$|£"


def features(subject, body, attachments):
    text = f"{subject}\n{body}"
    low = text.lower()
    f = set()
    for name, rx in CONCEPTS.items():
        if re.search(rx, text, re.I):
            f.add("concept:" + name)
    for cur in re.findall(CURRENCIES, text):
        f.add("currency:" + (cur if isinstance(cur, str) and cur else "symbol"))
    for code in re.findall(r"\b([A-Z]{3})\b", text):
        if code in OUR_AIRPORTS:
            f.add("origin_airport_named")
    for att in attachments or []:
        name = (att.get("filename") or att.get("name") or "") if isinstance(att, dict) else str(att)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else "noext"
        f.add("attachment:" + ext)
    if not attachments:
        f.add("attachment:none")
    if re.search(r"[äöüß]|\b(bitte|sehr geehrte|grüße)\b", low):
        f.add("lang:de")
    if re.search(r"\b(bonjour|merci|veuillez)\b", low):
        f.add("lang:fr")
    if re.search(r"\b(ciao|buongiorno|grazie)\b", low):
        f.add("lang:it")
    if re.search(r"\b(hola|gracias|por favor)\b", low):
        f.add("lang:es")
    return f


def requests(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    out = []
    for m in c.execute("SELECT * FROM mails WHERE route='rfq' ORDER BY id"):
        raw = {}
        try:
            raw = json.loads(m["raw"]) if "raw" in m.keys() and m["raw"] else {}
        except ValueError:
            pass
        out.append({"id": m["id"], "subject": m["subject"] or "", "body": m["body"] or "",
                    "attachments": raw.get("attachments") or [], "received_at": m["received_at"] if "received_at" in m.keys() else None})
    return out


def request_findings(path):
    reqs = requests(path)
    base = set()
    for r in reqs[:BASELINE_N]:
        base |= features(r["subject"], r["body"], r["attachments"])
    found = []
    for r in reqs[BASELINE_N:]:
        new = features(r["subject"], r["body"], r["attachments"]) - base
        for feat in sorted(new):
            found.append(("request", f"{feat}", r["id"], r["body"][:220].replace("\n", " ")))
        base |= new                                       # report each new feature once, with its first request
    return found


def board_findings():
    with urllib.request.urlopen(BOARD, timeout=10) as r:
        d = json.load(r)
    out = []
    for rd in d.get("rounds", []):
        if rd.get("status") == "closed" and rd.get("answered") and rd["accepted"] <= rd["answered"] / 2:
            out.append(("board", f"round {rd['round_no']} only {rd['accepted']}/{rd['answered']} accepted",
                        rd["round_no"], rd["sent_at"][11:16] + " UTC"))
    return out


def _seen():
    try:
        return set(json.load(open(SEEN)))
    except Exception:
        return set()


def _post(lines):
    body = "From Riky's drift watch (audit/drift.py), possible 5U change:\n" + "\n".join(lines)
    subprocess.run(["gh", "issue", "comment", "2", "--body", body], cwd=ROOT, capture_output=True, timeout=30)


def run_once(post=False):
    path = DB if os.path.exists(DB) else SNAPSHOT
    findings = []
    if os.path.exists(path):
        findings += request_findings(path)
    try:
        findings += board_findings()
    except Exception as e:
        print("board error:", e)
    seen = _seen()
    fresh = [f for f in findings if f"{f[0]}|{f[1]}|{f[2]}" not in seen]
    for kind, what, ref, detail in findings:
        mark = "NEW " if (kind, what, ref, detail) in fresh else "    "
        print(f"{mark}{kind:<8} {what:<45} {ref}  {detail}")
    if fresh:
        os.makedirs(os.path.dirname(SEEN), exist_ok=True)
        json.dump(sorted(seen | {f"{f[0]}|{f[1]}|{f[2]}" for f in fresh}), open(SEEN, "w"))
        if post and seen:                                  # first run only builds the memory, never floods the chat
            _post([f"- **{w}** ({k} {r}): {d[:160]}" for k, w, r, d in fresh[:8]])
    return fresh


def main(argv):
    post = "--watch" in argv and "--no-post" not in argv
    if "--watch" in argv:
        while True:
            run_once(post)
            time.sleep(30)
    run_once(False)


if __name__ == "__main__":
    main(sys.argv[1:])
