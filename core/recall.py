"""'Quote the same shipment as in my earlier request': the details come from that earlier request.

5U, 22 Nov 02:20 (round 103, thr 30354): "Could you please quote the same shipment as in my earlier request, "Air
freight quote request: STR to MEL", sent on 2026-11-21 at 23:18 UTC for destination MEL? The cargo and pickup details
are unchanged, and you already have them from that request. The new destination is LAX, ready 2026-11-29, cheapest."
The clerk found no weight, asked the customer for it, and crashed on the answer. The earlier request was in our own
database: same sender, that subject, received 23:18 UTC: 1841 kg, 4.63 cbm, delivered to STR by the customer.

Code only, no gateway call. Used only when the new mail points to an earlier request AND gives no weight of its own.
The earlier request must come from the SAME sender. It is picked by the subject the customer quotes, the time they
name and the destination they name; with none of these, the sender's most recent request.
"""
import calendar
import json
import re

from core import db

REFERS = re.compile(
    r"same (?:shipment|cargo|goods|consignment|freight)|(?:earlier|previous|prior|last|recent) (?:request|enquiry|inquiry|rfq|quote request)|"
    r"details are (?:unchanged|the same)|you already have (?:them|the details|these)|as (?:before|last time)\b|"
    r"gleiche(?:n)? (?:sendung|ware|fracht)|(?:fr[üu]here|vorherige|letzte)n? anfrage|unver[äa]ndert|wie (?:zuvor|beim letzten mal)|"
    r"m[êe]me (?:envoi|exp[ée]dition|marchandise)|demande (?:pr[ée]c[ée]dente|ant[ée]rieure)|inchang[ée]|"
    r"stessa (?:spedizione|merce)|richiesta precedente|invariat[io]|mismo env[íi]o|misma (?:carga|mercanc[íi]a)|solicitud anterior|sin cambios", re.I)
QUOTED = re.compile(r"[\"“”„«]([^\"“”„«»\n]{6,140})[\"“”»]")
SENT = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:\s*(?:at|um|à|alle|a las)?\s*|T)(\d{1,2})[:.h](\d{2})(?:\s*(UTC|GMT|Z))?", re.I)
IATA = re.compile(r"\b([A-Z]{3})\b")
KEEP = ("pickup_postcode", "customer_city", "commodity", "dg", "dangerous_goods", "self_delivery")


def refers(text):
    return bool(REFERS.search(text or ""))


def _earlier(sender, tid):
    """The sender's earlier requests that we could read, newest first."""
    out = []
    for r in db.con().execute("SELECT s.thread_id, s.fields, s.received_at, m.subject, m.body FROM sessions s JOIN mails m ON m.id = s.thread_id "
                              "WHERE s.customer=? AND s.thread_id!=? ORDER BY s.received_at DESC", (sender, tid)).fetchall():
        try:
            f = json.loads(r["fields"] or "{}")
        except ValueError:
            continue
        if float(f.get("weight_kg_total") or 0) > 0 and not f.get("shipments"):
            out.append({"thread": r["thread_id"], "fields": f, "received_at": r["received_at"], "subject": r["subject"] or ""})
    return out


def find(mail, fields):
    """-> (earlier request dict, why) or (None, why)."""
    text = "%s\n%s" % (mail.get("subject") or "", (mail.get("body") or "").split("\n--- attached file:")[0])
    if not refers(text):
        return None, "the mail does not point to an earlier request"
    earlier = _earlier(mail.get("sender") or mail.get("from") or "", mail["thread_id"])
    if not earlier:
        return None, "no earlier request from this sender"
    quoted = [q.strip().lower() for q in QUOTED.findall(text)]
    times = []
    for y, mo, d, h, mi, zone in SENT.findall(text):
        if zone:                                             # only a time with a stated zone is compared
            times.append(calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), 0)))
    new_dest = (fields.get("destination") or "").upper()
    named = {c for c in IATA.findall(text)} - {new_dest}
    best, best_score, why = None, 0, ""
    for e in earlier:
        score, hits = 0, []
        subj = re.sub(r"^(?:re|aw|fwd?|wg)\s*:\s*", "", e["subject"].strip().lower())
        if subj and any(q == subj or (len(q) >= 12 and (q in subj or subj in q)) for q in quoted):
            score += 4
            hits.append("subject")
        if any(abs(t - e["received_at"]) <= 180 for t in times):
            score += 4
            hits.append("time")
        if (e["fields"].get("destination") or "").upper() in named:
            score += 1
            hits.append("destination")
        if score > best_score:
            best, best_score, why = e, score, "+".join(hits)
    if best:
        return best, "matched by " + why
    if quoted or times:
        return None, "the earlier request the customer names is not in our records"
    return earlier[0], "most recent request of this sender (no subject, time or destination named)"


def merge(mail, fields):
    """Fills weight, volume and the pickup details from the earlier request. -> the earlier request, or None.
    The new mail wins wherever it says something itself (destination, ready date, cheapest/fastest)."""
    if float(fields.get("weight_kg") or 0) > 0 or any(isinstance(p, dict) and p.get("kg_each") for p in fields.get("pieces") or []):
        return None                                          # the new mail carries its own weight: nothing to recall
    earlier, why = find(mail, fields)
    if not earlier:
        if refers("%s\n%s" % (mail.get("subject") or "", mail.get("body") or "")):
            db.event("same_as_earlier", mail["thread_id"], mail["id"], found=False, why=why)
        return None
    old = earlier["fields"]
    fields["weight_kg"], fields["volume_cbm"] = old["weight_kg_total"], old.get("volume_cbm_total") or 0
    fields["pieces"] = []                                    # the totals above are the whole shipment
    took = {"weight_kg": fields["weight_kg"], "volume_cbm": fields["volume_cbm"]}
    for k in KEEP:
        if old.get(k) not in (None, "", [], {}) and fields.get(k) in (None, "", [], {}, False):
            fields[k] = took[k] = old[k]
    if not fields.get("origin") or "origin" in (fields.get("filled_by_code") or []):
        if old.get("origin"):
            fields["origin"] = took["origin"] = old["origin"]
    fields["same_as_thread"] = earlier["thread"]
    db.event("same_as_earlier", mail["thread_id"], mail["id"], found=True, earlier=earlier["thread"], why=why, took=took)
    return earlier
