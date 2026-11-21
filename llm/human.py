"""A personal touch in every quote mail, and learning which kind of touch wins the jury's +10 "most human" pick.

Code only, $0, no extra gateway call. The touch is one short line (or a regional greeting) built from facts we
really have: where the customer is (their city from the mail, the pickup postcode zone, or the origin airport),
where the cargo goes, and when they wrote. No numbers, no promises, so it passes llm/quality.py.

Styles (the arms of the experiment):
    control      no touch (the mail as before)
    city         a warm line to the customer's city with a local nod ("Grüße nach Köln: der Dom bleibt stehen, ...")
    destination  a nod to where the cargo goes ("Next stop for your cargo: the Windy City.")
    moment       when they wrote ("Saturday evening, but your request didn't have to wait.")
    local        regional greeting (Moin / Servus / Grüß Gott) + the city line
    mirror       the customer wrote something personal: we answer THAT (see mirror() below). Not sampled:
                 it is used whenever they did, and counted like the others so the report shows if it wins.

Learning: the public board (GET /v1/board) has a `human` count per team. When ours goes up, the quotes we sent
since the last check share the win; a quote that sees no win within LEARN_WINDOW_S counts as a loss. Each style
keeps Beta(wins+1, losses+1) and the next quote picks a style by Thompson sampling, so winners get used more
while the others still get tried. State: data/human_learn.json. Look at it: `python3 -m llm.human`.
Only the live runner (DRY_RUN=0) records and learns; everyone else just renders.
"""
import csv, hashlib, json, os, random, re, threading, time, urllib.request, zlib
from datetime import datetime, timedelta, timezone

from core import config

STYLES = ("control", "city", "destination", "moment", "local", "mirror")
# v2: the first file also collected fake quotes from the test suite (core.restart runs it on the runner)
STATE = os.path.join(config.ROOT, "data", "human_learn_v2.json")
TEAM = os.environ.get("TEAM_NAME", "Google")
LEARN_WINDOW_S = float(os.environ.get("HUMAN_LEARN_WINDOW_S", "1800"))   # the jury may judge a round late
POLL_S = float(os.environ.get("HUMAN_POLL_S", "60"))
HUMAN_STYLE = os.environ.get("HUMAN_STYLE", "").strip().lower()         # force one style (tests, or once we know)

# ---------------------------------------------------------------------------------------------------- where

_UML = {"Duesseldorf": "Düsseldorf", "Moenchengladbach": "Mönchengladbach", "Lueneburg": "Lüneburg",
        "Tuebingen": "Tübingen", "Boeblingen": "Böblingen", "Giessen": "Gießen", "Munich South": "Munich",
        "Hamburg North": "Hamburg"}
try:
    _ZONES = {r["zone"]: _UML.get(r["area"], r["area"])
              for r in csv.DictReader(open(os.path.join(config.ROOT, "kit", "start-kit", "pickup_zones.csv")))}
except OSError:
    _ZONES = {}
_AIRPORT_CITY = {"FRA": "Frankfurt", "MUC": "Munich", "DUS": "Düsseldorf", "HAM": "Hamburg", "STR": "Stuttgart",
                 "CGN": "Cologne"}
_DE_NAME = {"Munich": "München", "Cologne": "Köln", "Frankfurt am Main": "Frankfurt", "Nuremberg": "Nürnberg"}
_EN_NAME = {"München": "Munich", "Köln": "Cologne", "Frankfurt am Main": "Frankfurt", "Nürnberg": "Nuremberg"}

NORTH = {"Hamburg", "Bremen", "Kiel", "Lüneburg", "Hannover", "Lübeck", "Rostock", "Oldenburg"}
BAVARIA = {"Munich", "Landshut", "Ingolstadt", "Augsburg", "Regensburg", "Nuremberg", "Würzburg", "Passau"}
SWABIA = {"Stuttgart", "Böblingen", "Tübingen", "Esslingen", "Ulm", "Reutlingen", "Heilbronn"}


def customer_city(fields):
    """The customer's city in English spelling, or None. Their own words first, then postcode zone, then airport."""
    c = (fields.get("customer_city") or "").strip()
    if c and c.lower() not in ("null", "none", "unknown") and len(c) <= 30 and not re.search(r"\d", c):
        return _EN_NAME.get(c, c)
    pc = re.sub(r"\D", "", str(fields.get("pickup_postcode") or ""))
    if len(pc) >= 2 and pc[:2] in _ZONES:
        return _ZONES[pc[:2]]
    return _AIRPORT_CITY.get((fields.get("origin") or "").upper())


