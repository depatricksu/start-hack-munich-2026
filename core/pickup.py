"""Truck pickup wanted, but the pickup place came incomplete: only the town, or only a postcode the model missed.

5U, 22 Nov 11:03 (request 56806, rejected 'too low'): "the fastest air freight option to LIM, including truck pickup
from our warehouse to the airport". No place at all. We asked, the customer answered "Sorry I left out the pickup
location: Cologne, Germany." The model took CGN as the airport and no postcode, so no trucker was asked and the quote
was the flight alone. Same shape before: round 20 and round 131 ("The goods are in Augsburg, Germany"), accepted with
accuracy 28.9 and 33.3 of 45 because the truck was small against the flight.

What the truckers need (asked one of them four ways at 11:07): a 5-digit postcode. A town alone is refused ("To
quote we need: the pickup postcode"). Their price depends only on the first two digits: postcode 50380 and postcode
50000 got the same 178.63 EUR. The kit's pickup_zones.csv names one town per postcode area (50 Cologne, 51 Bergisch
Gladbach, 86 Augsburg ...), so the town gives the area, and the area's first postcode gives the right truck price.

fill() runs before pricing. It only acts when the customer asks for a pickup, gave no postcode, and names the place
in a sentence about the pickup (never a town in a signature, "Best greetings from Regensburg").
"""
import csv, os, re
from . import config, db

_ZONES = os.path.join(config.ROOT, "kit", "start-kit", "pickup_zones.csv")
AREAS = [(r["area"], r["zone"]) for r in csv.DictReader(open(_ZONES))]
ZONES = {zone for _, zone in AREAS}
OTHER_NAMES = {"Cologne": ["Köln", "Koeln"], "Munich": ["München", "Muenchen"], "Munich South": ["München Süd", "Muenchen Sued", "South Munich"],
               "Duesseldorf": ["Düsseldorf", "Dusseldorf"], "Moenchengladbach": ["Mönchengladbach", "Monchengladbach"],
               "Lueneburg": ["Lüneburg", "Luneburg"], "Tuebingen": ["Tübingen", "Tubingen"], "Boeblingen": ["Böblingen", "Boblingen"],
               "Giessen": ["Gießen"], "Frankfurt am Main": ["Frankfurt"], "Hamburg North": ["North Hamburg", "Hamburg Nord"]}
_NAMES = sorted(((n, area, zone) for area, zone in AREAS for n in [area] + OTHER_NAMES.get(area, [])), key=lambda x: -len(x[0]))
WANTS = re.compile(r"pick[- ]?up|collect|truck|abhol|\blkw\b|vorlauf|ex ?works|\bexw\b|ab werk|"
                   r"from our (?:site|warehouse|premises|factory|plant)|alınma|kamyon|픽업|트럭", re.I)
PLACE = re.compile(r"pick[- ]?up|collect\w*|warehouse|\bsite\b|premises|factory|plant\b|goods are|located|location|address|"
                   r"abhol\w*|standort|\blager\b|\bwerk\b|ware (?:steht|liegt|befindet)|alınma|depo|픽업", re.I)
# "We will deliver it to Munich airport (MUC) ourselves" names a town and says pickup: that is no pickup (requests
# 1631, 2822, 7240, all quoted without a truck, two of them with full accuracy).
OWN_DELIVERY = re.compile(r"deliver\w*\b[^.!?\n]{0,70}\b(?:ourselves|ourself|on our own)|(?:bring|drop)\w*\b[^.!?\n]{0,50}\b(?:ourselves|airport)|"
                          r"no (?:pick[- ]?up|collection|truck)\b[^.!?\n]{0,20}(?:needed|required|necessary)|"
                          r"no need to arrange\b[^.!?\n]{0,30}(?:pick[- ]?up|truck|collection)|"
                          r"selbst\b[^.!?\n]{0,30}\b(?:an|ab)?liefer\w*|liefer\w*\b[^.!?\n]{0,40}\bselbst|keine abholung", re.I)
AIRPORT_AFTER = r"(?!\s*(?:\(?[A-Z]{3}\)?\s*)?(?:international\s+)?(?:airport|flughafen))"   # "Munich airport" is where it flies from
POSTCODE = re.compile(r"(?<![\d+/.-])(?:D-)?(\d{5})\b(?![\d/-])")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")


def place(text):
    """(postcode or None, area name, zone) named in a sentence about the pickup; None when there is none."""
    for sentence in SENTENCE.split(text or ""):
        if not PLACE.search(sentence):
            continue
        for m in POSTCODE.finditer(sentence):                    # a postcode of an area we serve: it wins over the town
            if m.group(1)[:2] in ZONES:
                zone = m.group(1)[:2]
                return m.group(1), next(a for a, z in AREAS if z == zone), zone
        for name, area, zone in _NAMES:                          # longest first: "Munich South" before "Munich"
            if re.search(r"(?<![\w-])%s(?![\w-])%s" % (re.escape(name), AIRPORT_AFTER), sentence, re.I):
                return None, area, zone
    return None


def fill(tid, fields):
    """Give the request the pickup postcode it lacks. Returns the postcode set, or None when nothing was to do."""
    if fields.get("pickup_postcode") or fields.get("self_delivery") or len(fields.get("shipments") or []) > 1:
        return None
    s = db.session(tid) or {}
    texts = [(r["body"] or "") for r in db.con().execute(
        "SELECT body FROM mails WHERE thread_id=? AND lower(sender)=? ORDER BY id DESC", (tid, (s.get("customer") or "").lower()))]
    if not any(WANTS.search(t) for t in texts) or any(OWN_DELIVERY.search(t) for t in texts):
        return None
    hit = next((p for p in map(place, texts) if p), None)        # the newest mail first: the answer to our question
    if not hit:
        return None
    postcode, area, zone = hit
    fields["pickup_postcode"] = postcode or zone + "000"         # the area's first postcode: truckers price by the area
    fields.setdefault("filled_by_code", []).append("pickup_postcode")
    if not postcode:
        fields["pickup_area"] = area                             # the customer named the town: say the town, not a postcode
    db.update_session(tid, fields=fields)
    db.event("pickup_place", tid, area=area, zone=zone, postcode=fields["pickup_postcode"], given="postcode" if postcode else "town")
    return fields["pickup_postcode"]
