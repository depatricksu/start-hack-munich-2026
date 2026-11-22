"""Find any case, old (imported, history/importer.py) or live, in one search. Owner: Patrick.

    python3 -m history.find lindqvist ORD           # every word must match: customer, company, lane, goods, airline...
    python3 -m history.find BK-AW8CXJCM             # a reference: BK-, GOOGLE-, INV-, AWB
    python3 -m history.find weber 2025-03           # a month (or a day: 2025-03-14)
    python3 -m history.find 820kg FRA JFK           # a weight (+-2%)
    python3 -m history.find --case mail:<id>        # one case with every mail of it, oldest first
    python3 -m history.find --duplicates            # requests sent twice, and what they were linked to

For the agent: archived_status(text, lang) answers "what happened to my shipment BK-... from March" from the archive
when the live tables do not know the reference (booking/tracking.py uses it). Read only.
"""
import datetime as dt, json, re, sys

from core import db
from . import importer

IATA = re.compile(r"^[A-Z]{3}$")
MONTH = re.compile(r"^(20\d\d)-(\d\d)(?:-(\d\d))?$")
KG = re.compile(r"^(\d+(?:[.,]\d+)?)\s*kg$", re.I)


def _rows():
    c = importer.con()
    docs = {}
    for k, kind, fn, text in c.execute("SELECT case_key, kind, filename, substr(text,1,3000) FROM archive_docs WHERE case_key IS NOT NULL"):
        docs.setdefault(k, []).append("%s %s %s" % (kind, fn, text or ""))
    for r in c.execute("SELECT * FROM archive_cases"):
        d = dict(r)
        d["where"] = "archive"
        d["docs_text"] = " ".join(docs.get(d["key"], []))
        d["n_docs"] = len(docs.get(d["key"], []))
        yield d
    try:
        for r in c.execute("SELECT s.thread_id, s.customer, s.subject, s.status, s.fields, s.chosen, s.received_at, "
                           "b.booking_reference, b.airline AS b_airline, b.status AS b_status FROM sessions s "
                           "LEFT JOIN bookings b ON b.thread_id = s.thread_id"):
            f, ch = json.loads(r["fields"] or "{}"), json.loads(r["chosen"] or "{}")
            yield {"key": "live:%s" % r["thread_id"], "where": "live", "customer": r["customer"], "company": None,
                   "subject": r["subject"], "origin": f.get("origin") or ch.get("origin"), "destination": f.get("destination"),
                   "weight_kg": f.get("weight_kg_total") or f.get("weight_kg"), "volume_cbm": f.get("volume_cbm_total"),
                   "commodity": f.get("commodity"), "price": ch.get("total"), "currency": ch.get("currency"),
                   "airline": r["b_airline"] or ch.get("airline"), "booking_reference": r["booking_reference"],
                   "refs": json.dumps([x for x in (r["booking_reference"], "GOOGLE-%s" % r["thread_id"]) if x]),
                   "status": r["b_status"] or r["status"], "first_at": r["received_at"], "last_at": r["received_at"],
                   "n_mails": None, "sources": "[]", "duplicate_of": None, "note": None}
    except Exception:
        pass                                                      # a DB without live tables (archive only)


def _hay(c):
    return " ".join(str(c.get(k) or "") for k in ("customer", "company", "subject", "origin", "destination", "commodity",
                                                  "airline", "booking_reference", "refs", "status", "note", "docs_text")).lower()


def matches(c, words):
    hay = _hay(c)
    for w in words:
        m, k = MONTH.match(w), KG.match(w)
        if m and c.get("first_at"):
            day = dt.datetime.fromtimestamp(c["first_at"]).strftime("%Y-%m-%d")
            if not day.startswith(w):
                return False
        elif m:
            return False
        elif k:
            kg = float(k.group(1).replace(",", "."))
            if not (c.get("weight_kg") and abs(c["weight_kg"] - kg) <= 0.02 * kg):
                return False
        elif IATA.match(w):
            if w not in (c.get("origin"), c.get("destination")) and w.lower() not in hay:
                return False
        elif w.lower() not in hay:
            return False
    return True


def search(words, limit=50):
    hits = [c for c in _rows() if matches(c, words)]
    return sorted(hits, key=lambda c: -(c.get("first_at") or 0))[:limit]


def by_reference(text):
    """The archived case a mail's reference points to (BK-, GOOGLE-, INV-, AWB), or None."""
    refs = {x.upper().replace(" ", "") for x in importer.REF.findall(text or "")}
    if not refs:
        return None
    for c in importer.con().execute("SELECT * FROM archive_cases"):
        if refs & set(json.loads(c["refs"] or "[]")) or (c["booking_reference"] or "").upper() in refs:
            return dict(c)
    return None


STATUS = {
    "en": {"confirmed": "flown and closed", "booked": "booked", "cancelled": "cancelled", "lost": "not booked (offer declined)",
           "quoted": "quoted, not booked", "open": "not quoted"},
    "de": {"confirmed": "geflogen und abgeschlossen", "booked": "gebucht", "cancelled": "storniert",
           "lost": "nicht gebucht (Angebot abgelehnt)", "quoted": "angeboten, nicht gebucht", "open": "nicht angeboten"},
}


