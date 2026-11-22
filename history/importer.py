"""Bring a forwarder's OLD data into our system: the switch-over in one command. Owner: Patrick.

    python3 -m history.importer old_mail.mbox                    # a mailbox export (Outlook / Thunderbird / Gmail Takeout)
    python3 -m history.importer exported_mails/                  # a folder of .eml files (subfolders too)
    python3 -m history.importer shipments_2025.xlsx bookings.csv # the shipment register the team kept in Excel
    python3 -m history.importer old_forwarder.db                 # another clerk database (same tables as ours)
    python3 -m history.importer ... --ours sales@ourfirm.de,ourfirm.de   # who "we" are in the old mails
    python3 -m history.importer ... --dry                        # report only, write nothing

What it does, code only (no AI call, no mail is ever sent):
  1. reads every mail and register row, whatever the source
  2. drops duplicate mails (same Message-ID, or the same mail exported twice / sent to two colleagues)
  3. sorts mails into conversations (reply headers first, then subject + customer + time)
  4. turns each customer conversation into a CASE: lane, weight, volume, pickup, goods, our price, airline,
     booking reference, outcome (open / quoted / booked / confirmed / lost / cancelled), first and last mail
  5. merges duplicates: a register row and the mail conversation of the same shipment become one case; a request
     the customer sent twice is linked to the first one (duplicate_of)
  6. stores it in archive_cases / archive_mails, next to the live tables, never inside them. Running it again on the
     same files changes nothing (stable keys), so a growing archive can be re-imported any time.
Find old cases afterwards: python3 -m history.find <words, customer, lane, reference, date>.
"""
import csv, email, email.policy, email.utils, hashlib, html, json, mailbox, os, re, sqlite3, sys, time
from collections import defaultdict

from core import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS archive_mails(mid TEXT PRIMARY KEY, case_key TEXT, date REAL, sender TEXT, recipients TEXT,
  subject TEXT, body TEXT, in_reply_to TEXT, refs TEXT, files TEXT, source TEXT, role TEXT, duplicate_of TEXT, imported_at REAL);
CREATE TABLE IF NOT EXISTS archive_cases(key TEXT PRIMARY KEY, customer TEXT, company TEXT, subject TEXT, origin TEXT,
  destination TEXT, weight_kg REAL, volume_cbm REAL, pieces INTEGER, commodity TEXT, pickup_postcode TEXT, ready_date TEXT,
  price TEXT, currency TEXT, airline TEXT, booking_reference TEXT, refs TEXT, status TEXT, first_at REAL, last_at REAL,
  n_mails INTEGER, sources TEXT, duplicate_of TEXT, note TEXT, imported_at REAL);
