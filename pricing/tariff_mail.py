"""Airline tariff mails -> live price update (route "tariff", sender is an airline in the carrier list).

5U: "the airlines also send monthly tariffs" and "the setup changes about once an hour". So a tariff mail may
change prices we quote right now. This handler:
  1. takes every attachment (inline content_base64, or downloaded from the mailbox API); no attachment -> the body
  2. parses it with pricing/parse_tariffs.py (xlsx, pdf, docx, txt). Images -> needs a human (no OCR, no LLM)
  3. checks it: lanes found, no missing fields, rates fall with weight, valid today, same airline as the sender
  4. swaps that airline's lanes in pricing.price immediately (no restart) and keeps a copy in data/
Anything doubtful is NOT applied: old prices stay, an event `tariff_rejected` tells the UI why.
"""
import base64, datetime as dt, os, re, urllib.parse, urllib.request

from core import config, db
from pricing import parse_tariffs, price

INBOX = os.path.join(os.path.dirname(os.path.abspath(config.DB_PATH)), "tariffs_in")
PARSEABLE = ("xlsx", "pdf", "docx", "txt")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def _download(mail_id, att):
    """Raw bytes of one attachment."""
    if att.get("content_base64"):
        return base64.b64decode(att["content_base64"])
    att_id = att.get("id") or att.get("attachment_id")
    url = "%s/v1/mailbox/messages/%s/attachments/%s" % (config.BASE_URL, mail_id, urllib.parse.quote(str(att_id)))
    req = urllib.request.Request(url, headers={"X-API-Key": config.API_KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _save(mail, name, data):
    os.makedirs(INBOX, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(name or "tariff.txt"))
    path = os.path.join(INBOX, "%s_%s" % (mail["id"], safe))
    with open(path, "wb") as f:
        f.write(data)
    return path


def _date(s):
    s = str(s).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(s[:19] if " " in s and ":" in s else s.split()[0], fmt).date()
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


def validity(path):
    """(valid_from, valid_to) read from the sheet header, None if not found."""
    got = {}
    for row in parse_tariffs.load_rows(path)[:12]:
        cells = [str(c) for c in row if str(c).strip()]
        text = " ".join(cells)
        for key in ("from", "to"):
            m = re.match(r"valid\s+%s\s*:?\s*(.+)" % key, text, re.I)
            if m:
                got[key] = _date(cells[1] if len(cells) > 1 else m.group(1))
    return got.get("from"), got.get("to")


def currency(path):
    """The sheet's currency from its header ('Currency  USD') or its price cells; None if it does not say."""
    for row in parse_tariffs.load_rows(path)[:40]:
        text = " ".join(str(c) for c in row if str(c).strip())
        m = re.match(r"currency\s*:?\s*([A-Z]{3})\b", text, re.I)
        if m:
            return m.group(1).upper()
        m = re.search(r"\b(USD|GBP|CHF|CNY|JPY)\s*\d|\$\s*\d", text)
        if m:
            return (m.group(1) or "USD").upper()
    return None


def check(records, sender_airline, path, today=None):
    """-> list of problems; empty means safe to apply."""
    today = today or dt.date.today()
    if not records:
        return ["no lanes found in %s" % os.path.basename(path)]
    cur = currency(path)
    if cur and cur != "EUR":                                 # the parser stores every price as EUR: never relabel USD
        return ["prices in %s, not EUR (a human converts, nothing applied)" % cur]
    problems = parse_tariffs.check(records)
    names = {r["airline"] for r in records}
    if len(names) != 1:
        problems.append("several airlines in one sheet: %s" % sorted(names))
    elif sender_airline and next(iter(names)).lower() != sender_airline.lower():
        problems.append("sheet is from %s but mail is from %s" % (next(iter(names)), sender_airline))
    vf, vt = validity(path)
    if vf and vf > today:
        problems.append("valid only from %s (keep current prices until then)" % vf)
    if vt and vt < today:
        problems.append("expired on %s" % vt)
    for r in records:
        if r["origin"] not in {"FRA", "MUC", "DUS", "HAM", "STR", "CGN"}:
            problems.append("%s-%s: origin is not one of our airports" % (r["origin"], r["destination"]))
    return problems


def _diff(airline, new):
    old = {(r["origin"], r["destination"]): r for r in price.lanes_of(airline)}
    nw = {(r["origin"], r["destination"]): r for r in new}
    changed = [k for k in nw if k in old and (old[k]["rates_per_kg"], old[k]["min_charge"], old[k]["fuel_per_kg"],
                                              old[k]["security_per_kg"], old[k]["transit_days"]) !=
               (nw[k]["rates_per_kg"], nw[k]["min_charge"], nw[k]["fuel_per_kg"], nw[k]["security_per_kg"],
                nw[k]["transit_days"])]
    return {"added": ["%s-%s" % k for k in nw if k not in old], "removed": ["%s-%s" % k for k in old if k not in nw],
            "changed": ["%s-%s" % k for k in changed]}


def _sender_airline(sender):
    from booking.handlers import AIRLINE_EMAIL                 # name.lower() -> email, from carrier-list.csv
    for name, email in AIRLINE_EMAIL.items():
        if email.lower() == sender.lower():
            return name
    return None


def handle(mail):
    tid = mail["thread_id"]
    sender_airline = _sender_airline(mail["sender"])
    files = []
    for att in mail["attachments"]:
        name = att.get("filename") or att.get("name") or "attachment"
        try:
            files.append(_save(mail, name, _download(mail["id"], att)))
        except Exception as e:
            db.event("tariff_rejected", tid, mail["id"], file=name, why="download failed: %s" % e)
    if not mail["attachments"] and mail["body"].strip():
        files.append(_save(mail, "body.txt", mail["body"].encode()))

    applied = 0
    for path in files:
        ext = path.rsplit(".", 1)[-1].lower()
        if ext not in PARSEABLE:
            db.event("tariff_rejected", tid, mail["id"], file=os.path.basename(path), airline=sender_airline,
                     why="format .%s needs a human (no OCR)" % ext)
            continue
        try:
            records = parse_tariffs.parse_file(path)
        except Exception as e:
            db.event("tariff_rejected", tid, mail["id"], file=os.path.basename(path), why="parse error: %s" % e)
            continue
        problems = check(records, sender_airline, path)
        if problems:
            db.event("tariff_rejected", tid, mail["id"], file=os.path.basename(path), airline=sender_airline,
                     lanes=len(records), why=problems[:10])
            continue
        airline = records[0]["airline"]
        current = price.lanes_of(airline)
        partial = bool(current) and len(records) * 2 < len(current)
        if partial:                                          # "new rates for FRA-ORD": update those lanes, keep the rest
            new = {(r["origin"], r["destination"]) for r in records}
            records = [r for r in current if (r["origin"], r["destination"]) not in new] + records
        diff = _diff(airline, records)
        price.replace_airline(airline, records)
        applied += 1
        db.event("tariff_loaded", tid, mail["id"], airline=airline, file=os.path.basename(path), lanes=len(records),
                 partial=partial, **diff)
    if not applied:
        db.event("tariff_not_applied", tid, mail["id"], airline=sender_airline, files=len(files))