def _local(city, lang):
    return _DE_NAME.get(city, city) if lang == "de" else city


# ---------------------------------------------------------------------------------------------------- lines
# One line each, no digits, nothing in llm/quality.DENY. {CITY} is the customer's city.

CITY_LINE = {   # remarks, not greetings: the sign-off below already says "regards"
    "Hamburg": {"en": "For once your goods leave Hamburg by air instead of down the Elbe.",
                "de": "Ab Hamburg geht es für Ihre Ware diesmal ausnahmsweise per Luft statt über die Elbe."},
    "Munich": {"en": "We'll take it from here, so there's time for a proper Munich Brotzeit.",
               "de": "Den Rest übernehmen wir, da bleibt in München Zeit für eine ordentliche Brotzeit."},
    "Frankfurt": {"en": "With Germany's biggest cargo hub on your Frankfurt doorstep, this one is a home game.",
                  "de": "Mit dem größten Frachtdrehkreuz Deutschlands vor der Frankfurter Haustür ist das ein Heimspiel."},
    "Cologne": {"en": "In Cologne the cathedral stays where it is, your cargo won't.",
                "de": "In Köln bleibt der Dom stehen, Ihre Ware nicht."},
    "Düsseldorf": {"en": "Have an Altbier in Düsseldorf once it has landed.",
                   "de": "Auf ein Alt in Düsseldorf, sobald alles gelandet ist."},
    "Stuttgart": {"en": "You keep Stuttgart's engines running, we'll keep the freight moving.",
                  "de": "Sie schaffe, schaffe in Stuttgart, um den Versand kümmern wir uns."},
    "Bonn": {"en": "Freight with good timing, as Beethoven's hometown would expect.",
             "de": "Ein Versand mit Taktgefühl, wie sich das für die Beethovenstadt gehört."},
}
CITY_GENERIC = {"en": "Always good to get a request from {CITY}.", "de": "Schön, eine Anfrage aus {CITY} zu bekommen."}

DEST_NICK = {
    "JFK": ("the Big Apple", "den Big Apple"), "LAX": ("the City of Angels", "die Stadt der Engel"),
    "ORD": ("the Windy City", "die Windy City"), "MIA": ("Miami sunshine", "die Sonne Miamis"),
    "SIN": ("the Lion City", "die Löwenstadt"), "HKG": ("the Fragrant Harbour", "den Duftenden Hafen"),
    "BOM": ("the City of Dreams", "die Stadt der Träume"), "JNB": ("Jozi", "Jozi"),
    "EZE": ("the Paris of South America", "das Paris Südamerikas"), "GRU": ("Sampa", "Sampa"),
    "CAI": ("the city of a thousand minarets", "die Stadt der tausend Minarette"),
    "NBO": ("the Green City in the Sun", "die grüne Stadt unter der Sonne"), "SYD": ("the Harbour City", "die Hafenstadt Sydney"),
    "MEL": ("Melbourne's coffee lanes", "Melbournes Kaffeegassen"), "NRT": ("Tokyo", "Tokio"), "PVG": ("the Pearl of the Orient", "die Perle des Orients"),
    "PEK": ("Beijing", "Peking"), "ICN": ("Seoul", "Seoul"), "DXB": ("the Dubai skyline", "die Skyline von Dubai"),
    "DOH": ("Doha", "Doha"), "BKK": ("Bangkok", "Bangkok"), "KTM": ("the roof of the world", "das Dach der Welt"),
    "ULN": ("the land of the eternal blue sky", "das Land des ewigen blauen Himmels"), "PPT": ("Tahiti", "Tahiti"),
    "TNR": ("Madagascar", "Madagaskar"), "MEX": ("Mexico City", "Mexiko-Stadt"), "YYZ": ("Toronto", "Toronto"),
    "TPE": ("Taipei", "Taipeh"), "LIM": ("the City of Kings", "die Stadt der Könige"), "LOS": ("Lagos", "Lagos"),
    "BOG": ("Bogotá, up in the Andes", "Bogotá hoch in den Anden"), "SCL": ("Santiago and the Andes", "Santiago und die Anden"),
    "DEL": ("Delhi", "Delhi"), "ATL": ("Atlanta", "Atlanta"), "DFW": ("Texas", "Texas"), "KUL": ("Kuala Lumpur", "Kuala Lumpur"),
    "MNL": ("Manila", "Manila"), "SGN": ("Saigon", "Saigon"), "TLV": ("Tel Aviv", "Tel Aviv"), "RUH": ("Riyadh", "Riad"),
    "ASU": ("Asunción", "Asunción"),
}
DEST_LINE = {"en": "Next stop for your cargo: {NICK}.", "de": "Nächster Halt für Ihre Ware: {NICK}."}