"""
_KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "start-kit")
CARRIERS = {r["email"].lower(): r["name"] for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv")))}
AIRLINES = sorted({r["name"] for r in csv.DictReader(open(os.path.join(_KIT, "carrier-list.csv"))) if r["kind"] == "airline"},
                  key=len, reverse=True)
REF = re.compile(r"\b(BK-[A-Z0-9]{6,12}|GOOGLE-\d+(?:-\d+)?|INV-\d+|AWB[\s:-]*\d{3}-?\d{8}|\d{3}-\d{8})\b", re.I)
PREFIX = re.compile(r"^\s*((re|aw|antw|wg|fw|fwd|tr|rif|r)\s*(\[\d+\])?\s*:\s*)+", re.I)
MONEY = re.compile(r"(?:(EUR|€|USD|\$|CHF)\s*(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?))|"
                   r"(?:(\d{1,3}(?:[.,\s]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)\s*(EUR|€|USD|\$|CHF))", re.I)
ORIGINS = {"FRA", "MUC", "DUS", "CGN", "HAM", "STR"}
LANE = re.compile(r"\b([A-Z]{3})\s*(?:to|nach|->|→|–|-)\s*([A-Z]{3})\b")


def _own(m):
    from booking.handlers import own_text
    return own_text(m["body"], m["subject"])[:600]


CANCEL = re.compile(r"\b(cancel\w*|storn\w*|annul\w*|no longer needed|nicht mehr ben[öo]tigt)\b", re.I)
CONFIRMED = re.compile(r"\b(booking\s+BK-\S+\s+(?:is\s+)?confirmed|confirmed|bestätigt)\b", re.I)


def con():
    c = db.con()
    c.executescript(SCHEMA)
    return c


# ------------------------------------------------------------------------------------------------ reading
def _text_of(msg):
    """Plain text of an email.message: text/plain first, else HTML without tags."""
    plain, htm = [], []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for p in parts:
        if p.get_content_maintype() == "multipart" or p.get_filename():
            continue
        try:
            payload = p.get_payload(decode=True) or b""
            t = payload.decode(p.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        (plain if p.get_content_type() == "text/plain" else htm if p.get_content_type() == "text/html" else []).append(t)
    if plain:
        return "\n".join(plain).strip()
    raw = "\n".join(htm)
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip()


def _addr(v):
    return (email.utils.parseaddr(v or "")[1] or "").lower()


def _msg_record(msg, source):
    date = msg.get("Date")
    try:
        ts = email.utils.parsedate_to_datetime(date).timestamp() if date else None
    except Exception:
        ts = None
    refs = re.findall(r"<[^>]+>", (msg.get("References") or "") + " " + (msg.get("In-Reply-To") or ""))
    return {"mid": (msg.get("Message-ID") or "").strip(), "date": ts, "sender": _addr(msg.get("From")),
            "sender_name": email.utils.parseaddr(msg.get("From") or "")[0],
            "recipients": ",".join(a for _, a in email.utils.getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []))).lower(),
            "subject": str(msg.get("Subject") or ""), "body": _text_of(msg),
            "in_reply_to": (msg.get("In-Reply-To") or "").strip(), "refs": refs,
            "files": [p.get_filename() for p in msg.walk() if p.get_filename()], "source": source}


def read_mbox(path):
    box = mailbox.mbox(path, factory=lambda f: email.message_from_binary_file(f, policy=email.policy.compat32), create=False)
    try:
        for msg in box:
            yield _msg_record(msg, os.path.basename(path))
    finally:
        box.close()


def read_eml(path):
    with open(path, "rb") as f:
        yield _msg_record(email.message_from_binary_file(f, policy=email.policy.compat32), os.path.basename(path))


def read_db(path):
    """Another clerk database: its incoming mails, plus the mails it SENT (kept in its event log, not in `mails`).
    Its thread ids become reply links; its router's verdict says who is a customer."""
    from core import config
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT id, sender, subject, body, thread_id, received_at, route FROM mails ORDER BY id").fetchall()
    sent = c.execute("SELECT id, ts, thread_id, kind, data FROM events WHERE kind IN ('mail_out','bid_mail_out') ORDER BY id").fetchall() \
        if "events" in {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")} else []
    c.close()
    name = os.path.basename(path)
    link = lambda t: "<db-%s-%s>" % (name, t)
    for r in rows:
        reply = r["thread_id"] and r["thread_id"] != r["id"]
        yield {"mid": link(r["id"]), "date": r["received_at"], "sender": (r["sender"] or "").lower(), "sender_name": "",
               "recipients": config.OUR_ADDRESS, "subject": r["subject"] or "", "body": r["body"] or "",
               "in_reply_to": link(r["thread_id"]) if reply else "", "refs": [link(r["thread_id"])] if reply else [],
               "files": [], "source": name, "route": r["route"]}
    for e in sent:
        d = json.loads(e["data"] or "{}")
        yield {"mid": "<db-%s-out-%s>" % (name, e["id"]), "date": e["ts"], "sender": config.OUR_ADDRESS, "sender_name": "",
               "recipients": (d.get("to") or "").lower(), "subject": d.get("subject") or "", "body": d.get("body") or "",
               "in_reply_to": link(e["thread_id"]) if e["thread_id"] else "", "refs": [link(e["thread_id"])] if e["thread_id"] else [],
               "files": [a.get("filename") for a in d.get("attachments") or []], "source": name,
               "route": "carrier" if e["kind"] == "bid_mail_out" else "ours"}


COLS = {   # register column -> our field, by the headers forwarders actually use (en / de)
    "date": r"^(date|datum|booking date|buchungsdatum|shipment date|versanddatum|ready|created)$",
    "customer": r"^(customer|kunde|client|shipper|versender|e-?mail|customer e-?mail|contact)$",
    "company": r"^(company|firma|customer name|kundenname|account)$",
    "origin": r"^(origin|from|von|abgang|departure|dep|aop|origin airport)$",
    "destination": r"^(destination|to|nach|ziel|dest|arrival|aod|destination airport)$",
    "weight_kg": r"^(weight|gewicht|kg|weight kg|gross weight|bruttogewicht|gross kg)$",
    "volume_cbm": r"^(volume|volumen|cbm|m3|volume cbm)$",
    "pieces": r"^(pieces|pcs|stück|colli|packages)$",
    "price": r"^(price|preis|rate|total|amount|betrag|sell|selling price|verkaufspreis|all-?in)$",
    "currency": r"^(currency|währung|cur|ccy)$",
    "airline": r"^(airline|carrier|fluggesellschaft|carrier name)$",
    "booking_reference": r"^(booking|booking ref|booking reference|buchungsnummer|awb|mawb|reference|ref|referenz)$",
    "status": r"^(status|state|stand)$",
    "commodity": r"^(goods|commodity|ware|description|beschreibung)$",
}


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.,-]", "", str(v))
    if re.search(r",\d{1,2}$", s):                             # 1.234,50 (German)
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _date(v):
    """A register date in any common form -> timestamp, or None."""
    import datetime as dt
    if v is None or v == "":
        return None
    if hasattr(v, "timestamp"):
        return v.timestamp()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y", "%m/%d/%Y"):
        for cand in (s, s[:10]):
            try:
                return dt.datetime.strptime(cand, fmt).timestamp()
            except ValueError:
                continue
    return None


