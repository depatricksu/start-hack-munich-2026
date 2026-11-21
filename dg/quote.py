"""What an RFQ with dangerous goods (DG) gets from us. Owner: Riky.

5U's hourly change (21 Nov ~17:00): the RFQ mail says "general cargo, non-dangerous", but the attached packing list /
Shipper's Letter of Instruction declares e.g. "Dangerous goods: UN1133, Class 3, Adhesives". Quoting it as general
cargo was rejected with reason `dg_docs_missing`.

Erik's detection reads the attachment and puts what it found in fields["dg"]. This module takes it from there:

    info = dg.read_declaration(text)          # optional helper: UN number, class, name from any text, or None
    best, body, human = dg.apply(best, fields, body)

DG_MODE (env, default "docs") decides, until 5U confirms the rule:
    docs       quote as usual + a short DG paragraph: we name the UN number/class we saw and ask for the
               Shipper's Declaration for Dangerous Goods and the safety data sheet (MSDS) before booking.
    surcharge  the same, plus DG_SURCHARGE_EUR_PER_KG x billed kg (and DG_SURCHARGE_MIN_EUR) on the total.
    human      do not quote: hand to a person (apply() returns human=True with the reason).
    off        do nothing (old behaviour).
Pure functions, no network, no LLM call, no DB: instant and safe to call on every quote.
"""
import os, re
from decimal import Decimal, ROUND_HALF_UP

UN = re.compile(r"\bUN\s?-?(\d{4})\b", re.I)
CLASS = re.compile(r"\b(?:class|klasse|classe|clase)\s*[:.]?\s*(\d(?:\.\d)?)\b", re.I)
NAME_AFTER = re.compile(r"\bUN\s?-?\d{4}\b[\s,;:/-]*(?:(?:class|klasse)\s*[:.]?\s*\d(?:\.\d)?[\s,;:/-]*)?([A-Za-z][A-Za-z ,()-]{2,60})", re.I)
_NO = r"(?:no\b|none\b|nil\b|n/?a\b|not\b|nicht|entf|non\b|false\b|0\b|-|nein\b|keine?\b|nein)"
DECLARES = re.compile(r"(?:dangerous goods|gefahrgut|hazmat|\bdgr\b)\s*[:=][ \t|]*(?=[^\s|])(?!" + _NO + r")"   # table cell 'Dangerous goods: | No'
                      r"|\bUN\s?-?\d{4}\b", re.I)
NOT_DG = re.compile(r"\b(?:non[- ]?dangerous|not dangerous|no dangerous goods|no dg|non[- ]?dg|no dgr|non[- ]?dgr|no hazmat|"
                    r"not hazardous|non[- ]?hazardous|not restricted|not dgr|kein gefahrgut|nicht gef[aä]hrlich)\b", re.I)

# Inherently dangerous commodities (IATA): named in the RFQ with no UN number and no "Dangerous goods:" line.
# 5U's trick (21 Nov): the commodity is DG by nature (spray cans = aerosols UN1950) but nothing is declared,
# and a quote that ignores it is declined. Keep this list TIGHT and high-confidence: a false positive asks
# for DG documents on general cargo and costs the round. Only fires when NOT_DG is absent.
COMMODITY_DG = re.compile(
    r"\b(aerosols?|spray[\s-]?cans?|spray[\s-]?paint|"
    r"lithium[\s-]?(?:ion|metal|batter(?:y|ies)|cells?)|li[\s-]?ion\b|power[\s-]?banks?|"
    r"dry[\s-]?ice|"
    r"gas[\s-]?cylinders?|compressed[\s-]?gas|propane|butane|"
    r"fireworks?|feuerwerk\w*|signal[\s-]?flares?|"
    r"flammable[\s-]?(?:liquids?|gas(?:es)?|solids?|aerosols?)|"
    r"nail[\s-]?polish|perfumes?|colognes?|fragrances?|"
    r"safety[\s-]?matches|cigarette[\s-]?lighters?|lighter[\s-]?(?:gas|fluid|refills?)|"
    r"corrosive (?:liquids?|substances?|chemicals?)|oxidizers?|radioactive (?:material|sources?)|explosives (?:for|as)|"
    r"spraydosen?|druckgas\w*|trockeneis|"
    # red-team #47 (issues #64-#68): perfume without the word, solvent paint, German words, sanitizer, wet batteries
    r"eau[\s-]de[\s-](?:parfum|toilette|cologne)|parf[üu]m\w*|nagellack\w*|feuerzeug\w*|lighters|"
    r"solvent[\s-]?based(?:\s+\w+){0,2}\s+(?:paints?|inks?|coatings?|lacquers?|varnish(?:es)?|adhesives?)|"
    r"(?:farbe|farben|lack|lacke)\s+auf\s+l[öo]se?mittelbasis|l[öo]se?mittelhaltig\w*|flash[\s-]?point|"
    r"hand[\s-]?saniti[sz]er\w*|desinfektionsmittel\w*|\d{2,3}\s?%\s*(?:alcohol|ethanol|alkohol)|"
    r"batter(?:y|ies),?\s+wet|wet[\s-]+(?:cell\s+)?batter(?:y|ies)|lead[\s-]?acid|filled\s+with\s+acid|car\s+batter(?:y|ies))\b", re.I)
