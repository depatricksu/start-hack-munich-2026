"""Several shipments in one customer mail (5U booth: "everything can happen").

handle_rfq calls `handle(tid, mail, fields)` when the LLM form has more than one entry in `shipments`.
Each shipment is checked and priced on its own (sheets + portal), then ONE reply lists every price and one total.
Anything we cannot price safely (door pickup without bids, unknown lane, missing data) -> needs_human, nothing sent.

The session's `chosen` stays one dict (UI and booking read it): airline "A + B", total = sum, source "multi",
plus `parts` = the chosen option per shipment. Booking sends multi accepts to a human for now.
"""
import csv, json, os, re, time
from decimal import Decimal

from core import config, db, mailbox
from pricing import price as sheets
from shared.rfq import Level, from_fields, validate
from llm import extract as llm_extract

_ZONES = os.path.join(config.ROOT, "kit", "start-kit", "pickup_zones.csv")
ZONE_AIRPORT = {r["zone"]: r["airport"] for r in csv.DictReader(open(_ZONES))}

FALLBACK = ("Hello,\n\nthank you for your request. Here are our all-in prices per shipment:\n\n{PRICE_TABLE}\n\n"
            "All-in total: {TOTAL}\n\nIf that works for you, just reply and I'll book everything.\n\nBest regards\n{SIGNER}\nAir Export")
FALLBACK_DE = ("Guten Tag,\n\nvielen Dank für Ihre Anfrage. Hier unsere Gesamtpreise je Sendung:\n\n{PRICE_TABLE}\n\n"
               "Gesamtpreis: {TOTAL}\n\nWenn das passt, antworten Sie einfach kurz und ich buche alles.\n\nViele Grüße\n{SIGNER}\nLuftfracht Export")


def _totals(s):
    pieces = s.get("pieces") or []
    w = s.get("weight_kg") or sum((p.get("count") or 1) * (p.get("kg_each") or 0) for p in pieces)
    v = s.get("volume_cbm") or sum((p.get("count") or 1) * (p.get("l_cm") or 0) * (p.get("w_cm") or 0)
                                   * (p.get("h_cm") or 0) for p in pieces) / 1e6
    return float(w or 0), float(v or 0)


def _options(o, d, w, v, tid, mail_id):
    opts = [dict(x, total_eur=x["total"]) for x in sheets.options(o, d, w, v)]
    try:
        from sourcing import portal
        opts += portal.options(o, d, w, v)
    except Exception as e:                                   # portal down: sheets still work
        db.event("portal_error", tid, mail_id, error=str(e))
    return opts


def price_all(tid, mail, fields):
    """-> (parts, problem). parts = [{shipment, options, best}], problem = reason string or None."""
    parts = []
    for n, s in enumerate(fields.get("shipments") or [], 1):
        s = dict(s)
        pc = str(s.get("pickup_postcode") or "")
        if not s.get("origin") and pc[:2] in ZONE_AIRPORT:
            s["origin"] = ZONE_AIRPORT[pc[:2]]
        s["weight_kg_total"], s["volume_cbm_total"] = _totals(s)
        s.setdefault("prefer", fields.get("prefer"))
        stops = [f"{i.field}: {i.message}" for i in validate(from_fields(s, mail))
                 if i.level in (Level.MISSING, Level.HUMAN) and i.field not in ("message_id", "customer_email")]
        if stops:
            return parts, f"multi_shipment #{n}: " + "; ".join(stops)
        if pc:
            return parts, f"multi_shipment #{n}: door pickup needs a trucker bid"
        o, d = s["origin"].upper(), s["destination"].upper()
        opts = _options(o, d, s["weight_kg_total"], s["volume_cbm_total"], tid, mail["id"])
        if not opts:
            return parts, f"multi_shipment #{n}: no price found for {o}-{d}"
        if (s.get("prefer") or "").lower() == "fastest":
            best = min(opts, key=lambda x: (x["transit_days"], Decimal(x["total_eur"])))
        else:
            best = min(opts, key=lambda x: Decimal(x["total_eur"]))
        parts.append({"shipment": s, "options": opts, "best": best})
    return parts, None


def _line(p):
    s, b = p["shipment"], p["best"]
    return "- %s to %s, %s kg: %s EUR with %s, %s days transit" % (
        b["origin"], b["destination"], ("%g" % s["weight_kg_total"]), b["total_eur"], b["airline"], b["transit_days"])


def handle(tid, mail, fields):
    parts, problem = price_all(tid, mail, fields)
    db.event("multi_options", tid, mail["id"], shipments=len(fields.get("shipments") or []),
             priced=len(parts), problem=problem)
    if problem:
        db.update_session(tid, status="needs_human", note=problem)
        return db.event("needs_human", tid, mail["id"], why=problem)

    total = sum(Decimal(p["best"]["total_eur"]) for p in parts)
    chosen = {"airline": " + ".join(p["best"]["airline"] for p in parts), "total": "%.2f" % total,
              "total_eur": "%.2f" % total, "currency": "EUR",
              "transit_days": max(p["best"]["transit_days"] for p in parts),
              "origin": parts[0]["best"]["origin"], "destination": parts[0]["best"]["destination"],
              "source": "multi", "parts": [p["best"] for p in parts]}
    db.update_session(tid, options=[o for p in parts for o in p["options"]])
    if not db.claim_for_sending(tid):
        return db.event("quote_skipped_already_sent", tid)

    s = db.session(tid)
    # Code-only body (Erik's dry run: the LLM mixed {PRICE}/{AIRLINE} into multi replies). German if the mail was.
    template = FALLBACK_DE if (json.loads(s["fields"] or "{}").get("language") or "").lower() == "de" else FALLBACK
    body = (template.replace("{PRICE_TABLE}", "\n".join(_line(p) for p in parts))
            .replace("{TOTAL}", "%.2f EUR" % total).replace("{SIGNER}", llm_extract.SIGNER))
    if re.search(r"\{[A-Z_]+\}", body):                    # never send a raw placeholder
        db.update_session(tid, status="needs_human", note="reply still had a placeholder, not sent")
        return db.event("needs_human", tid, mail["id"], why="placeholder left in multi reply")
    subject = s["subject"] if s["subject"].lower().startswith("re:") else "Re: " + s["subject"]
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=tid, thread_id=tid)
    now = time.time()
    db.update_session(tid, status="quoted" if ok else "failed", chosen=chosen, reply=body, quoted_at=now)
    db.event("quote_sent" if ok else "quote_failed", tid, chosen=chosen, seconds=round(now - s["received_at"], 1),
             dry_run=config.DRY_RUN)