def read_register(path):
    """CSV or XLSX shipment list -> case dicts (one per row)."""
    rows = []
    if path.lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            head = next(it, None)
            if head:
                rows += [dict(zip([str(h or "").strip() for h in head], r)) for r in it if any(x not in (None, "") for x in r)]
    else:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            raw = f.read()
        dialect = csv.Sniffer().sniff(raw[:2000], delimiters=",;\t") if raw.strip() else csv.excel
        rows = list(csv.DictReader(raw.splitlines(), dialect=dialect))
    for i, r in enumerate(rows):
        m = {}
        for h, v in r.items():
            for field, rx in COLS.items():
                if field not in m and re.match(rx, (h or "").strip(), re.I):
                    m[field] = v
        yield {"row": i + 2, "source": os.path.basename(path), **{
            "customer": str(m.get("customer") or "").strip().lower() or None, "company": str(m.get("company") or "").strip() or None,
            "origin": (str(m.get("origin") or "").strip().upper()[:3] or None), "destination": (str(m.get("destination") or "").strip().upper()[:3] or None),
            "weight_kg": _num(m.get("weight_kg")), "volume_cbm": _num(m.get("volume_cbm")), "pieces": _num(m.get("pieces")),
            "price": _num(m.get("price")), "currency": (str(m.get("currency") or "").strip().upper() or None),
            "airline": str(m.get("airline") or "").strip() or None, "booking_reference": str(m.get("booking_reference") or "").strip() or None,
            "status": str(m.get("status") or "").strip().lower() or None, "commodity": str(m.get("commodity") or "").strip() or None,
            "date": _date(m.get("date"))}}


def _starts_from(path):
    with open(path, "rb") as f:
        return f.read(5) == b"From "


def read_any(path):
    """-> (mails, register rows) from a file or a folder."""
    mails, rows = [], []
    if os.path.isdir(path):
        for root, _, files in os.walk(path):
            for f in sorted(files):
                m, r = read_any(os.path.join(root, f))
                mails += m
                rows += r
        return mails, rows
    low = path.lower()
    if low.endswith(".eml"):
        mails += list(read_eml(path))
    elif low.endswith((".mbox", ".mbx")) or (not os.path.splitext(low)[1] and _starts_from(path)):
        mails += list(read_mbox(path))
    elif low.endswith((".db", ".sqlite", ".sqlite3")):
        mails += list(read_db(path))
    elif low.endswith((".csv", ".xlsx", ".xlsm", ".tsv")):
        rows += list(read_register(path))
    return mails, rows


# ------------------------------------------------------------------------------------------------ sorting
def _norm_subject(s):
    return re.sub(r"\s+", " ", PREFIX.sub("", s or "")).strip().lower()


