"""RFQ template: the fields every air-export request needs, a cheap regex
extractor, and a validator that says what is missing or suspicious.

No LLM here. The router calls `extract_rfq(subject, body)` first; only if
`validate(rfq)` reports missing REQUIRED fields do we spend an LLM call to
fill exactly those fields (see docs/rfq-template.md).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / "kit" / "start-kit"

VOLUME_FACTOR = 167  # kg per cbm, same in every start-kit tariff
QUOTE_CURRENCY = "EUR"  # every start-kit tariff is EUR


# --------------------------------------------------------------------------
# Reference data (loaded once from the start kit)
# --------------------------------------------------------------------------
def _load_zones() -> dict[str, str]:
    with open(KIT / "pickup_zones.csv", newline="") as f:
        return {r["zone"].strip(): r["airport"].strip() for r in csv.DictReader(f)}


def _load_destinations() -> set[str]:
    dests: set[str] = set()
    with open(KIT / "carrier-list.csv", newline="") as f:
        for r in csv.DictReader(f):
            if r["kind"] == "airline":
                dests.update(r["serves"].split())
    lanes = ROOT / "docs" / "portal-lanes.json"
    if lanes.exists():
        dests.update(l["destination"] for l in json.loads(lanes.read_text())["lanes"])
    return dests


PICKUP_ZONES = _load_zones()                    # "80" -> "MUC"
ORIGINS = set(PICKUP_ZONES.values())            # FRA MUC DUS HAM STR CGN
DESTINATIONS = _load_destinations()             # every IATA code someone serves


def live_lanes() -> set[tuple[str, str]]:
    """Lanes the portal prices RIGHT NOW (sourcing/portal.py re-reads /v1/portal/ports every 3 min).
    5U changes the setup hourly: a new origin or destination there must not send a request to a human."""
    try:
        from sourcing import portal
        portal.refresh_lanes()                      # at most one free read every 3 min, no-op without a key
        return set(portal.LANES)
    except Exception:
        return set()


def known_origins() -> set[str]:
    return ORIGINS | {o for o, _ in live_lanes()}


def known_destinations() -> set[str]:
    return DESTINATIONS | {d for _, d in live_lanes()}

# City names customers may write instead of codes (EN + DE + local spellings).
CITY_TO_IATA = {
    # other languages (Erik's dry run: Italian "Francoforte" / "Dubai" gave destination=null)
    "francoforte": "FRA", "francfort": "FRA", "fráncfort": "FRA", "monaco di baviera": "MUC", "munique": "MUC",
    "amburgo": "HAM", "hambourg": "HAM", "colonia": "CGN", "stoccarda": "STR", "dusseldorf am rhein": "DUS",
    "nueva york": "JFK", "nuova york": "JFK", "pechino": "PEK", "pékin": "PEK", "pekín": "PEK", "dubái": "DXB",
    "dubaï": "DXB", "città del messico": "MEX", "ciudad de méxico": "MEX", "ciudad de mexico": "MEX",
    "san paolo": "GRU", "tel aviv-yafo": "TLV", "singapour": "SIN", "singapura": "SIN", "le caire": "CAI",
    "il cairo": "CAI", "el cairo": "CAI", "seul": "ICN", "séoul": "ICN",
    # origins
    "frankfurt": "FRA", "munich": "MUC", "münchen": "MUC", "muenchen": "MUC",
    "dusseldorf": "DUS", "düsseldorf": "DUS", "duesseldorf": "DUS",
    "hamburg": "HAM", "stuttgart": "STR", "cologne": "CGN", "köln": "CGN", "koeln": "CGN",
    # destinations
    "atlanta": "ATL", "bangkok": "BKK", "bogota": "BOG", "bogotá": "BOG",
    "mumbai": "BOM", "bombay": "BOM", "cairo": "CAI", "kairo": "CAI",
    "delhi": "DEL", "new delhi": "DEL", "dallas": "DFW", "doha": "DOH", "dubai": "DXB",
    "buenos aires": "EZE", "sao paulo": "GRU", "são paulo": "GRU", "hong kong": "HKG",
    "seoul": "ICN", "new york": "JFK", "johannesburg": "JNB", "kuala lumpur": "KUL",
    "los angeles": "LAX", "lima": "LIM", "lagos": "LOS", "melbourne": "MEL",
    "mexico city": "MEX", "mexiko-stadt": "MEX", "miami": "MIA", "manila": "MNL",
    "nairobi": "NBO", "tokyo": "NRT", "tokio": "NRT", "chicago": "ORD",
    "beijing": "PEK", "peking": "PEK", "shanghai": "PVG", "riyadh": "RUH", "riad": "RUH",
    "santiago": "SCL", "ho chi minh city": "SGN", "saigon": "SGN", "singapore": "SIN",
    "singapur": "SIN", "sydney": "SYD", "tel aviv": "TLV", "taipei": "TPE", "toronto": "YYZ",
    "asuncion": "ASU", "asunción": "ASU", "kathmandu": "KTM", "papeete": "PPT",
    "antananarivo": "TNR", "ulaanbaatar": "ULN", "ulan bator": "ULN",
}


# --------------------------------------------------------------------------
# The template
# --------------------------------------------------------------------------
class Mode(str, Enum):
    CHEAPEST = "cheapest"
    FASTEST = "fastest"


class Service(str, Enum):
    AIRPORT_TO_AIRPORT = "airport_to_airport"
    DOOR_TO_PORT = "door_to_port"


@dataclass
class RFQ:
    # --- from the mail envelope (always present, set by the mailbox poller)
    message_id: str | None = None        # reply with in_reply_to = this
    thread_id: str | None = None
    customer_email: str | None = None
    received_at: str | None = None       # ISO time, starts the 6-min clock

    # --- REQUIRED to price
    origin: str | None = None            # IATA, one of ORIGINS (or derived from pickup_postcode)
    destination: str | None = None       # IATA
    weight_kg: float | None = None       # total actual gross weight
    mode: Mode | None = None             # cheapest | fastest (default cheapest, but flag it)

    # --- STRONGLY RECOMMENDED (changes chargeable weight)
    volume_cbm: float | None = None      # total volume; or derived from pieces x dims
    pieces: int | None = None
    dims_cm: tuple[float, float, float] | None = None  # L x W x H of ONE piece

    # --- door-to-port only
    service: Service = Service.AIRPORT_TO_AIRPORT
    pickup_postcode: str | None = None   # German 5-digit postcode -> zone -> airport

    # --- optional / informational
    commodity: str | None = None
    dangerous_goods: bool = False        # out of scope -> hand to a human
    ready_date: str | None = None
    language: str | None = None          # reply in the customer's language
    currency_requested: str | None = None

    # --- derived (filled by normalize())
    chargeable_kg: float | None = None
    pickup_zone: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = self.mode.value if self.mode else None
        d["service"] = self.service.value
        return d


REQUIRED = ("origin", "destination", "weight_kg", "mode")
RECOMMENDED = ("volume_cbm",)


# --------------------------------------------------------------------------
# Cheap regex extractor (free, runs before any LLM)
# --------------------------------------------------------------------------
_NUM = r"(\d{1,3}(?:[.\s,]\d{3})*(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"


def _num(s: str) -> float:
    s = s.replace(" ", "")
    if "," in s and "." in s:            # 1.234,5 or 1,234.5
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:                        # 2,5 (decimal) vs 1,200 (thousands)
        head, tail = s.rsplit(",", 1)
        s = s.replace(",", "") if len(tail) == 3 and head.isdigit() else s.replace(",", ".")
    return float(s)


def _find_place(text: str) -> tuple[list[str], list[str]]:
    """(IATA codes, codes from city names), each in the order they appear.
    Explicit codes win: a pickup city ("collect in Hamburg") must not beat "from FRA"."""
    known = known_origins() | known_destinations()
    codes = [m.group(1) for m in re.finditer(r"\b([A-Z]{3})\b", text) if m.group(1) in known]
    low = text.lower()
    hits = sorted((m.start(), code) for name, code in CITY_TO_IATA.items()
                  for m in re.finditer(r"\b" + re.escape(name) + r"\b", low))
    return codes, [c for _, c in hits]


def extract_rfq(subject: str, body: str, **envelope) -> RFQ:
    text = f"{subject}\n{body}"
    low = text.lower()
    r = RFQ(**envelope)

    # route: "X to Y", "X -> Y", "X - Y", "from X ... to Y", or first origin + first destination
    codes, cities = _find_place(text)
    for places in (codes, cities):
        org, dst = known_origins(), known_destinations()
        origins = [p for p in places if p in org]
        dests = [p for p in places if p in dst and p not in org]
        r.origin = r.origin or (origins[0] if origins else None)
        r.destination = r.destination or (dests[0] if dests else None)

    m = re.search(_NUM + r"\s*(?:kg|kgs|kilo(?:gram)?s?)\b", low)
    if m:
        r.weight_kg = _num(m.group(1))

    m = re.search(_NUM + r"\s*(?:cbm|m3|m³|cubic met(?:er|re)s?)", low)
    if m:
        r.volume_cbm = _num(m.group(1))

    m = re.search(r"(\d+)\s*(?:pcs|pieces|pallets?|cartons?|boxes|colli|packages|stück|paletten)", low)
    if m:
        r.pieces = int(m.group(1))

    m = re.search(_NUM + r"\s*[x×*]\s*" + _NUM + r"\s*[x×*]\s*" + _NUM + r"\s*cm", low)
    if m:
        r.dims_cm = tuple(_num(m.group(i)) for i in (1, 2, 3))

    if re.search(r"\b(fastest|quickest|urgent|asap|express|schnellste|eilig|dringend|le plus rapide|más rápido)\b", low):
        r.mode = Mode.FASTEST
    elif re.search(r"\b(cheapest|lowest|best price|economy|günstigste|billigste|le moins cher|más barato)\b", low):
        r.mode = Mode.CHEAPEST

    m = re.search(r"\b(?:d-)?(\d{5})\b", text)
    if m and re.search(r"pick ?up|abhol|collect|door|from our (?:warehouse|site|factory)|ab werk", low):
        r.service = Service.DOOR_TO_PORT
        r.pickup_postcode = m.group(1)

    try:                                                 # a denial ("no dangerous goods") is not DG (Riky, PR #17)
        import dg
        declared = bool(dg.read_declaration(text))
    except Exception:
        declared = bool(re.search(r"\bun ?\d{4}\b", low))
    if declared:
        r.dangerous_goods = True

    m = re.search(r"\b(USD|EUR|GBP|CHF)\b", text)
    if m:
        r.currency_requested = m.group(1)

    return normalize(r)


# --------------------------------------------------------------------------
# Normalize + validate
# --------------------------------------------------------------------------
def normalize(r: RFQ) -> RFQ:
    if r.pickup_postcode and len(r.pickup_postcode) == 5:
        r.pickup_zone = r.pickup_postcode[:2]
        zone_airport = PICKUP_ZONES.get(r.pickup_zone)
        if zone_airport and not r.origin:
            r.origin = zone_airport
    if r.volume_cbm is None and r.dims_cm and r.pieces:
        l, w, h = r.dims_cm
        r.volume_cbm = round(l * w * h / 1_000_000 * r.pieces, 3)
    if r.weight_kg is not None:
        vol_kg = (r.volume_cbm or 0) * VOLUME_FACTOR
        r.chargeable_kg = round(max(r.weight_kg, vol_kg), 2)
    return r


class Level(str, Enum):
    MISSING = "missing"    # cannot price -> ask LLM to fill, else ask customer
    WARNING = "warning"    # can price, but risky -> flag in sessions UI
    HUMAN = "human"        # out of scope / judgement call -> hand over


@dataclass
class Issue:
    field: str
    level: Level
    message: str


def validate(r: RFQ) -> list[Issue]:
    issues: list[Issue] = []
    add = lambda f, lvl, msg: issues.append(Issue(f, lvl, msg))

    # envelope
    for f in ("message_id", "customer_email"):
        if not getattr(r, f):
            add(f, Level.MISSING, "needed to reply in the customer's thread")

    # required
    if not r.origin:
        add("origin", Level.MISSING, "no origin airport or pickup postcode")
    elif r.origin not in known_origins():
        add("origin", Level.HUMAN, f"{r.origin} is not an export airport we or the portal serve {sorted(known_origins())}")
    elif r.origin not in ORIGINS:
        add("origin", Level.WARNING, f"{r.origin} is a new origin (on the portal since 5U's last change)")
    if not r.destination:
        add("destination", Level.MISSING, "no destination")
    elif r.destination not in known_destinations():
        add("destination", Level.HUMAN, f"nobody in the carrier list or on the portal serves {r.destination}")
    if r.weight_kg is None:
        add("weight_kg", Level.MISSING, "no weight")
    elif r.weight_kg <= 0 or r.weight_kg > 100_000:          # portal max is 100 t: never quote outside
        add("weight_kg", Level.HUMAN, f"weight {r.weight_kg} kg is impossible to quote")
    elif r.weight_kg > 50_000:
        add("weight_kg", Level.WARNING, f"weight {r.weight_kg} kg looks wrong")
    if r.mode is None:
        add("mode", Level.WARNING, "customer did not say cheapest or fastest -> defaulting to cheapest")

    # recommended
    if r.volume_cbm is None:
        add("volume_cbm", Level.WARNING, "no volume or dims -> pricing on actual weight only")
    elif r.weight_kg:
        density = r.weight_kg / r.volume_cbm if r.volume_cbm else float("inf")
        if density < 10 or density > 2000:
            add("volume_cbm", Level.WARNING, f"density {density:.0f} kg/cbm is unusual, check units (cm vs m?)")

    # door-to-port
    if r.service == Service.DOOR_TO_PORT:
        if not r.pickup_postcode:
            add("pickup_postcode", Level.MISSING, "door-to-port but no pickup postcode")
        elif r.pickup_zone not in PICKUP_ZONES:
            add("pickup_postcode", Level.HUMAN, f"zone {r.pickup_zone} not in pickup_zones.csv")
        elif r.origin and PICKUP_ZONES[r.pickup_zone] != r.origin:
            add("origin", Level.WARNING,
                f"pickup zone {r.pickup_zone} maps to {PICKUP_ZONES[r.pickup_zone]}, customer said {r.origin}")

    # scope
    if r.dangerous_goods:                                # since 17:00 5U sends DG RFQs: dg.apply quotes them (Riky, PR #17)
        import os
        if os.environ.get("DG_MODE", "docs").strip().lower() == "human":
            add("dangerous_goods", Level.HUMAN, "dangerous goods mentioned -> hand to a human")
        else:
            add("dangerous_goods", Level.WARNING, "dangerous goods -> quoted with the DG documents paragraph")
    if r.currency_requested and r.currency_requested != QUOTE_CURRENCY:
        add("currency_requested", Level.WARNING,
            f"customer asked for {r.currency_requested}, tariffs are {QUOTE_CURRENCY}")
    return issues


def missing_fields(issues: list[Issue]) -> list[str]:
    """Fields to ask the LLM (one cheap call) to fill, envelope excluded."""
    return [i.field for i in issues
            if i.level == Level.MISSING and i.field not in ("message_id", "customer_email")]


def can_price(issues: list[Issue]) -> bool:
    return not any(i.level in (Level.MISSING, Level.HUMAN) for i in issues)


# --------------------------------------------------------------------------
# Gate for core/main.py handle_rfq: LLM fields in, go / no-go + reason codes out
# --------------------------------------------------------------------------
KINDS = ("new_request", "accept", "question", "other")


def from_fields(fields: dict, mail: dict) -> RFQ:
    """Turn the LLM form (llm/extract.py) into an RFQ. Uses the totals core already computed."""
    prefer = (fields.get("prefer") or "").lower()
    postcode = str(fields.get("pickup_postcode") or "").strip() or None
    r = RFQ(
        message_id=str(mail.get("id") or "") or None,
        thread_id=str(mail.get("thread_id") or "") or None,
        customer_email=mail.get("sender"),
        origin=(fields.get("origin") or "").upper() or None,
        destination=(fields.get("destination") or "").upper() or None,
        weight_kg=fields.get("weight_kg_total") or fields.get("weight_kg") or None,
        volume_cbm=fields.get("volume_cbm_total") or fields.get("volume_cbm") or None,
        mode=Mode.FASTEST if prefer == "fastest" else Mode.CHEAPEST if prefer == "cheapest" else None,
        service=Service.DOOR_TO_PORT if postcode else Service.AIRPORT_TO_AIRPORT,
        pickup_postcode=postcode,
        dangerous_goods=bool(fields.get("dangerous_goods")),
        currency_requested=(fields.get("currency") or None),
        language=fields.get("language"),
    )
    return normalize(r)


def _cross_check(llm: RFQ, rx: RFQ) -> list[str]:
    """Free second reader. Disagreement is a warning, not a stop: a stop scores 0 for sure."""
    out = []
    if llm.destination and rx.destination and llm.destination != rx.destination:
        out.append(f"llm_regex_mismatch: destination {llm.destination} vs {rx.destination}")
    if llm.weight_kg and rx.weight_kg and abs(llm.weight_kg - rx.weight_kg) > 0.05 * llm.weight_kg:
        out.append(f"llm_regex_mismatch: weight {llm.weight_kg} vs {rx.weight_kg} kg")
    return out


_NEG_WEIGHT = re.compile(r"(?<![\w.])-\s*\d[\d.,]*\s*(kg|kgs|t|tons?|tonnen)\b", re.I)
_THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3})[.,](\d{3})(?![\d.,])\s*(kg|kgs)\b", re.I)


def _weight_traps(r: "RFQ", text: str) -> list[str]:
    """Stops for weights a reader can get badly wrong (found by red-team mails)."""
    out = []
    if _NEG_WEIGHT.search(text):
        out.append("weight_kg: negative weight in the mail")
    m = _THOUSANDS.search(text)
    if m and r.weight_kg is not None:
        as_decimal = float("%s.%s" % (m.group(1), m.group(2)))
        if abs(r.weight_kg - as_decimal) < 0.01:            # "1.200 kg" read as 1.2 kg: German 1200 kg is likelier
            out.append("weight_kg: '%s' read as %s kg, could be %s kg" % (m.group(0), as_decimal,
                                                                          int(m.group(1) + m.group(2))))
    return out


_DG_DENIAL = re.compile(r"non[- ]?dangerous|non[- ]?hazardous|not? (?:a )?dangerous|no dangerous goods|not hazardous|"
                        r"kein(?:e)? gefahrgut|nicht gef[aä]hrlich|ungef[aä]hrlich|dangerous goods:\s*no\b", re.I)


def _declared_dg(mail: dict):
    """The model flagged dangerous goods in the MAIL. Is it a real declaration?
    A UN number / 'Dangerous goods: ...' -> the dict from dg.read_declaration. A plain denial ('non-dangerous',
    'no dangerous goods') -> None, it is NOT dangerous goods. Anything else the model flagged (lithium batteries,
    'hazmat') -> True: dg/ adds the documents paragraph without a UN number."""
    text = (mail.get("subject") or "") + "\n" + (mail.get("body") or "")
    try:
        import dg
        found = dg.read_declaration(text)
    except Exception:
        found = None
    if found:
        return found
    return None if _DG_DENIAL.search(text) else True


def gate(fields: dict, mail: dict) -> tuple[bool, str]:
    """(ok, note). ok=False -> needs_human with `note`. ok=True -> price it; note lists warnings (may be "").

    Reason codes, first word of each part of the note (the UI shows them):
      not_a_request, multi_shipment, unclear, missing, dangerous_goods, origin, destination,
      pickup_postcode, llm_regex_mismatch, volume_cbm, mode, currency_requested
    """
    stop, warn = [], []
    kind = (fields.get("kind") or "new_request").lower()
    if kind not in ("new_request",):
        stop.append(f"not_a_request: kind={kind}")
    if fields.get("multi_shipment") or len(fields.get("shipments") or []) > 1:
        stop.append("multi_shipment: several shipments in one mail")
    if fields.get("unclear"):
        stop.append("unclear: " + "; ".join(map(str, fields["unclear"]))[:200])

    r = from_fields(fields, mail)
    if r.dangerous_goods or fields.get("dg"):            # DG is no longer a stop: dg/ writes it into the quote
        import os
        fields["dg"] = fields.get("dg") or _declared_dg(mail)
        human = os.environ.get("DG_MODE", "docs").strip().lower() == "human"
        r.dangerous_goods = bool(fields["dg"]) and human     # DG_MODE=human: validate() below stops it, as before
        if fields["dg"] and not human:
            warn.append("dangerous_goods: declared, quoted with the DG documents paragraph")
    for i in validate(r):
        if i.field in ("message_id", "customer_email"):
            continue                                     # envelope is core's job
        if i.level == Level.MISSING:
            stop.append(f"missing: {i.field}")
        elif i.level == Level.HUMAN:
            stop.append(f"{i.field}: {i.message}")
        else:
            warn.append(f"{i.field}: {i.message}")
    stop += _weight_traps(r, (mail.get("subject") or "") + "\n" + (mail.get("body") or ""))
    warn += _cross_check(r, extract_rfq(mail.get("subject") or "", mail.get("body") or ""))
    return (not stop), " | ".join(stop + warn)