def _berlin(ts):
    """Berlin local time for a unix timestamp (CET; CEST from the last Sunday of March to the last of October)."""
    utc = datetime.fromtimestamp(ts, timezone.utc)
    def last_sunday(month):
        d = datetime(utc.year, month, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    summer = last_sunday(3) <= utc < last_sunday(10)
    return utc + timedelta(hours=2 if summer else 1)


def moment_line(ts, lang):
    t = _berlin(ts or time.time())
    wd, h = t.weekday(), t.hour
    if 0 <= h < 6:
        return {"en": "Late one tonight, glad we could turn it around straight away.",
                "de": "Späte Stunde, umso schöner, dass es gleich klappt."}[lang]
    if wd == 6:
        return {"en": "Sunday or not, your request didn't have to wait.",
                "de": "Sonntag hin oder her, Ihre Anfrage musste nicht warten."}[lang]
    if wd == 5 and h >= 17:
        return {"en": "Saturday evening, but your request didn't have to wait.",
                "de": "Samstagabend, aber Ihre Anfrage musste trotzdem nicht warten."}[lang]
    if h >= 20:
        return {"en": "Working late too, I see. This one was quick to sort.",
                "de": "Auch noch spät dran, wie ich sehe. Das hier ging zum Glück schnell."}[lang]
    if h < 10:
        return {"en": "A good start to the day, this one was quick to sort.",
                "de": "Guter Start in den Tag, das ging schnell."}[lang]
    return {"en": "That one was quick to sort.", "de": "Das ging zum Glück schnell."}[lang]


def local_greeting(hello, city, lang):
    """Moin for the north, Servus / Grüß Gott for Bavaria and Swabia. Only in German; formal stays formal."""
    if lang != "de" or not hello:
        return hello
    formal = hello.startswith("Guten Tag")
    if city in NORTH:
        return re.sub(r"^(Hallo|Guten Tag)", "Moin", hello)
    if city in BAVARIA:
        return re.sub(r"^(Hallo|Guten Tag)", "Grüß Gott" if formal else "Servus", hello)
    if city in SWABIA:
        return re.sub(r"^(Hallo|Guten Tag)", "Grüß Gott", hello)
    return hello


def city_line(city, lang):
    if not city:
        return ""
    line = CITY_LINE.get(city, {}).get(lang) or CITY_GENERIC[lang]
    return line.replace("{CITY}", _local(city, lang))


def dest_line(fields, lang):
    nick = DEST_NICK.get((fields.get("destination") or "").upper())
    return DEST_LINE[lang].replace("{NICK}", nick[1 if lang == "de" else 0]) if nick else ""


def touch(style, fields, lang, received_at=None):
    """-> (greeting_fn or None, line). greeting_fn(hello) swaps the greeting; line goes above the sign-off."""
    if lang not in ("en", "de") or style == "control":
        return None, ""
    city = customer_city(fields)
    if style == "city":
        return None, city_line(city, lang)
    if style == "destination":
        return None, dest_line(fields, lang)
    if style == "moment":
        return None, moment_line(received_at, lang)
    if style == "local":
        return (lambda h: local_greeting(h, city, lang)), city_line(city, lang)
    return None, ""


def apply(body, style, fields, lang, received_at=None):
    """Put the touch into a finished body (greeting is line 0, our signature the last 4 lines incl. the blank one)."""
    swap, line = touch(style, fields, lang, received_at)
    if not swap and not line:
        return body
    lines = body.split("\n")
    if swap and lines:
        lines[0] = swap(lines[0])
    if line and len(lines) > 4:
        lines = lines[:-4] + ["", line] + lines[-4:]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- mirror + shape
# What humanize/ (Riky) does not do. The jury reads the accepted mails with team names hidden; ours were clean but
# every one had the same first sentence, the same last line, and never answered what the customer said as a person.
#   mirror   answer THEIR personal line: "Hope your week's going well!" -> "All good here, thanks, ...",
#            "have a lovely day!" -> "Have a lovely day too!", "Best greetings from Regensburg" -> our sign-off
#            becomes "Best regards to Regensburg". Only what they wrote, never invented. Code, $0.
#   card     one line under the customer's mail in the ONE gateway call: the shape of this reply (first sentence,
#            one detail of theirs, last line), rotated by thread. About 110 tokens, $0.00002 per quote.
#   polish   first word after the greeting line as a native writes it; a greeting line if the model left it out;
#            their first name when the model wrote only "Hi,".

_QUOTED = re.compile(r"^\s*(-{2,}.*(original|ursprüngliche|forwarded|weitergeleitete).*|(from|von|sent|gesendet|subject|betreff)\s*:.*"
                     r"|on .+ wrote:\s*|am .+ schrieb.*|>.*)$", re.I)
_GREET = re.compile(r"^(hi|hello|hey|dear|good (?:morning|afternoon|evening|day)|hallo|liebe[r]?|guten (?:tag|morgen|abend)|moin|servus|"
                    r"grüß gott|sehr geehrte|buongiorno|buonasera|salve|ciao|gentile|bonjour|bonsoir|hola|buenos días|"
                    r"buenas tardes|estimad[oa]s?)\b[^\n]{0,40}$", re.I)
_TOWN = r"([A-ZÄÖÜ][a-zäöüß]+(?:[ -][A-ZÄÖÜ][a-zäöüß]+)?)"

# their wish at the top of the mail -> our line right after the greeting. {N} is their own noun (week, morning, ...)
_WELL = {
    "en": (re.compile(r"hope (?:your (week|day|morning|afternoon|evening|weekend)(?:['’]s| is| has been) (?:going|been) (?:well|good|great)"
                      r"|you(?:['’]re| are) having a (?:good|great|nice|lovely) (week|day|morning|afternoon|evening|weekend)"
                      r"|you(?:['’]re| are) (?:doing )?well|all is well)", re.I),
           ("All good here, thanks, I hope your {N} is going well too.",
            "Thanks, the {N} is going well here, and I hope yours is too.",
            "My {N} is going fine, thanks for asking, and I hope yours is as well."),
           ("All good here, thanks, I hope the same goes for you.", "Doing well, thanks for asking, I hope you are too.")),
    "de": (re.compile(r"hoffe,? (?:es geht ihnen gut|sie hatten ein(?:en)? (?:schönes|gutes|guten|erholsames) (wochenende|start in die woche))|"
                      r"hoffe,? (?:bei ihnen ist alles (?:gut|in ordnung))", re.I),
           ("danke der Nachfrage, hier ist alles bestens, ich hoffe, bei Ihnen auch.",),
           ("danke der Nachfrage, hier ist alles bestens, ich hoffe, bei Ihnen auch.",
            "vielen Dank, hier läuft alles gut, ich hoffe, bei Ihnen ebenso.")),
    "it": (re.compile(r"spero (?:che )?(?:stiate|stia|vada|tutto) (?:tutto )?bene", re.I), (),
           ("Qui tutto bene, grazie, spero anche da voi.",)),
    "fr": (re.compile(r"j['’]espère que (?:vous allez bien|tout va bien)", re.I), (),
           ("Tout va bien de notre côté, merci, j'espère que vous aussi.",)),
    "es": (re.compile(r"espero que (?:esté[n]?|se encuentre[n]?|todo vaya|todo esté) (?:muy )?bien", re.I), (),
           ("Por aquí todo bien, gracias, espero que ustedes también.",)),
}
_RUSH = {
    "en": (re.compile(r"(?:sorry|apologies) for the (rush|short notice|late (?:request|notice))", re.I),
           ("No worries about the {N}.", "No problem at all on the {N}.")),
    "de": (re.compile(r"entschuldigen sie (?:bitte )?die (eile|kurzfristige anfrage|kurzfristigkeit)", re.I),
           ("kein Problem, dafür sind wir da.",)),
}
# their parting wish -> our last line. Group 1 is repeated in their own words.
_WISH = {
    "en": (re.compile(r"\bhave an? ((?:lovely|nice|great|good|wonderful|pleasant) (?:day|evening|weekend|week|afternoon|rest of the (?:day|week)))(!?)", re.I),
           "Have a {W} too"),
    "de": (re.compile(r"\b(einen schönen tag|einen schönen abend|ein schönes wochenende|einen schönen feierabend|eine schöne woche)(?: noch)?(!?)", re.I),
           "Ihnen auch {W}"),
    "it": (re.compile(r"\b(buona giornata|buona serata|buon lavoro|buon fine settimana|buon weekend)(!?)", re.I), "{W} anche a voi"),
    "fr": (re.compile(r"\b(bonne journée|bonne soirée|bon week-end|bonne fin de journée|bonne semaine)( ?!)?", re.I), "{W} à vous aussi"),
    "es": (re.compile(r"\b(buen día|buena tarde|buen fin de semana|feliz día|buena semana)(!?)", re.I), "Igualmente, {W}"),
}
# greetings from their town -> our sign-off line goes back there
_FROM = {
    "en": (re.compile(r"\b(?:greetings|regards|wishes) from " + _TOWN), ("Best regards to {T}", "Greetings back to {T}", "Kind regards to {T}")),
    "de": (re.compile(r"\b[Gg]r(?:ü|ue)(?:ß|ss)en? aus " + _TOWN), ("Viele Grüße zurück nach {T}", "Beste Grüße nach {T}")),
    "it": (re.compile(r"\b[Ss]alut[io] da " + _TOWN), ("Un caro saluto a {T}",)),
}
_NOT_A_TOWN = {"The", "Our", "All", "Us", "Me", "Germany", "Deutschland", "Der", "Dem", "Uns"}


def own_text(body):
    """The customer's own words: a forwarded or quoted chain below is cut."""
    out = []
    for line in (body or "").split("\n"):
        if _QUOTED.match(line):
            break
        out.append(line)
    return "\n".join(out)


def signed_name(body):
    """The first name the customer signed with: humanize/'s reader (Riky), on their own text only, so the sign-off
    of a forwarded mail below is never taken for theirs."""
    try:
        import humanize
        return humanize.signed_name(own_text(body))
    except Exception:
        return None


def cues(body, lang):
    """What the customer wrote as a person, read from their own text -> {"well": noun or "", "rush": ..., "wish": [words, "!"],
    "town": ..., "cheers": True}. Empty dict = they wrote nothing personal, so we add nothing personal."""
    text, out = own_text(body), {}
    if lang in _WELL:
        m = _WELL[lang][0].search(text)
        if m:
            out["well"] = (next((g for g in m.groups() if g), "") or "").lower()
    if lang in _RUSH:
        m = _RUSH[lang][0].search(text)
        if m:
            out["rush"] = m.group(1).lower()
    if lang in _WISH:
        m = _WISH[lang][0].search(text)
        if m:
            out["wish"] = [m.group(1).lower(), "!" if (m.group(2) or "").strip() else "."]
    if lang in _FROM:
        m = _FROM[lang][0].search(text)
        if m and m.group(1).split()[0] not in _NOT_A_TOWN:
            out["town"] = m.group(1)
    if lang == "en" and re.search(r"^\s*cheers\b[ ,!]*$", text, re.I | re.M):
        out["cheers"] = True
    return out


def mix(salt, thread_id):
    """A well mixed number per (purpose, thread). crc32 of "open:1", "open:2", "open:3" lands on the same variant."""
    return int(hashlib.md5(("%s:%s" % (salt, thread_id)).encode()).hexdigest()[:8], 16)


def _pick(options, thread_id, salt):
    return options[mix(salt, thread_id) % len(options)]


def mirror(body, found, lang, thread_id=0):
    """Put our answers to their personal lines into a finished body (greeting is line 0, our 3 signature lines last).
    A line the model already wrote itself is not doubled."""
    if not found:
        return body
    lines = body.split("\n")
    if len(lines) < 6 or lines[1].strip():
        return body
    head, sign = lines[:-4], lines[-4:]                      # sign = ["", sign-off, signer, team]
    text = "\n".join(head[2:]).lower()
    first = None
    if "well" in found and lang in _WELL and not re.search(r"\b(hope|hoffe|spero|espère|espero)\b", text):
        named, plain = _WELL[lang][1], _WELL[lang][2]
        first = _pick(named, thread_id, "well").replace("{N}", found["well"]) if found["well"] and named else _pick(plain, thread_id, "well")
    elif "rush" in found and lang in _RUSH and not re.search(r"\b(no worries|no problem|kein problem)\b", text):
        first = _pick(_RUSH[lang][1], thread_id, "rush").replace("{N}", found["rush"])
    if first and len(head) > 2:
        rest = head[2]
        head[2] = first + " " + rest[:1].upper() + rest[1:]
    if "wish" in found and lang in _WISH and found["wish"][0] not in text:
        words, mark = found["wish"]
        if lang == "de":                                     # the noun is the last word: "einen schönen Tag"
            words = re.sub(r"(\w+)$", lambda m: m.group(1).capitalize(), words)
        line = _WISH[lang][1].replace("{W}", words)
        head += ["", line[:1].upper() + line[1:] + mark]
    if "town" in found and lang in _FROM:
        sign[1] = _pick(_FROM[lang][1], thread_id, "town").replace("{T}", found["town"])
    elif found.get("cheers") and lang == "en":
        sign[1] = "Cheers"
    return "\n".join(head + sign)


_DE_LOWER = {"Für", "Ich", "Wir", "Gerne", "Danke", "Vielen", "Die", "Der", "Das", "Hier", "Kurz", "Mit", "Bei", "Zu",
             "Auch", "Gute", "Anbei", "Wie", "Nach", "Am", "Schön"}


_BARE = re.compile(r"^(hi|hello|hey|hallo|guten tag|guten morgen|buongiorno|buonasera|salve|bonjour|bonsoir|hola|buenos días)\s*,$", re.I)


def polish(body, lang, hello="", name=None):
    """What a person gets right without thinking: a greeting line (the model sometimes starts with the answer),
    the name when they signed with one and the model wrote only "Hi,", and the first word after the greeting:
    capital in English, French and Spanish, lower case in German ("Hallo Katrin,\\n\\nfür Ihre ...").
    A WRONG name and doubled units are humanize/'s job (core.finalize), not ours."""
    lines = body.split("\n")
    first = lines[0].strip() if lines else ""
    if hello and first and not _GREET.match(first) and not (first.endswith(",") and len(first.split()) <= 4):
        lines = [hello, ""] + lines
    elif name and _BARE.match(first):
        lines[0] = "%s %s," % (first.rstrip(" ,"), name)
    if len(lines) > 2 and lines[0].rstrip().endswith(",") and not lines[1].strip() and lines[2]:
        first = lines[2].split(" ", 1)[0]
        if lang in ("en", "fr", "es") and first[:1].islower():
            lines[2] = lines[2][:1].upper() + lines[2][1:]
        elif lang == "de" and first in _DE_LOWER:
            lines[2] = lines[2][:1].lower() + lines[2][1:]
    return "\n".join(lines)


CARD_OPEN = (
    "the first sentence after the greeting gives the answer itself, airline and price; their details come after it",
    "the first sentence after the greeting is about their goods and where they are going, in your own words; the price comes in the second sentence",
    "the first sentence after the greeting says you have looked at their lane; the price comes in the second sentence",
    "the first sentence after the greeting confirms what they asked for (cheapest or fastest, pickup at their site or their own delivery); then the price",
)
CARD_CLOSE = (
    "the last line is a short question: should you book it",
    "the last line says a one-line yes is enough and you will book it",
    "the last line says you will book it as soon as they give the go-ahead",
    "the last line asks if that works for them and offers to book right away",
    "the last line tells them to just say the word and you will get it booked",
)


def card_index(thread_id):
    return mix("card-open", thread_id) % len(CARD_OPEN), mix("card-close", thread_id) % len(CARD_CLOSE)


def style_card(thread_id):
    o, c = card_index(thread_id)
    return ("Shape of this reply: greeting line with their first name; %s; one sentence that picks up what they told you "
            "(pickup at their site = our truck, in the price; their own delivery; the ready date); %s, in its own "
            "paragraph. Use {AIRLINE}, {PRICE} and {TRANSIT_DAYS}. Your own words, in the customer's language."
            % (CARD_OPEN[o], CARD_CLOSE[c]))


# ---------------------------------------------------------------------------------------------------- learning

_lock = threading.Lock()
_watcher = None


def _load():
    try:
        with open(STATE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("arms", {})
    for k in STYLES:
        s["arms"].setdefault(k, {"wins": 0.0, "losses": 0.0, "sent": 0})
    s.setdefault("pending", [])
    s.setdefault("last_human", None)
    s.setdefault("log", [])
    return s


def _save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, STATE)


def available(fields, lang, received_at=None):
    """Styles that would actually change this mail (no city known -> no city style)."""
    out = ["control"]
    for st in STYLES[1:]:
        swap, line = touch(st, fields, lang, received_at)
        if line or swap:
            out.append(st)
    return out


def choose(fields, lang, thread_id=0, received_at=None, rng=None):
    """Thompson sampling over the styles that fit this mail."""
    if _learning_on():
        _ensure_watcher()                                 # baseline of our human count before the first quote
    if HUMAN_STYLE in STYLES:
        return HUMAN_STYLE
    options = available(fields, lang, received_at)
    if len(options) == 1:
        return "control"
    with _lock:
        arms = _load()["arms"]
    rng = rng or random.Random(zlib.crc32(str(thread_id).encode()) ^ int(time.time() // 60))
    draws = {st: rng.betavariate(arms[st]["wins"] + 1, arms[st]["losses"] + 1) for st in options}
    return max(draws, key=draws.get)


def _learning_on():
    """Only the live clerk learns: never in DRY_RUN, never inside the test suite (tests patch DRY_RUN off)."""
    return not config.DRY_RUN and os.environ.get("HUMAN_LEARN", "1") == "1"


def record(thread_id, style, now=None):
    """The runner sent a quote in this style: it waits for the jury."""
    if not _learning_on():
        return
    with _lock:
        s = _load()
        s["arms"][style]["sent"] += 1
        s["pending"].append({"tid": thread_id, "style": style, "t": now or time.time()})
        _save(s)
    _ensure_watcher()


def learn(human_now, now=None):
    """Feed the board's current `human` count for our team. Wins go to the quotes since the last rise."""
    now = now or time.time()
    with _lock:
        s = _load()
        last = s["last_human"]
        s["last_human"] = human_now
        if last is not None and human_now > last and s["pending"]:
            gain = float(human_now - last)
            share = gain / len(s["pending"])
            for p in s["pending"]:
                s["arms"][p["style"]]["wins"] += share
            s["log"].append({"t": now, "event": "win", "gain": gain, "styles": [p["style"] for p in s["pending"]]})
            s["pending"] = []
        keep = []
        for p in s["pending"]:
            if now - p["t"] > LEARN_WINDOW_S:
                s["arms"][p["style"]]["losses"] += 1
            else:
                keep.append(p)
        s["pending"] = keep
        s["log"] = s["log"][-200:]
        _save(s)
        return s


def _board_human():
    with urllib.request.urlopen(config.BASE_URL + "/v1/board", timeout=8) as r:
        d = json.load(r)
    for t in d.get("ranking", []):
        if t.get("team") == TEAM or t.get("name") == TEAM.lower():
            return int(t.get("human") or 0)
    return None


def _watch():
    while True:
        try:
            h = _board_human()
            if h is not None:
                learn(h)
        except Exception:
            pass
        time.sleep(POLL_S)


def _ensure_watcher():
    global _watcher
    if _watcher is None or not _watcher.is_alive():
        _watcher = threading.Thread(target=_watch, name="human-learn", daemon=True)
        _watcher.start()


def report():
    s = _load()
    lines = ["style        sent   wins  losses  p(win) ~", "-" * 42]
    for st in STYLES:
        a = s["arms"][st]
        lines.append("%-12s %4d  %5.2f  %6.1f   %.2f" % (st, a["sent"], a["wins"], a["losses"],
                                                       (a["wins"] + 1) / (a["wins"] + a["losses"] + 2)))
    lines.append("pending: %d, our human count last seen: %s" % (len(s["pending"]), s["last_human"]))
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
