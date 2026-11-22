"""Which shipment is a carrier mail about?

Order (first hit wins, the method is stored with the update):
  1. thread     the mail answers a mail we already linked to a shipment (or the customer thread itself)
  2. bk         a booking reference BK-... we know
  3. our_ref    our reference GOOGLE-<thread>
  4. awb        an air waybill number we know
  5. flight     the sender is the shipment's airline and names the shipment's current flight
  6. lane       the sender is the shipment's airline and names the lane (FRA-ORD), exactly one active shipment
5 and 6 are fuzzy: only for real status news (not price answers, not [BID-n] replies). Two or more candidates =
no match ("ambiguous"), so a mail is never pinned on the wrong customer; the forwarder gets a note instead.
"""
import re

from . import rules, state

FUZZY_TYPES = ("delayed", "offloaded", "rebooked", "cancelled", "departed", "arrived", "delivered")


def _norm_flight(f):
    return re.sub(r"\s", "", (f or "").upper())


def mail_refs(mail):
    """Mail ids this mail points at: its thread id, in_reply_to and references."""
    raw = mail.get("raw") or {}
    if isinstance(raw, str):
        raw = state.jload(raw, {}) or {}
    ids = [mail.get("thread_id"), raw.get("in_reply_to"), raw.get("parent_id")] + list(raw.get("references") or [])
    out = []
    for i in ids:
        try:
            i = int(i)
        except (TypeError, ValueError):
            continue
        if i != mail.get("id") and i not in out:
            out.append(i)
    return out


def match(con, mail, sender_name=None, sender_kind=None, typ=None):
    """-> (thread_id, method) or (None, reason)."""
    text = "%s\n%s" % (mail.get("subject") or "", rules.own_text(mail.get("body") or ""))
    # 1. thread
    for ref in mail_refs(mail):
        if state.shipment(con, ref):
            return ref, "thread"
        r = state.one(con, "SELECT thread_id FROM shipment_updates WHERE mail_id=? AND thread_id IS NOT NULL", (ref,))
        if r:
            return r["thread_id"], "thread"
    refs = rules.refs_in(text)
    # 2. booking reference
    for bk in refs["bk"]:
        r = state.one(con, "SELECT thread_id FROM shipment_state WHERE UPPER(booking_ref)=?", (bk,))
        if r:
            return r["thread_id"], "bk"
    # 3. our reference GOOGLE-<thread>
    for g in refs["google"]:
        if state.shipment(con, g):
            return g, "our_ref"
    # 4. AWB
    awb = rules.awb_in(text)
    if awb:
        r = state.one(con, "SELECT thread_id FROM shipment_state WHERE awb=?", (awb,))
        if r:
            return r["thread_id"], "awb"
    if refs["bk"] or refs["google"]:
        return None, "unknown_ref"                  # it names a booking we do not have: never guess another one
    if re.search(r"\[bid-\d+\]", (mail.get("subject") or "").lower()) or typ not in FUZZY_TYPES:
        return None, "no_match"
    if sender_kind != "airline" or not sender_name:
        return None, "no_match"
    mine = [s for s in state.active_shipments(con) if (s["airline"] or "").lower() == sender_name.lower()]
    # 5. flight
    named = {_norm_flight(f) for f in rules.flights(text, None) if f}
    named |= {_norm_flight(m.group(1) + m.group(2)) for m in rules._FLIGHT_TOKEN.finditer(text)}
    hits = [s for s in mine if s["flight"] and _norm_flight(s["flight"]) in named]
    if len(hits) == 1:
        return hits[0]["thread_id"], "flight"
    if len(hits) > 1:
        return None, "ambiguous:" + ",".join(str(s["thread_id"]) for s in hits)
    # 6. airline + lane
    lane = rules.lane_in(text)
    if lane:
        hits = [s for s in mine if (s["origin"], s["destination"]) == lane]
        if len(hits) == 1:
            return hits[0]["thread_id"], "lane"
        if len(hits) > 1:
            return None, "ambiguous:" + ",".join(str(s["thread_id"]) for s in hits)
    return None, "no_match"
