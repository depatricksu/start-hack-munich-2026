"""In-transit problems that carriers describe without the word 'delay': weather, strike, closure, customs hold,
technical problem, diversion, missed connection, damaged or missing cargo. EN + DE, rules only.

A sentence counts only when it says the problem is real. Forecasts, conditions ("if", "may"), all-clears and negations
are left to the normal rules, so the client never gets a false alarm.
"""
import re

from . import rules

HIT = (r"suspend|grounded|closed|closure|halted|standstill|will not|won't|cannot|can't|unable|stuck|missed|pushed back|"
       r"held|on hold|affects|affected|disrupted|prevent|waiting|no departures|nicht|gesperrt|geschlossen|eingestellt|"
       r"hängt|fest|betroffen")
CAUSES = [  # key, type, words, needs an impact word, EN, DE
    ("damaged", "damaged", r"\b(?:is|was|been|arrived|found|got|are|were) (?:badly |partly |slightly )?damaged\b|"
     r"\bcargo damaged\b|\b(?:ist|wurde|wurden|sind) (?:\w+ )?beschädigt", False, "damage to the cargo", "Schaden an der Ware"),
    ("missing", "missing", r"cannot locate|can't locate|unable to locate|\b(?:is|are|went) missing\b|"
     r"\b(?:cargo|shipment|pieces?) (?:is |are |was )?lost\b|nicht auffindbar|vermisst",
     False, "cargo not located", "Ware derzeit nicht auffindbar"),
    ("weather", "delayed", r"weather|storm|snow|\bfog\b|typhoon|hurricane|cyclone|flood|\bice\b|de-icing|volcanic|unwetter|"
     r"sturm|schnee|nebel|gewitter|hochwasser", True, "bad weather", "schlechtes Wetter"),
    ("strike", "delayed", r"\bstrikes?\b|walkout|industrial action|streik", True, "a strike", "ein Streik"),
    ("customs", "delayed", r"customs|\bzoll\b", True, "a customs hold", "Klärung beim Zoll"),
    ("technical", "delayed", r"technical (?:problem|issue|fault)|mechanical|aircraft on ground|technische[rns]? (?:problem|defekt)",
     True, "a technical problem with the aircraft", "ein technisches Problem am Flugzeug"),
    ("closure", "delayed", r"airport|airspace|runway|flughafen|luftraum", True, "a closure at the airport or in the airspace",
     "eine Sperrung am Flughafen oder im Luftraum"),
    ("diverted", "delayed", r"\b(?:was|is|been|being) diverted\b|wurde umgeleitet", False, "a diversion", "eine Umleitung"),
    ("connection", "delayed", r"missed (?:its|the|their) connect|anschluss(?:flug)? verpasst",
     False, "a missed connection", "ein verpasster Anschlussflug"),
]
CAUSES = [(k, t, re.compile(rx, re.I), need, en, de) for k, t, rx, need, en, de in CAUSES]
_HIT = re.compile(r"\b(?:%s)" % HIT, re.I)
_QUIET = re.compile(r"^\W*(?:if|in case|should|falls|sollte)\b|\b(?:may|might|could|possibly|forecast|könnte|eventuell)\b|"
                    r"\bin case of\b|\bdespite\b|\btrotz\b|not (?:be |been )?(?:affected|damaged|delayed)|unaffected|no damage|"
                    r"no impact|nothing (?:is )?missing|nicht (?:betroffen|beschädigt)|reopened|resumed|has been (?:cleared|released)|"
                    r"cleared customs|wieder geöffnet|freigegeben|free of charge", re.I)


def detect(subject, body):
    """-> {'key', 'type', 'en', 'de', 'sentence'} or None."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n\s*\n", rules.own_text(body)) if p.strip()] + [subject or ""]
    live = [re.sub(r"\s+", " ", p) for p in parts if not _QUIET.search(p)]
    for key, typ, rx, needs_hit, en, de in CAUSES:
        for p in live:
            if rx.search(p) and (not needs_hit or _HIT.search(p)):
                return {"key": key, "type": typ, "en": en, "de": de, "sentence": p[:150]}
    return None