# A confident UN/class for the common ones, keyed by a substring of the match, for a precise description.
COMMODITY_UN = (
    ("wet", ("UN2794", "8", "batteries, wet, filled with acid")), ("acid", ("UN2794", "8", "batteries, wet, filled with acid")),
    ("car batter", ("UN2794", "8", "batteries, wet, filled with acid")),
    ("eau de", ("UN1266", "3", "perfumery products")), ("parf", ("UN1266", "3", "perfumery products")),
    ("perfume", ("UN1266", "3", "perfumery products")), ("nail polish", ("UN1263", "3", "paint")),
    ("nagellack", ("UN1263", "3", "paint")), ("solvent", ("UN1263", "3", "paint")), ("mittel", ("UN1263", "3", "paint")),
    ("flash", ("UN1263", "3", "paint")), ("lighter", ("UN1057", "2.1", "lighters")), ("feuerzeug", ("UN1057", "2.1", "lighters")),
    ("saniti", ("UN1170", "3", "ethanol solution")), ("alcohol", ("UN1170", "3", "ethanol solution")),
    ("ethanol", ("UN1170", "3", "ethanol solution")), ("alkohol", ("UN1170", "3", "ethanol solution")),
    ("aerosol", ("UN1950", "2.1", "aerosols")), ("spray", ("UN1950", "2.1", "aerosols")),
    ("lithium", ("UN3481", "9", "lithium batteries")), ("li-ion", ("UN3481", "9", "lithium batteries")),
    ("li ion", ("UN3481", "9", "lithium batteries")), ("power bank", ("UN3481", "9", "lithium batteries")),
    ("dry ice", ("UN1845", "9", "dry ice")), ("fireworks", ("UN0336", "1.4", "fireworks")),
    ("spraydose", ("UN1950", "2.1", "aerosols")), ("akku", ("UN3481", "9", "lithium batteries")),
    ("batterie", ("UN3481", "9", "lithium batteries")), ("lithium-ionen", ("UN3481", "9", "lithium batteries")),
    ("trockeneis", ("UN1845", "9", "dry ice")), ("feuerwerk", ("UN0336", "1.4", "fireworks")),
)


# DG by nature, whatever the customer claims. 5U's trap (request 2533, 21 Nov): "maintenance spray cans ... The goods
# are general cargo, non-dangerous" -> customer declined: "these goods are dangerous goods and you quoted without asking
# us for the dangerous goods documents". So for these the "non-dangerous" claim must NOT block the DG paragraph (Riky).
INHERENT_DG = re.compile(r"\b(aerosols?|spray[\s-]?cans?|spray[\s-]?paint|spraydosen?|"
                         r"lithium[\s-]?(?:ion|metal|batter(?:y|ies)|cells?)|lithium\w*(?:akku|batterie)\w*|lithium-ionen\w*|"
                         r"li[\s-]?ion\b|li-ion-akku\w*|power[\s-]?banks?|dry[\s-]?ice|trockeneis|gas[\s-]?cylinders?|"
                         r"compressed[\s-]?gas|druckgas\w*|fireworks?|feuerwerk\w*)", re.I)


COMPANY = re.compile(r"\b(?:gmbh|ltd|limited|inc|llc|corp|s\.r\.l|b\.v|media|group|holding)\b|\bag$|& co\b", re.I)   # not 'kg', not 'AG' mid-text
NEGATED = re.compile(r"\b(?:no|not|without|zero|non|free of|excluding|except|kein\w*|ohne)\b[^.;:\n]*$", re.I)   # clause back to sentence start
FREE_AFTER = re.compile(r"^\s*-?\s*free\b|^[^.\n]{0,25}\b(?:empty|unfilled|dummy|replica|toy)\b", re.I)
ACCESSORY_BEFORE = re.compile(r"\b(?:empty|caps?|lids?|cases?|covers?|chargers?|packaging|boxes|holders?|bags?|labels?|"
                              r"stands?|mounts?|for)\s+(?:\w+\s+){0,2}$", re.I)   # 'caps for aerosol cans', 'cases for power banks'
