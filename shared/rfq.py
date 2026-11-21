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

# City names customers may write instead of codes (EN + DE + local spellings).
CITY_TO_IATA = {
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
    known = ORIGINS | DESTINATIONS
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
        origins = [p for p in places if p in ORIGINS]
        dests = [p for p in places if p in DESTINATIONS and p not in ORIGINS]
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

    if re.search(r"\b(dangerous goods|dgr|hazmat|un ?\d{4}|lithium|gefahrgut)\b", low):
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
    elif r.origin not in ORIGINS:
        add("origin", Level.HUMAN, f"{r.origin} is not one of our export airports {sorted(ORIGINS)}")
    if not r.destination:
        add("destination", Level.MISSING, "no destination")
    elif r.destination not in DESTINATIONS:
        add("destination", Level.HUMAN, f"nobody in the carrier list serves {r.destination}")
    if r.weight_kg is None:
        add("weight_kg", Level.MISSING, "no weight")
    elif r.weight_kg <= 0 or r.weight_kg > 50_000:
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
    if r.dangerous_goods:
        add("dangerous_goods", Level.HUMAN, "dangerous goods mentioned -> hand to a human")
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
