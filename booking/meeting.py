"""Customer wants a better price -> offer a short call with our forwarder.

Finds free slots in the forwarder's calendar (booking/forwarder_calendar.json, or an .ics file via FORWARDER_ICS)
that are inside the forwarder's working hours AND a polite hour for the customer (08:00-19:00 their time).
The customer's time zone comes from the mail (e.g. "EST", "UTC+8", "Singapore time") or the sender's country domain;
default Europe/Berlin. No LLM, no network.
"""
import datetime as dt, json, os, re
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CAL_PATH = os.environ.get("FORWARDER_CALENDAR", os.path.join(HERE, "forwarder_calendar.json"))
CUSTOMER_HOURS = (8, 19)

TZ_WORDS = {  # words a customer may write -> IANA zone
    r"\b(est|edt|eastern time|new york)\b": "America/New_York", r"\b(cst|cdt|central time|chicago)\b": "America/Chicago",
    r"\b(pst|pdt|pacific time|los angeles|california)\b": "America/Los_Angeles",
    r"\b(gmt|bst|london|uk time)\b": "Europe/London", r"\b(cet|cest|mez|berlin|german time)\b": "Europe/Berlin",
    r"\b(ist|india|mumbai|delhi)\b": "Asia/Kolkata", r"\b(sgt|singapore)\b": "Asia/Singapore",
    r"\b(jst|tokyo|japan)\b": "Asia/Tokyo", r"\b(aest|aedt|sydney)\b": "Australia/Sydney",
    r"\b(gst|dubai)\b": "Asia/Dubai", r"\b(brt|são paulo|sao paulo)\b": "America/Sao_Paulo",
    r"\b(hkt|hong kong)\b": "Asia/Hong_Kong", r"\b(cst china|beijing|shanghai)\b": "Asia/Shanghai",
}
TLD = {"de": "Europe/Berlin", "at": "Europe/Vienna", "ch": "Europe/Zurich", "fr": "Europe/Paris", "it": "Europe/Rome",
       "es": "Europe/Madrid", "nl": "Europe/Amsterdam", "uk": "Europe/London", "pl": "Europe/Warsaw",
       "us": "America/New_York", "ca": "America/Toronto", "mx": "America/Mexico_City", "br": "America/Sao_Paulo",
       "ar": "America/Argentina/Buenos_Aires", "in": "Asia/Kolkata", "sg": "Asia/Singapore", "jp": "Asia/Tokyo",
       "cn": "Asia/Shanghai", "hk": "Asia/Hong_Kong", "kr": "Asia/Seoul", "tw": "Asia/Taipei", "au": "Australia/Sydney",
       "ae": "Asia/Dubai", "za": "Africa/Johannesburg", "tr": "Europe/Istanbul"}


def customer_zone(text, sender):
    t = (text or "").lower()
    m = re.search(r"\b(?:utc|gmt)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?\b", t)
    if m:
        mins = int(m.group(2)) * 60 + int(m.group(3) or 0)
        return dt.timezone(dt.timedelta(minutes=mins if m.group(1) == "+" else -mins), "UTC%s%s" % (m.group(1), m.group(2)))
    for pat, zone in TZ_WORDS.items():
        if re.search(pat, t):
            return ZoneInfo(zone)
    tld = (sender or "").rsplit(".", 1)[-1].lower()
    return ZoneInfo(TLD.get(tld, "Europe/Berlin"))


def load_calendar():
    with open(CAL_PATH) as f:
        cal = json.load(f)
    tz = ZoneInfo(cal["timezone"])
    busy = [(dt.datetime.fromisoformat(b["start"]).replace(tzinfo=tz), dt.datetime.fromisoformat(b["end"]).replace(tzinfo=tz))
            for b in cal.get("busy", [])]
    ics = os.environ.get("FORWARDER_ICS")
    if ics and os.path.exists(ics):
        with open(ics) as f:
            busy += _ics_busy(f.read())
    return cal, tz, busy


def _ics_busy(text):
    """Minimal .ics reader: DTSTART/DTEND of each VEVENT (UTC 'Z' or local with TZID)."""
    out = []
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
        def t(key):
            m = re.search(r"^%s(?:;TZID=([^:]+))?:(\d{8}T\d{6})(Z?)" % key, ev, re.M)
            if not m:
                return None
            zone = dt.timezone.utc if m.group(3) else ZoneInfo(m.group(1) or "Europe/Berlin")
            return dt.datetime.strptime(m.group(2), "%Y%m%dT%H%M%S").replace(tzinfo=zone)
        s, e = t("DTSTART"), t("DTEND")
        if s and e:
            out.append((s, e))
    return out


def free_slots(customer_tz, now=None, n=3, days=7):
    """Up to n free slots, at most one per day, polite for both sides. Returns aware datetimes (forwarder tz)."""
    cal, tz, busy = load_calendar()
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    step = dt.timedelta(minutes=cal["slot_minutes"])
    start_h, end_h = [dt.time.fromisoformat(x) for x in cal["working_hours"]]
    earliest = now + dt.timedelta(hours=cal.get("min_notice_hours", 2))
    slots = []
    for d in range(days + 1):
        day = (now + dt.timedelta(days=d)).date()
        if day.weekday() not in cal["working_days"]:
            continue
        t = dt.datetime.combine(day, start_h, tz)
        while t + step <= dt.datetime.combine(day, end_h, tz):
            local = t.astimezone(customer_tz)
            end_local = local + step
            ok = (t >= earliest and local.time() >= dt.time(CUSTOMER_HOURS[0])
                  and end_local.date() == local.date() and end_local.time() <= dt.time(CUSTOMER_HOURS[1])
                  and local.weekday() < 5 and not any(t < e and t + step > s for s, e in busy))
            if ok:
                slots.append(t)
                break                                   # one per day, so the customer gets a real choice
            t += step
        if len(slots) == n:
            break
    return slots, cal


def fmt(slot, customer_tz, lang="en"):
    local = slot.astimezone(customer_tz)
    berlin = slot.astimezone(ZoneInfo("Europe/Berlin"))
    days_de = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    if lang == "de":
        s = "%s %s, %s Uhr" % (days_de[local.weekday()], local.strftime("%d.%m."), local.strftime("%H:%M"))
    else:
        s = local.strftime("%a %d %b, %H:%M")
    name = local.tzname() or ""
    s += " (%s)" % name
    if local.utcoffset() != berlin.utcoffset():
        s += " = %s %s" % (berlin.strftime("%H:%M"), berlin.tzname())
    return s