def _fingerprint(m):
    body = re.sub(r"\s+", " ", (m["body"] or "")[:800]).strip().lower()
    return hashlib.sha1(("%s|%s|%s|%s" % (m["sender"], _norm_subject(m["subject"]), body,
                                          int((m["date"] or 0) // 300))).encode()).hexdigest()


def dedupe_mails(mails):
    """Same Message-ID, or the same mail exported twice (sender, subject, body, 5 minutes): keep the first."""
    seen, out, dups = {}, [], []
    for m in sorted(mails, key=lambda x: x["date"] or 0):
        keys = [k for k in (m["mid"], _fingerprint(m)) if k]
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit:
            dups.append((m, hit))
            continue
        if not m["mid"]:
            m["mid"] = "<fp-%s>" % _fingerprint(m)
        for k in keys:
            seen[k] = m["mid"]
        out.append(m)
    return out, dups


def guess_ours(mails):
    """The address that writes to the most different people is us (override with --ours)."""
    talks = defaultdict(set)
    for m in mails:
        for r in (m["recipients"] or "").split(","):
            if r:
                talks[m["sender"]].add(r)
    return {max(talks, key=lambda a: len(talks[a]))} if talks else set()


def is_ours(addr, ours):
    return any(addr == o or addr.endswith("@" + o.lstrip("@")) for o in ours)


def threads(mails, ours):
    """Union of reply links; mails without headers join by subject + the same customer within 45 days."""
    parent = {m["mid"]: m["mid"] for m in mails}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a, b):
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    for m in mails:
        for r in m["refs"] + ([m["in_reply_to"]] if m["in_reply_to"] else []):
            join(m["mid"], r)
    by_subject = defaultdict(list)
    for m in sorted(mails, key=lambda x: x["date"] or 0):
        party = m["sender"] if not is_ours(m["sender"], ours) else (m["recipients"] or "").split(",")[0]
        by_subject[(_norm_subject(m["subject"]), party)].append(m)
    for group in by_subject.values():
        for a, b in zip(group, group[1:]):
            if (b["date"] or 0) - (a["date"] or 0) < 45 * 86400 and PREFIX.match(b["subject"] or "") \
                    and not b["refs"] and not b["in_reply_to"]:     # only a REPLY joins by subject: a new request with the
                                                                    # same subject is a new case
                join(b["mid"], a["mid"])
    out = defaultdict(list)
    for m in mails:
        out[find(m["mid"])].append(m)
    return [sorted(t, key=lambda x: x["date"] or 0) for t in out.values()]


def _money(text):
    m = MONEY.search(text or "")
    if not m:
        return None, None
    cur = (m.group(1) or m.group(4) or "EUR").upper().replace("€", "EUR").replace("$", "USD")
    return _num(m.group(2) or m.group(3)), cur


SYSTEM = re.compile(r"^(tracking|ratedesk|rate-?desk|portal|no-?reply|noreply|bookings?|confirm\w*|mailer-daemon|postmaster|"
                    r"notifications?)@", re.I)


def is_customer(m, ours):
    if m.get("route"):                                            # another clerk's router already decided
        return m["route"] in ("rfq", "follow_up")
    return not is_ours(m["sender"], ours) and m["sender"] not in CARRIERS and not SYSTEM.match(m["sender"])


def case_from_thread(t, ours):
    """One customer conversation -> one case. Carrier-only conversations return None (they are linked by reference)."""
    first = next((m for m in t if is_customer(m, ours) and m.get("route") != "follow_up"), None) or \
        next((m for m in t if is_customer(m, ours)), None)
    if not first:
        return None
    from shared import rfq
    from booking.handlers import classify
    r = rfq.extract_rfq(first["subject"], first["body"])
    try:
        r = rfq.normalize(r)                                      # pickup postcode -> departure airport
    except Exception:
        pass
    text_all = "\n".join("%s\n%s" % (m["subject"], m["body"]) for m in t)
    ours_after = [m for m in t if is_ours(m["sender"], ours) and (m["date"] or 0) >= (first["date"] or 0)]
    quote = next((m for m in ours_after if _money(m["body"])[0]), None)
    price, cur = _money(quote["body"]) if quote else (None, None)
    airline = next((a for a in AIRLINES if quote and a.lower() in quote["body"].lower()), None)
    refs = sorted({x.upper().replace(" ", "") for x in REF.findall(text_all)})
    origin, destination, weight = r.origin, r.destination, r.weight_kg
    if not (origin and destination and weight):                  # answered in a later mail (our clarifying question)
        later = "\n".join(_own(m) for m in t if is_customer(m, ours) and m is not first)
        if later:
            try:
                r2 = rfq.normalize(rfq.extract_rfq(first["subject"], first["body"] + "\n" + later))
                origin, destination, weight = origin or r2.origin, destination or r2.destination, weight or r2.weight_kg
            except Exception:
                pass
    if quote and not (origin and destination):                   # our own quote names the lane: "MUC to PVG", "FRA-ORD"
        lane = LANE.search(quote["body"]) or LANE.search(quote["subject"])
        if lane:
            origin, destination = origin or lane.group(1), destination or lane.group(2)
    if quote and not origin:                                      # "trucking to Cologne airport": our six departure airports
        low = quote["body"].lower()
        hits = sorted((low.find(name), code) for name, code in rfq.CITY_TO_IATA.items()
                      if code in ORIGINS and re.search(r"\b%s\b" % re.escape(name), low))
        origin = hits[0][1] if hits else None
    if quote and not destination:
        m = re.search(r"\(([A-Z]{3})\)", quote["body"])
        destination = m.group(1) if m and m.group(1) not in ORIGINS else None
    if quote and not weight:
        w = re.search(r"(\d[\d.,]*)\s*kg", quote["body"])
        weight = _num(w.group(1)) if w else None
    status = "open" if not quote else "quoted"
    if quote:
        for m in t:
            if m["sender"] == first["sender"] and (m["date"] or 0) > (quote["date"] or 0):
                if status in ("booked", "confirmed") and CANCEL.search(_own(m)):
                    status = "cancelled"                          # "please cancel" after the yes is no "decline"
                    continue
                v = classify(m["body"], m["subject"])
                if status in ("booked", "confirmed", "cancelled"):
                    continue                                       # later mails (thanks, status) do not undo a booking
                status = {"accept": "booked", "sending_docs": "booked", "decline": "lost"}.get(v, status)
    if any(m["sender"] in CARRIERS and CONFIRMED.search(m["subject"] + " " + m["body"][:300]) for m in t) and status in ("booked", "quoted"):
        status = "confirmed"
    bk = next((x for x in refs if x.startswith("BK-")), None)
    if bk and status == "quoted":
        status = "booked"
    return {"key": "mail:" + t[0]["mid"], "customer": first["sender"], "company": first.get("sender_name") or None,
            "subject": first["subject"], "origin": origin, "destination": destination, "weight_kg": weight,
            "volume_cbm": r.volume_cbm, "pieces": r.pieces, "commodity": r.commodity, "pickup_postcode": r.pickup_postcode,
            "ready_date": r.ready_date, "price": price, "currency": cur, "airline": airline, "booking_reference": bk,
            "refs": refs, "status": status, "first_at": t[0]["date"], "last_at": t[-1]["date"], "n_mails": len(t),
            "sources": sorted({m["source"] for m in t}), "mids": [m["mid"] for m in t],
            "quoted_at": quote["date"] if quote else None}


def case_from_row(r):
    st = (r["status"] or "").lower()
    status = ("confirmed" if re.search(r"confirm|bestät|flown|geflogen|delivered|zugestellt|done|closed|abgeschlossen", st)
              else "cancelled" if re.search(r"cancel|storn", st) else "lost" if re.search(r"lost|verloren|declin|abgelehnt", st)
              else "booked" if re.search(r"book|gebucht", st) else "quoted" if r["price"] else "open")
    key = "row:" + hashlib.sha1(json.dumps({k: r[k] for k in ("customer", "company", "origin", "destination", "weight_kg",
                                                                "price", "booking_reference", "date")}, sort_keys=True,
                                           default=str).encode()).hexdigest()[:16]
    return {"key": key, "customer": r["customer"], "company": r["company"], "subject": None, "origin": r["origin"],
            "destination": r["destination"], "weight_kg": r["weight_kg"], "volume_cbm": r["volume_cbm"],
            "pieces": int(r["pieces"]) if r["pieces"] else None, "commodity": r["commodity"], "pickup_postcode": None,
            "ready_date": None, "price": r["price"], "currency": r["currency"] or ("EUR" if r["price"] else None),
            "airline": r["airline"], "booking_reference": r["booking_reference"],
            "refs": [r["booking_reference"].upper()] if r["booking_reference"] else [], "status": status,
            "first_at": r["date"], "last_at": r["date"], "n_mails": 0, "sources": ["%s row %d" % (r["source"], r["row"])], "mids": []}


def link_carrier_threads(ts, cases, ours):
    """Airline confirmations, trucker mails and the like often start their own conversation. Hang each one on the
    case whose reference it names (BK-, GOOGLE-, INV-, AWB); an airline confirmation makes that case `confirmed`."""
    in_case = {mid for k in cases for mid in k["mids"]}
    by_ref = defaultdict(list)
    for k in cases:
        for r in k["refs"]:
            by_ref[r].append(k)
    n = 0
    for t in ts:
        if any(m["mid"] in in_case for m in t):
            continue
        refs = {x.upper().replace(" ", "") for m in t for x in REF.findall(m["subject"] + " " + m["body"])}
        k = next((k for r in sorted(refs, key=lambda x: not x.startswith("GOOGLE-")) for k in by_ref.get(r, [])), None)
        if not k and any(m["sender"] in CARRIERS for m in t):      # no known reference: same lane, a booked case, within 7 days
            text = " ".join(m["subject"] + " " + m["body"] for m in t)
            lanes = {(a, b) for a, b in LANE.findall(text)}
            near = [c for c in cases if (c["origin"], c["destination"]) in lanes and c["status"] in ("booked", "quoted")
                    and 0 <= (t[0]["date"] or 0) - (c["first_at"] or 0) <= 7 * 86400]
            k = near[0] if len(near) == 1 else None                 # only when exactly one case fits
        if not k:
            continue
        n += 1
        k["mids"] += [m["mid"] for m in t]
        k["refs"] = sorted(set(k["refs"]) | refs)
        k["n_mails"] += len(t)
        k["last_at"] = max(k["last_at"] or 0, t[-1]["date"] or 0)
        bk = next((r for r in sorted(refs) if r.startswith("BK-")), None)
        if bk and not k["booking_reference"]:
            k["booking_reference"] = bk
        if any(CONFIRMED.search(m["subject"] + " " + m["body"][:300]) and not CANCEL.search(m["subject"]) for m in t) \
                and k["status"] in ("booked", "quoted"):
            k["status"] = "confirmed"
        if any(CANCEL.search(m["subject"]) for m in t) and k["status"] in ("booked", "confirmed"):
            k["status"] = "cancelled"
    return n


RANK = {"confirmed": 5, "cancelled": 4, "booked": 3, "lost": 2, "quoted": 1, "open": 0}


def _same_shipment(a, b, days=5):
    """Same shipment: a shared reference, or same customer + lane + weight within 3% + dates within `days`."""
    if set(a["refs"]) & set(b["refs"]):
        return True
    who = lambda c: {x for x in ((c["customer"] or "").lower(), (c["company"] or "").lower()) if x}
    if not (who(a) & who(b)) and not ((a["customer"] or "").split("@")[-1] and (a["customer"] or "").split("@")[-1] ==
                                      (b["customer"] or "").split("@")[-1]):
        return False
    if not (a["origin"] and a["origin"] == b["origin"] and a["destination"] == b["destination"]):
        return False
    if not (a["weight_kg"] and b["weight_kg"] and abs(a["weight_kg"] - b["weight_kg"]) <= 0.03 * max(a["weight_kg"], b["weight_kg"])):
        return False
    return abs((a["first_at"] or 0) - (b["first_at"] or 0)) <= days * 86400


def merge_cases(cases):
    """Register row + mail case of one shipment -> one case (the mail one, with the row's facts filled in).
    Two mail cases of one shipment (the customer sent the request again) -> the later one is a duplicate."""
    cases = sorted(cases, key=lambda c: (c["first_at"] or 0, c["key"].startswith("row:")))
    kept, merged, repeats = [], 0, 0
    for c in cases:
        twin = next((k for k in kept if _same_shipment(k, c)), None)
        if twin and (c["key"].startswith("row:") or twin["key"].startswith("row:")):
            for f in ("company", "origin", "destination", "weight_kg", "volume_cbm", "pieces", "commodity", "price", "currency",
                      "airline", "booking_reference"):
                if not twin.get(f) and c.get(f):
                    twin[f] = c[f]
            twin["refs"] = sorted(set(twin["refs"]) | set(c["refs"]))
            twin["sources"] = sorted(set(twin["sources"]) | set(c["sources"]))
            twin["mids"] = twin["mids"] + c["mids"]
            if RANK.get(c["status"], 0) > RANK.get(twin["status"], 0):
                twin["status"] = c["status"]
            merged += 1
            continue
        if twin and twin.get("quoted_at") and (c["first_at"] or 0) > twin["quoted_at"]:
            twin = None                                           # we had answered: a NEW request for the same lane (repeat
                                                                  # business), not the same request sent again
        if twin:                                                  # two conversations, one shipment: the request came twice
            c["duplicate_of"] = twin["key"]
            c["note"] = "same shipment as an earlier request (sent again)"
            repeats += 1
        kept.append(c)
    return kept, merged, repeats


# ------------------------------------------------------------------------------------------------ storing
def run(paths, ours=None, dry=False, quiet=False):
    mails, rows = [], []
    for p in paths:
        m, r = read_any(p)
        mails += m
        rows += r
    n_raw = len(mails)
    mails, dups = dedupe_mails(mails)
    ours = set(ours or []) or guess_ours(mails)
    ts = threads(mails, ours)
    cases = [c for c in (case_from_thread(t, ours) for t in ts) if c]
    carrier_threads = len(ts) - len(cases)
    linked = link_carrier_threads(ts, cases, ours)
    row_cases = [case_from_row(r) for r in rows]
    uniq_rows = {c["key"]: c for c in row_cases}
    cases, merged, repeats = merge_cases(cases + list(uniq_rows.values()))
    linked += link_carrier_threads(ts, cases, ours)                # register rows bring booking numbers: second pass
    report = {"files": len(paths), "mails_read": n_raw, "duplicate_mails": len(dups), "mails_kept": len(mails),
              "conversations": len(ts), "carrier_only_conversations": carrier_threads,
              "carrier_conversations_linked_by_reference": linked, "register_rows": len(rows),
              "register_duplicate_rows": len(row_cases) - len(uniq_rows), "rows_merged_into_mail_cases": merged,
              "requests_sent_twice": repeats, "cases": len(cases), "ours": sorted(ours),
              "by_status": dict(sorted(defaultdict(int, {s: sum(1 for c in cases if c["status"] == s) for s in RANK}).items(),
                                       key=lambda x: -RANK[x[0]]))}
    if not dry:
        c, now = con(), time.time()
        case_of = {mid: k["key"] for k in cases for mid in k["mids"]}
        for m in mails:
            role = "ours" if is_ours(m["sender"], ours) else "carrier" if m["sender"] in CARRIERS or m.get("route") in (
                "carrier_bid", "ratedesk", "booking_confirmation", "tariff", "carrier") else "customer" if is_customer(m, ours) else "system"
            c.execute("INSERT OR IGNORE INTO archive_mails(mid,case_key,date,sender,recipients,subject,body,in_reply_to,refs,files,"
                      "source,role,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (m["mid"], case_of.get(m["mid"]), m["date"], m["sender"], m["recipients"], m["subject"], m["body"],
                       m["in_reply_to"], json.dumps(m["refs"]), json.dumps(m["files"]), m["source"], role, now))
        for m, kept in dups:
            c.execute("INSERT OR IGNORE INTO archive_mails(mid,case_key,date,sender,subject,source,role,duplicate_of,imported_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?)", (m["mid"] or "<dup-%s>" % _fingerprint(m) + m["source"], case_of.get(kept),
                                                    m["date"], m["sender"], m["subject"], m["source"], "duplicate", kept, now))
        for k in cases:
            c.execute("INSERT OR REPLACE INTO archive_cases(key,customer,company,subject,origin,destination,weight_kg,volume_cbm,"
                      "pieces,commodity,pickup_postcode,ready_date,price,currency,airline,booking_reference,refs,status,first_at,"
                      "last_at,n_mails,sources,duplicate_of,note,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (k["key"], k["customer"], k["company"], k["subject"], k["origin"], k["destination"], k["weight_kg"],
                       k["volume_cbm"], k["pieces"], k["commodity"], k["pickup_postcode"], k["ready_date"],
                       None if k["price"] is None else "%.2f" % k["price"], k["currency"], k["airline"], k["booking_reference"],
                       json.dumps(k["refs"]), k["status"], k["first_at"], k["last_at"], k["n_mails"], json.dumps(k["sources"]),
                       k.get("duplicate_of"), k.get("note"), now))
        db.event("history_import", **{x: report[x] for x in report if x != "ours"})
    if not quiet:
        print(json.dumps(report, indent=2))
    return report


def main(argv):
    ours = None
    if "--ours" in argv:
        i = argv.index("--ours")
        ours = [x.strip().lower() for x in argv[i + 1].split(",") if x.strip()]
        argv = argv[:i] + argv[i + 2:]
    dry = "--dry" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        sys.exit(__doc__)
    run(paths, ours, dry)


if __name__ == "__main__":
    main(sys.argv[1:])
