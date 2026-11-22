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
    r"stessa (?:spedizione|merce)|richiesta precedente|invariat[io]|mismo env[íi]o|misma (?:carga|mercanc[íi]a)|solicitud anterior|sin cambios|"
    r"same as (?:before|last time|my last|our last|the last)|like last time|as in my last|as per (?:my|our) last|repeat (?:order|shipment)|wie (?:letztes mal|gehabt)", re.I)
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


def find(mail, fields, also_route=False):
    """-> (earlier request dict, why) or (None, why)."""
    text = "%s\n%s" % (mail.get("subject") or "", (mail.get("body") or "").split("\n--- attached file:")[0])
    if not refers(text) and not (also_route and ROUTE.search(text)):
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


ROUTE = re.compile(
    r"same (?:route|lane|destination|origin|pickup|collection|address|site|airport)|(?:route|lane|pickup|collection)(?: details?)? (?:is|are|stays?|remains?)? ?"
    r"(?:unchanged|the same|as before)|gleiche(?:n|r)? (?:strecke|route|relation|ziel|abholung)|m[êe]me (?:trajet|route|destination|enl[èe]vement)|"
    r"stess[ao] (?:tratta|rotta|destinazione|ritiro)|mism[ao] (?:ruta|destino|recogida)", re.I)
UNIT = (r"(?:pallets?|pieces?|cartons?|boxes|box|crates?|colli|collis|packages?|units?|parcels?|skids?|drums?|rolls?|paletten?|st[üu]cke?|kartons?|kisten?|"
        r"palettes?|colis|pezzi|bancali|bultos|cajas)")
MORE = re.compile(r"\b(\d+|\w+)\s+(more|additional|extra|further|fewer|less|mehr|weitere|zus[äa]tzliche|weniger|de plus|de moins|in pi[uù]|in meno|m[áa]s|menos)"
                  r"\s+(?:of the same\s+)?" + UNIT + r"|\b(\d+|\w+)\s+" + UNIT + r"\s+(more|fewer|less|mehr|weniger|de plus|de moins|in pi[uù]|in meno|m[áa]s|menos)\b", re.I)
TIMES = {2.0: r"double|twice|doppelt\w*|zweimal|le double|il doppio|el doble", 0.5: r"half|halb\w*|la moiti[ée]|la met[àa]|la mitad",
         3.0: r"triple|three times|dreifach\w*|dreimal"}
WORDS = {w: n for n, ws in enumerate((("zero",), ("one", "a", "an", "ein", "eine", "un", "une", "uno", "una"), ("two", "zwei", "deux", "due", "dos"),
                                      ("three", "drei", "trois", "tre", "tres"), ("four", "vier", "quatre", "quattro", "cuatro"),
                                      ("five", "f\u00fcnf", "fuenf", "cinq", "cinque", "cinco"), ("six", "sechs", "sei", "seis"),
                                      ("seven", "sieben", "sept", "sette", "siete"), ("eight", "acht", "huit", "otto", "ocho"),
                                      ("nine", "neun", "neuf", "nove", "nueve"), ("ten", "zehn", "dix", "dieci", "diez"),
                                      ("eleven", "elf"), ("twelve", "zw\u00f6lf", "zwoelf"))) for w in ws}
FEWER = ("fewer", "less", "weniger", "de moins", "in meno", "menos")
SAY = {"en": "I have priced it on %g kg and %g cbm: %s.", "de": "Kalkuliert mit %g kg und %g cbm: %s."}
WHY = {"en": {"count": "your earlier shipment of %d pieces, now %d of the same size", "times": "%g times your earlier shipment",
              "weight": "the volume scaled with the new weight"},
       "de": {"count": "Ihre fr\u00fchere Sendung mit %d Packst\u00fccken, jetzt %d gleicher Gr\u00f6\u00dfe", "times": "das %g-Fache Ihrer fr\u00fcheren Sendung",
              "weight": "das Volumen im Verh\u00e4ltnis zum neuen Gewicht"}}


def _count(pieces):
    return sum(int(p.get("count") or 0) for p in pieces or [] if isinstance(p, dict))


def change(text, old_pieces):
    """A change of quantity against the earlier request: -> (factor, kind, old count, new count), or (None, 'unknown', ...)
    when the mail asks for more or fewer pieces but the earlier request has no piece count, or None for no change."""
    m = MORE.search(text)
    if m:
        number, word = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        k = int(number) if number.isdigit() else WORDS.get(number.lower())
        if k is not None:
            n = _count(old_pieces)
            k = -k if word.lower() in FEWER else k
            if n <= 0 or n + k <= 0:
                return None, "unknown", n, None
            return (n + k) / n, "count", n, n + k
    for factor, words in TIMES.items():
        if re.search(r"\b(?:%s)\b[^.!?\n]{0,40}\b(?:quantity|amount|volume|shipment|cargo|goods|menge|quantit[ée]|quantit[àa]|cantidad)|"
                     r"\b(?:quantity|amount|menge|quantit[ée]|quantit[àa]|cantidad)\b[^.!?\n]{0,30}\b(?:%s)\b" % (words, words), text, re.I):
            return factor, "times", _count(old_pieces), None
    return None