ACCESSORY_AFTER = re.compile(r"^\s*(?:(?:bottles?|cans?|flasks?)\s+)?(?:packaging|labels?|holders?|cases?|caps?|lids?|chargers?|pumps?|atomi[sz]ers?|stoppers?)\b", re.I)   # "perfume bottle caps, plastic" is not DG (#69)


def _cargo_text(text):
    """The mail without its signature block and company lines ('Fireworks Media GmbH' is not cargo)."""
    lines = (text or "").splitlines()
    for i in range(len(lines) - 1, max(-1, len(lines) - 8), -1):        # cut from the closing line downwards
        if re.fullmatch(r"\s*(?:best|kind|warm|many)?\s*(?:regards|greetings|wishes|thanks|thank you|cheers|danke|"
                        r"(?:\w+\s+)?(?:grüße|grüßen|gruesse|grüsse|gruß|gruss)|cordiali saluti|saludos|sincerely)[ ,.!/a-zA-Z]*",
                        lines[i], re.I):
            lines = lines[:i]
            break
    return "\n".join(l for l in lines if not COMPANY.search(l))


def _first_real(rx, text):
    """First match of rx that is not negated ('no lithium batteries'), not '-free' and not 'empty ... bottles'."""
    for m in rx.finditer(text):
        before, after = text[max(0, m.start() - 120):m.start()], text[m.end():m.end() + 30]
        before = re.split(r"[.!?\n]", before)[-1]          # only this sentence
        if NEGATED.search(before) or FREE_AFTER.search(after) or ACCESSORY_BEFORE.search(before) \
                or ACCESSORY_AFTER.search(after) or re.search(r"\(no batter", after, re.I):
            continue
        return m
    return None


def infer_commodity_dg(text):
    """A DG dict inferred from a commodity name (no UN number declared), or None.
    Only the cargo text counts (no signature, no company lines). A negated or '-free' or 'empty' mention is not DG
    (Kai's false positives). Inherently dangerous goods (aerosols, lithium batteries, dry ice, gas cylinders,
    fireworks) count even when the mail CLAIMS "non-dangerous" (5U's trap, request 2533); the softer words
    (perfume, flammable...) still yield to that claim."""
    if not text:
        return None
    cargo = _cargo_text(text)
    # "Cologne, Germany" is one of our six departure cities, not a perfume: round 72 (automotive sensors, pickup in
    # Cologne) went out with a dangerous goods paragraph. The city has a capital C; "eau de Cologne" stays a match.
    cargo = re.sub(r"(?<![Ee]au de )(?<![Ee]au-de-)\bCologne\b", " ", cargo)
    m = _first_real(INHERENT_DG, cargo) or (None if NOT_DG.search(cargo) else _first_real(COMMODITY_DG, cargo))
    if not m:
        return None
    hit = m.group(0).lower().replace("-", " ")
    for key, (un, cls, name) in COMMODITY_UN:
        if key in hit:
            return {"un": un, "class": cls, "name": name, "inferred": True}
    return {"un": None, "class": None, "name": m.group(1).lower(), "inferred": True}


def mode():
    m = os.environ.get("DG_MODE", "docs").strip().lower()
    return m if m in ("docs", "surcharge", "human", "off") else "docs"


def read_declaration(text):
    """Find a DG declaration in any text (attachment or mail). Returns {"un", "class", "name"} or None.
    A UN number is proof. Without one, an explicit 'Dangerous goods: <something>' line counts; a plain
    'non-dangerous' with no UN number does not."""
    if not text:
        return None
    un = UN.search(text)
    if not un and (NOT_DG.search(text) or not DECLARES.search(text)):
        return infer_commodity_dg(text)     # no UN, no declaration: maybe the commodity itself is DG (aerosols, lithium...)
    cls = CLASS.search(text)
    name = NAME_AFTER.search(text) if un else None
    clean = None
    if name:
        clean = re.split(r"\s{2,}|\b(?:class|klasse|packing|pg|net|gross|qty)\b", name.group(1), flags=re.I)[0]
        clean = clean.strip(" ,;:-()") or None
    return {"un": "UN" + un.group(1) if un else None, "class": cls.group(1) if cls else None, "name": clean}


def describe(info):
    """'UN1133, class 3, adhesives' (or 'aerosols', or 'dangerous goods') from whatever we know. No nested brackets."""
    parts = [p for p in (info.get("un"), "class " + info["class"] if info.get("class") else None,
                         (info.get("name") or "").strip().lower() or None) if p]
    return ", ".join(parts) or "dangerous goods"