def archived_status(text, lang="en"):
    """A short answer about an OLD shipment from the archive, or None. Facts only, no promises."""
    c = by_reference(text)
    if not c:
        return None
    lang = "de" if (lang or "").startswith("de") else "en"
    day = dt.datetime.fromtimestamp(c["first_at"]).strftime("%d.%m.%Y" if lang == "de" else "%d %b %Y") if c["first_at"] else "?"
    from llm.extract import SIGNER
    sign = lambda l: ("Viele Grüße\n%s\nLuftfracht Export" if l == "de" else "Best regards\n%s\nAir Export") % SIGNER
    ref = c["booking_reference"] or ", ".join(json.loads(c["refs"] or "[]")) or "-"
    if lang == "de":
        body = ("Guten Tag,\n\nich habe die Sendung in unserem Archiv gefunden: %s, %s nach %s, %s kg, Anfrage vom %s. "
                "Stand: %s%s.\n\nWenn es dazu eine offene Frage gibt, antworten Sie einfach auf diese Mail, ich kümmere "
                "mich darum.\n\n%s") % (ref, c["origin"] or "?", c["destination"] or "?", "%g" % c["weight_kg"] if c["weight_kg"] else "?",
                                       day, STATUS["de"].get(c["status"], c["status"]),
                                       (", Airline %s" % c["airline"]) if c["airline"] else "", sign("de"))
    else:
        body = ("Hello,\n\nI found this shipment in our archive: %s, %s to %s, %s kg, requested on %s. Status: %s%s.\n\n"
                "If there is an open question about it, just reply to this mail and I will take care of it.\n\n%s") % (
            ref, c["origin"] or "?", c["destination"] or "?", "%g" % c["weight_kg"] if c["weight_kg"] else "?", day,
            STATUS["en"].get(c["status"], c["status"]), (", airline %s" % c["airline"]) if c["airline"] else "", sign("en"))
    return body


def show_case(key):
    c = importer.con()
    k = c.execute("SELECT * FROM archive_cases WHERE key=?", (key,)).fetchone()
    if not k:
        print("no such case")
        return
    k = dict(k)
    print("CASE %s  [%s]  %s" % (k["key"], k["status"], k["subject"] or ""))
    for f in ("customer", "company", "origin", "destination", "weight_kg", "volume_cbm", "commodity", "pickup_postcode", "price",
              "currency", "airline", "booking_reference", "refs", "sources", "duplicate_of", "note"):
        if k.get(f) not in (None, "", "[]"):
            print("  %-18s %s" % (f, k[f]))
    for d in c.execute("SELECT * FROM archive_docs WHERE case_key=? ORDER BY filename", (key,)):
        first = " / ".join(l.strip() for l in (d["text"] or "").splitlines()[:3] if l.strip())
        print("  document  %-34s %-20s %-5s linked by %-20s %s" % (d["filename"][:34], d["kind"], d["how"] or "-",
                                                                  d["linked_by"] or "-", first[:90]))
    for m in c.execute("SELECT * FROM archive_mails WHERE case_key=? ORDER BY date", (key,)):
        when = dt.datetime.fromtimestamp(m["date"]).strftime("%Y-%m-%d %H:%M") if m["date"] else "?"
        tag = " (duplicate, kept %s)" % m["duplicate_of"] if m["duplicate_of"] else ""
        print("\n  %s  %-8s %s: %s%s\n    %s" % (when, m["role"], m["sender"], m["subject"], tag,
                                            (m["body"] or "").strip().replace("\n", " ")[:300]))


def _line(c):
    day = dt.datetime.fromtimestamp(c["first_at"]).strftime("%Y-%m-%d") if c.get("first_at") else "?"
    return "%-7s %s  %-10s %-34s %s-%s %8s kg %12s %-22s %s%s" % (
        c["where"], day, c["status"] or "?", (c["customer"] or c["company"] or "?")[:34], c["origin"] or "?",
        c["destination"] or "?", "%g" % c["weight_kg"] if c.get("weight_kg") else "?",
        ("%s %s" % (c["price"], c["currency"] or "")) if c.get("price") else "-", (c.get("airline") or "-")[:22],
        c["key"], "  DUPLICATE of %s" % c["duplicate_of"] if c.get("duplicate_of") else "")


def main(argv):
    if "--case" in argv:
        return show_case(argv[argv.index("--case") + 1])
    if "--docs" in argv:
        for d in importer.con().execute("SELECT * FROM archive_docs ORDER BY case_key IS NULL, filename"):
            print("%-36s %-20s %-5s %-24s %s" % (d["filename"][:36], d["kind"], d["how"] or "-", d["linked_by"] or "NOT LINKED",
                                                d["case_key"] or ""))
        return
    if "--duplicates" in argv:
        for c in importer.con().execute("SELECT * FROM archive_cases WHERE duplicate_of IS NOT NULL ORDER BY first_at"):
            print(_line(dict(c, where="archive")))
        return
    hits = search([a for a in argv if not a.startswith("--")])
    for c in hits:
        print(_line(c))
    print("%d case(s)" % len(hits))


if __name__ == "__main__":
    main(sys.argv[1:])