def merge(mail, fields):
    """Fills what the new mail leaves out from the earlier request it points to. -> the earlier request, or None.
    The new mail wins wherever it says something itself. Variations (Erik, 22 Nov):
      same shipment, new destination        -> weight, volume and pickup from the earlier request
      same route, new cargo                 -> origin, destination and pickup from the earlier request, cargo from the mail
      same shipment, new weight, no volume  -> the volume scales with the weight
      'two more pallets', 'double'          -> weight and volume scale with the piece count; the quote says the totals
      more pallets, no earlier piece count  -> nothing is guessed: the weight stays open and the customer is asked"""
    text = "%s\n%s" % (mail.get("subject") or "", (mail.get("body") or "").split("\n--- attached file:")[0])
    shipment, route = refers(text), bool(ROUTE.search(text))
    if not shipment and not route:
        return None
    earlier, why = find(mail, fields, also_route=True)
    if not earlier:
        db.event("same_as_earlier", mail["thread_id"], mail["id"], found=False, why=why)
        return None
    old, took = earlier["fields"], {}
    pieces = [p for p in fields.get("pieces") or [] if isinstance(p, dict)]
    own_weight = float(fields.get("weight_kg") or 0) > 0 or any(p.get("kg_each") for p in pieces)
    own_volume = float(fields.get("volume_cbm") or 0) > 0 or any(p.get("l_cm") for p in pieces)
    lang = (fields.get("language") or "en")[:2].lower()
    lang = lang if lang in SAY else "en"
    # the route: whatever the new mail leaves out
    if not fields.get("destination") and old.get("destination"):
        fields["destination"] = took["destination"] = old["destination"]
    if not fields.get("pickup_postcode") and old.get("pickup_postcode") and not fields.get("self_delivery"):
        fields["pickup_postcode"] = took["pickup_postcode"] = old["pickup_postcode"]
    if (not fields.get("origin") or "origin" in (fields.get("filled_by_code") or [])) and old.get("origin"):
        fields["origin"] = took["origin"] = old["origin"]
    for k in ("customer_city",):
        if old.get(k) and not fields.get(k):
            fields[k] = took[k] = old[k]
    # the cargo
    w_old, v_old = float(old.get("weight_kg_total") or 0), float(old.get("volume_cbm_total") or 0)
    if shipment and not own_weight:
        ch = change(text, old.get("pieces"))
        if ch and ch[0] is None:                             # "two more pallets" but we do not know how many there were
            took["quantity"] = "changed, earlier piece count unknown: not guessed"
        else:
            factor = ch[0] if ch else 1.0
            fields["weight_kg"] = took["weight_kg"] = round(w_old * factor, 1)
            if not own_volume:
                fields["volume_cbm"] = took["volume_cbm"] = round(v_old * factor, 2)
            fields["pieces"] = []                            # the totals above are the whole shipment
            if ch:
                because = WHY[lang][ch[1]] % ((ch[2], ch[3]) if ch[1] == "count" else factor)
                fields["recall_note"] = SAY[lang] % (fields["weight_kg"], fields.get("volume_cbm") or 0, because)
                took["scaled"] = {"factor": round(factor, 4), "kind": ch[1], "pieces_before": ch[2], "pieces_now": ch[3]}
            for k in ("commodity", "dg", "dangerous_goods", "self_delivery"):
                if old.get(k) not in (None, "", [], {}) and fields.get(k) in (None, "", [], {}, False):
                    fields[k] = took[k] = old[k]
    elif shipment and own_weight and not own_volume and w_old > 0 and v_old > 0:
        new_w = main_weight(fields)
        if new_w > 0 and abs(new_w - w_old) > 0.05:           # same goods, another weight: the volume moves with it
            fields["volume_cbm"] = took["volume_cbm"] = round(v_old * new_w / w_old, 2)
            fields["recall_note"] = SAY[lang] % (new_w, fields["volume_cbm"], WHY[lang]["weight"])
            took["scaled"] = {"factor": round(new_w / w_old, 4), "kind": "weight"}
        elif new_w > 0:
            fields["volume_cbm"] = took["volume_cbm"] = v_old
    if not took:
        return None
    fields["same_as_thread"] = earlier["thread"]
    db.event("same_as_earlier", mail["thread_id"], mail["id"], found=True, earlier=earlier["thread"], why=why, took=took)
    return earlier


def main_weight(fields):
    pieces = [p for p in fields.get("pieces") or [] if isinstance(p, dict)]
    return float(fields.get("weight_kg") or 0) or sum((p.get("count") or 1) * (p.get("kg_each") or 0) for p in pieces)