PARAGRAPH = {
    "en": ("One thing to note: this shipment contains dangerous goods ({what}). We can fly it as "
           "dangerous goods. Could you please send us the dangerous goods documents: the Shipper's Declaration for "
           "Dangerous Goods and the safety data sheet (MSDS)? We need them to confirm the booking."),
    "de": ("Ein Hinweis: Diese Sendung enthält Gefahrgut ({what}). Wir können die Sendung "
           "als Gefahrgut befördern. Könnten Sie uns bitte die Gefahrgutdokumente senden: die Shipper's Declaration "
           "for Dangerous Goods und das Sicherheitsdatenblatt (MSDS)? Wir benötigen sie für die Buchung."),
    "it": ("Una nota: questa spedizione contiene merce pericolosa ({what}). Possiamo trasportarla come "
           "merce pericolosa. Potrebbe inviarci i documenti per merci pericolose: la Shipper's Declaration for "
           "Dangerous Goods e la scheda di sicurezza (MSDS)? Ci servono per confermare la prenotazione."),
    "fr": ("Une remarque : cet envoi contient des marchandises dangereuses ({what}). Nous pouvons "
           "les transporter en tant que telles. Pourriez-vous nous envoyer les documents marchandises dangereuses : la "
           "Shipper's Declaration for Dangerous Goods et la fiche de données de sécurité (MSDS) ? Nous en avons besoin "
           "pour confirmer la réservation."),
    "es": ("Una nota: este envío contiene mercancía peligrosa ({what}). Podemos transportarla como "
           "mercancía peligrosa. ¿Podría enviarnos los documentos de mercancía peligrosa: la Shipper's Declaration for "
           "Dangerous Goods y la hoja de datos de seguridad (MSDS)? Los necesitamos para confirmar la reserva."),
}


def _money(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def surcharge_eur(best):
    """DG surcharge for the 'surcharge' mode: per kg of billed weight, at least the minimum. 0 if not configured."""
    per_kg = Decimal(os.environ.get("DG_SURCHARGE_EUR_PER_KG", "0") or "0")
    minimum = Decimal(os.environ.get("DG_SURCHARGE_MIN_EUR", "0") or "0")
    kg = Decimal(str(best.get("billed_kg") or best.get("chargeable_kg") or 0))
    return _money(max(per_kg * kg, minimum))


def _insert_before_signoff(body, paragraph):
    """Put our paragraph right before a short closing line in the last 6 lines ('Best regards', 'Best wishes',
    'Mit freundlichen Grüßen'...), with exactly one blank line on each side; else before a short signature block;
    else at the end. A sentence that merely starts with 'Best' in the text is never taken for the closing."""
    lines = body.rstrip().split("\n")
    for i in range(len(lines) - 1, max(-1, len(lines) - 7), -1):
        l = lines[i].strip()
        if len(l) <= 40 and re.fullmatch(r"(?:best|kind|warm|many|with)?\s*(?:regards|wishes|greetings|cheers|thanks|best|"
                                         r"mit freundlichen grüßen|(?:\w+ )?grüße|(?:\w+ )?gruesse|cordiali saluti|"
                                         r"saluti|cordialement|bien à vous|saludos|atentamente)\s*[,.!]?", l, re.I):
            return "\n".join(lines[:i]).rstrip() + "\n\n" + paragraph + "\n\n" + "\n".join(lines[i:]).lstrip("\n")
    blocks = body.rstrip().split("\n\n")
    if len(blocks) > 1 and len(blocks[-1].strip().splitlines()) <= 3 and not re.search(r"[.!?:]\s*$", blocks[-1].strip()):
        return "\n\n".join(blocks[:-1]).rstrip() + "\n\n" + paragraph + "\n\n" + blocks[-1].strip()
    return body.rstrip() + "\n\n" + paragraph


def apply(best, fields, body):
    """Returns (best, body, human). human is None, or the reason to hand the request to a person.
    Does nothing unless fields["dg"] says DG was declared (a dict from Erik's detection, or True)."""
    info = fields.get("dg")
    if not info or mode() == "off":
        return best, body, None
    if info is True:
        info = {}
    if mode() == "human":
        return best, body, "dangerous goods declared: " + describe(info)
    if mode() == "surcharge":
        extra = surcharge_eur(best)
        if extra > 0 and (best.get("total_eur") or best.get("total")):   # no total -> no surcharge, never a crash
            old = _money(best.get("total_eur") or best.get("total"))
            best = dict(best, dg_surcharge_eur=str(extra), total_eur=str(old + extra))
            if best.get("currency", "EUR") == "EUR":
                best["total"] = best["total_eur"]
            for s in {str(old), f"{old:,.2f}", f"{old:.2f}".replace(".", ",")}:
                body = body.replace(s, str(_money(best["total_eur"])))
    lang = (fields.get("language") or "en")[:2].lower()
    paragraph = PARAGRAPH.get(lang, PARAGRAPH["en"]).format(what=describe(info))
    return best, _insert_before_signoff(body, paragraph), None
