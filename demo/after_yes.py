"""After the yes: the messages a forwarder still writes by hand, built from the agent's own records.

Pitch demo only. Reads the runner's database READ-ONLY, sends nothing, makes no gateway call,
and is not imported by core/. For every confirmed booking it drafts what goes out after the customer
accepts: the pickup order to the chosen trucker, shipment details to the airline, a thank-you to the
carriers we did not pick, next steps to the customer, a pre-alert for the destination partner, and the
status mails during the trip.

    python3 -m core.share --get                                   # newest runner snapshot
    DB_PATH=examples/real/snapshot.db python3 -m demo.after_yes   # writes demo/out/after-the-yes.html
    python3 -m demo.after_yes --db path/to.db --out page.html --json data.json
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
CARRIERS = os.path.join(ROOT, "kit", "start-kit", "carrier-list.csv")
OUR_NAME = "Lena"  # the signature our quote mails use


def _j(text):
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


def _money(v):
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v or "")


def _carrier_emails():
    out = {}
    if os.path.exists(CARRIERS):
        with open(CARRIERS, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    out[parts[0]] = parts[2]
    return out


# ---- highlighting: f = from our record, o = still open, s = arrives later (sample) -------------
def F(v):
    return f'<span class="f">{html.escape(str(v))}</span>'


def O(v):
    return f'<span class="h">{html.escape(str(v))}</span>'


def T(v):
    return html.escape(str(v))


def _ready_date(first_body):
    m = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", first_body or "")
    if m:
        try:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    return None


def _first_name(fields):
    name = fields.get("customer_first_name")
    if name:
        return name
    for line in fields.get("customer_lines") or []:
        words = line.replace(",", " ").split()
        if len(words) >= 2 and words[0][:1].isupper() and words[0].lower() not in (
                "best", "kind", "cheers", "regards", "thanks", "many", "mit", "viele", "beste"):
            return words[0]
    return None


def _company(fields, customer):
    for line in fields.get("customer_lines") or []:
        if re.search(r"\b(GmbH|AG|KG|Ltd|SE|S\.p\.A|SAS|SL|Inc)\b", line):
            return line.strip()
    return customer.split("@")[0].replace("-", " ").title()


def _contact(fields):
    lines = fields.get("customer_lines") or []
    for line in lines:
        if _first_name(fields) and line.startswith(_first_name(fields)):
            return line.strip()
    return _first_name(fields) or "the shipper"


GENERIC = {"shipment", "goods", "cargo", "the shipment", "the goods", "freight", "it", "they"}
GOODS_PATTERNS = [
    r"\bpieces of ([a-z][a-z \-]{2,40}?)(?:[,.:;]| with| ready| for| to| from)",
    r"\bfor ([a-z][a-z \-]{2,40}?)\?",
    r"\bimporting (?:some )?([a-z][a-z \-]{2,40}?) from",
    r"\bcargo is ([a-z][a-z \-]{2,40}?)(?:[,.]| packed)",
    r"\b[Tt]he ([a-z][a-z \-]{2,40}?) (?:will be|are|is) ready",
    r"\bshipment of ([a-z][a-z \-]{2,40}?)(?:[,.]| to| from| with)",
]


def _goods(first_body, fields):
    """The goods as the customer wrote them; 'general cargo' when the mail never says."""
    for pat in GOODS_PATTERNS:
        for m in re.finditer(pat, first_body or ""):
            g = re.sub(r"^(our|some|the|these) ", "", m.group(1).strip())
            if g.lower() not in GENERIC and not re.search(r"piece|option|import|export|shipment", g):
                return g
    return "general cargo"


def load(db_path):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    emails = _carrier_emails()
    shipments = []
    for b in q("SELECT * FROM bookings WHERE status='confirmed' ORDER BY confirmed_at"):
        tid = b["thread_id"]
        s = q("SELECT * FROM sessions WHERE thread_id=?", tid)
        if not s:
            continue
        s = s[0]
        fields, chosen = _j(s["fields"]), _j(s["chosen"])
        mails = q("SELECT id, sender, subject, body, received_at FROM mails WHERE thread_id=? ORDER BY id", tid)
        first = mails[0] if mails else None
        yes = next((m for m in mails if m["id"] == b["last_customer_mail_id"]), None)
        bids = q("SELECT carrier, kind, status, total, currency, hours, transit_days, email, raw "
                 "FROM bids WHERE thread_id=? AND status='ok'", tid)
        shipments.append(build(b, s, fields, chosen, first, yes, bids, emails))
    con.close()
    return shipments


def build(b, s, fields, chosen, first, yes, bids, emails):
    first_body = first["body"] if first else ""
    ready = _ready_date(first_body)
    name = _first_name(fields) or "there"
    company = _company(fields, b["customer"])
    goods = _goods(first_body, fields)
    pieces = sum(int(p.get("count") or 0) for p in fields.get("pieces") or []) or None
    kg = float(b["weight_kg"] or fields.get("weight_kg_total") or fields.get("weight_kg") or 0)
    cbm = float(b["volume_cbm"] or fields.get("volume_cbm_total") or fields.get("volume_cbm") or 0) or None
    postcode = fields.get("pickup_postcode")
    city = fields.get("customer_city") or ""
    dg = fields.get("dg") or fields.get("dangerous_goods")
    dg_text = "dangerous goods, DG papers attached" if dg else "not dangerous"
    trucker = chosen.get("trucker")
    flight = chosen.get("flight_total") or chosen.get("total")
    transit = b["transit_days"] or chosen.get("transit_days")
    ready_s = ready.strftime("%d %b %Y") if ready else None
    arrive = (ready + dt.timedelta(days=int(transit))) if (ready and transit) else None
    ref = b["team_reference"]
    bk = b["booking_reference"]
    lane = f'{b["origin"]} → {b["destination"]}'
    t0 = b["booked_at"] or b["confirmed_at"]
    at = lambda sec: dt.datetime.fromtimestamp(t0 + sec).strftime("%H:%M:%S") if t0 else ""
    tbid = next((x for x in bids if x["kind"] == "trucker" and x["carrier"] == trucker), None)
    offer_ref = re.search(r"\b(TRK-\d+)\b", (tbid["raw"] if tbid else "") or "")
    losers = [x for x in bids if x["carrier"] not in (trucker, b["airline"]) and x["kind"] in ("trucker", "airline")]
    who = F(name)
    goods_line = f"{F(goods)}, {F(str(pieces) + ' pcs') if pieces else O('pieces open')}, {F(f'{kg:g} kg')}, {F(f'{cbm:g} m³') if cbm else O('volume open')}"

    msgs = []
    if trucker:
        msgs.append(dict(
            id="truck", phase=0, at=at(2), to="TRUCKER", tag="CONCEPT",
            title="Pickup order to the chosen trucker",
            who=f"{trucker}, picked from {sum(1 for x in bids if x['kind'] == 'trucker')} trucker offers for this request.",
            ai="None. Every line comes from the record.",
            today="The trucker only got our price request. The forwarder writes the order by hand.",
            uses=["shipper", "pickup", "ready", "pieces", "weight", "goods", "dg", "airline", "booking", "trucker", "cost"],
            out="\n".join([
                f"To: {T(tbid['email'] if tbid and tbid['email'] else trucker)}",
                f"Subject: Pickup order {T(ref)} · {F(postcode or city)} → {F(b['origin'])} · {F(ready_s) if ready_s else O('date open')}",
                "",
                f"Hello, thank you for your offer {F(offer_ref.group(1)) + ' ' if offer_ref else ''}of {F(_money(chosen.get('trucker_total')) + ' ' + (chosen.get('trucker_currency') or 'EUR'))}. We confirm:",
                "",
                f"Collect   {F(company)}, {F(postcode or '')} {F(city)}",
                f"Contact   {F(_contact(fields))}",
                f"From      {F(ready_s) if ready_s else O('ready date open')}",
                f"Goods     {goods_line}, {F(dg_text)}",
                f"Deliver   {F(b['origin'])} airport, {F(b['airline'])} cargo terminal",
                f"Booking   {F(bk)}",
                "",
                f"Please reply with the driver's arrival window. Ref {T(ref)}.",
            ])))
    msgs.append(dict(
        id="airline", phase=0, at=at(3), to="AIRLINE", tag="CONCEPT",
        title="Shipment details for the booking",
        who=f"{b['airline']}. The portal booking only carries lane, weight and volume.",
        ai="None. Open fields are marked and sent again when the customer's papers arrive.",
        today="The forwarder retypes shipper, goods and truck delivery into the airline's system or a mail.",
        uses=["shipper", "pieces", "weight", "goods", "dg", "airline", "booking", "trucker", "ready"],
        out="\n".join([
            f"To: {T(emails.get(b['airline'], b['airline']))}",
            f"Subject: {F(bk)} · shipment details · {T(ref)}",
            "",
            f"Shipper     {F(company)}, {F(city)}",
            f"Consignee   {O('follows with the commercial invoice')}",
            f"Routing     {F(b['origin'])} → {F(b['destination'])}",
            f"Pieces      {F(pieces) if pieces else O('open')} · gross {F(f'{kg:g} kg')} · {F(f'{cbm:g} m³') if cbm else O('volume open')}",
            f"Goods       {F(goods)}, {F(dg_text)}",
            (f"Delivery    by truck ({F(trucker)}) to your {F(b['origin'])} terminal on {F(ready_s) if ready_s else O('date open')}"
             if trucker else f"Delivery    by the shipper to your {F(b['origin'])} terminal"),
            "",
            f"Please issue the air waybill to our reference {T(ref)}.",
        ])))
    if losers:
        names = ", ".join(sorted({x["carrier"] for x in losers}))
        msgs.append(dict(
            id="losers", phase=0, at=at(4), to="CARRIERS NOT CHOSEN", tag="CONCEPT",
            title=f"Thank the {len(losers)} bidders we did not pick",
            who=f"{names}: they all sent a price for this request.",
            ai="Writes one short, friendly line per carrier. No price is shared.",
            today="Usually nobody answers them. Carriers stop prioritising a forwarder who never closes the loop.",
            uses=["pickup", "ready", "booking"],
            out="\n".join(
                [f"To: {T(x['email'] or x['carrier'])}   (offered {_money(x['total'])} {T(x['currency'] or '')})" for x in losers]
                + ["", f"Subject: Your offer for {F(lane)}, our ref {T(ref)}",
                   "", "Hello,", "",
                   "thank you for your quick offer. This time the customer went",
                   "with another option, so we will not need it.",
                   "We will ask you again for the next one on this lane.", "",
                   f"Best regards, {OUR_NAME}"])))
    msgs.append(dict(
        id="customer", phase=0, at=at(5), to="CUSTOMER", tag="CONCEPT",
        title="What happens next, and which papers we need",
        who=f"A reply in {name}'s thread, in {b['language'] or 'en'}.",
        ai="Writes the wording, like the quote mails. The list of papers comes from code: whatever is still open.",
        today="The forwarder chases the Shipper's Letter of Instruction, invoice and packing list by phone and mail.",
        uses=["shipper", "goods", "ready", "trucker", "airline", "transit", "lang"],
        out="\n".join([
            f"To: {F(_contact(fields))}",
            f"Subject: Re: {T(first['subject'] if first else '')}",
            "", f"Hi {who},", "",
            (f"all set: {F(trucker)} collects the {F(goods)} on {F(ready_s) if ready_s else O('the ready date')}"
             if trucker else f"all set: please deliver the {F(goods)} to {F(b['airline'])} at {F(b['origin'])}"),
            f"and they fly with {F(b['airline'])}, about {F(transit)} days to {F(b['destination'])}.",
            "", "Could you reply with these, so customs and the airline have them?",
            "  1. Commercial invoice (value and HS codes)",
            "  2. Packing list",
            "  3. Shipper's Letter of Instruction",
            f"  4. Consignee name and address at {F(b['destination'])}",
            "", "I will write again when the goods are on their way.",
            f"Best regards, {OUR_NAME}",
        ])))
    msgs.append(dict(
        id="prealert", phase=1, at="when papers arrive", to="DESTINATION PARTNER", tag="CONCEPT",
        title="Pre-alert to the partner at destination",
        who=f"Our partner forwarder at {b['destination']}, who clears import and delivers.",
        ai="One small call reads the customer's invoice into consignee and HS code; code checks weight and pieces against the record.",
        today="Sent by hand after departure, often without the HS code the import side needs.",
        uses=["shipper", "pieces", "weight", "goods", "airline", "booking", "transit", "ready"],
        out="\n".join([
            f"To: partner forwarder, {F(b['destination'])}",
            f"Subject: Pre-alert {F(lane)} · {F(b['airline_code'] or b['airline'])} · {F(bk)}",
            "",
            f"Departs {F(ready_s) if ready_s else O('date open')}, arrives about {F(arrive.strftime('%d %b')) if arrive else O('open')}.",
            f"Shipper    {F(company)}",
            f"Consignee  {O('from the invoice')}",
            f"Goods      {goods_line}, {F(dg_text)}",
            f"HS code    {O('from the invoice')}",
            "Docs       invoice and packing list attached",
        ])))
    if trucker:
        msgs.append(dict(
            id="remind", phase=1, at="day before pickup", to="TRUCKER → CUSTOMER", tag="CONCEPT",
            title="Day-before check with the trucker",
            who="The trucker confirms the window; the customer gets it the same minute.",
            ai="Reads the trucker's free-text answer. Code passes the time window on.",
            today="Phone calls in both directions the afternoon before pickup.",
            uses=["pickup", "ready", "trucker", "shipper", "lang"],
            out="\n".join([
                f"→ To: {F(trucker)}",
                f"  Reminder: pickup {F(ready_s) if ready_s else O('date open')}, {F(postcode or '')} {F(city)}, ref {T(ref)}.",
                "  What time will the driver be there?", "",
                f"← {T(trucker)}: {O('driver window, e.g. 9 to 11')}", "",
                f"→ To: {F(_contact(fields))}",
                f"  Hi {who}, the driver from {F(trucker)} comes between [window].",
                f"  Please have the {F(str(pieces) + ' pieces') if pieces else 'goods'} ready.",
            ])))
    msgs.append(dict(
        id="status", phase=2, at="pickup to arrival", to="CUSTOMER", tag="CONCEPT",
        title="Status mails before the customer has to ask",
        who=f"{name}, at each step: at the airport, departed, arrived.",
        ai="Reads the trucker's receipt and the airline's status mails. A delay of a day or more waits for a person first.",
        today="The customer asks \"where is it?\", someone looks it up and answers.",
        uses=["pieces", "airline", "booking", "transit", "shipper", "lang"],
        out="\n".join([
            f"{F(ready_s) if ready_s else O('pickup day')}  Your {F(goods)} are at {F(b['origin'])} airport with {F(b['airline'])} (booking {F(bk)}).",
            "            Next update when the flight leaves.",
            f"departure   The flight to {F(b['destination'])} has left. Arrival about {F(arrive.strftime('%d %b')) if arrive else O('open')}.",
            f"delay ≥ 24h {O('draft only: a person approves the new arrival date')}",
            f"arrival     Landed at {F(b['destination'])}. Our partner handles import and delivery.",
        ])))

    return dict(
        ref=ref, thread=b["thread_id"], lane=lane, origin=b["origin"], destination=b["destination"],
        record=dict(shipper=f"{company} · {_contact(fields)}", pickup=(f"{postcode} {city}".strip() if trucker else "shipper delivers"),
                    ready=ready_s or "open", pieces=str(pieces or "open"), weight=f"{kg:g} kg · {cbm:g} m³" if cbm else f"{kg:g} kg",
                    goods=goods, dg=dg_text, airline=f"{b['airline']} ({b['airline_code'] or ''})", booking=bk,
                    trucker=(trucker or "none (self-delivery)"), transit=f"{transit} days" if transit else "open",
                    cost=f"{_money(flight)} + {_money(chosen.get('trucker_total'))}" if trucker else _money(flight),
                    lang=b["language"] or "en"),
        price=f"{_money(b['price'])} {b['currency'] or 'EUR'}" if not trucker else f"{_money(chosen.get('total'))} {b['currency'] or 'EUR'}",
        request_at=dt.datetime.fromtimestamp(first["received_at"]).strftime("%H:%M:%S") if first else "",
        request=(first_body or "")[:240],
        yes_at=dt.datetime.fromtimestamp(yes["received_at"]).strftime("%H:%M:%S") if yes else "",
        yes=(yes["body"] if yes else "").split("\n")[0][:160],
        to_confirmed=round(t0 - first["received_at"]) if (first and t0) else None,
        messages=msgs,
    )


def main(argv=None):
    from core import config  # only for the default DB path
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=os.environ.get("DB_PATH", config.DB_PATH))
    ap.add_argument("--out", default=os.path.join(HERE, "out", "after-the-yes.html"))
    ap.add_argument("--json", default=None, help="also write the data as JSON")
    ap.add_argument("--featured", type=int, default=9869, help="thread shown first (default: request 9869)")
    a = ap.parse_args(argv)
    shipments = load(a.db)
    if not shipments:
        raise SystemExit(f"no confirmed bookings in {a.db}")
    shipments.sort(key=lambda x: (x["thread"] != a.featured, -len(x["messages"])))
    stats = dict(bookings=len(shipments), messages=sum(len(x["messages"]) for x in shipments),
                 bidders=sum(len([m for m in x["messages"] if m["id"] == "losers"]) for x in shipments),
                 trucked=sum(1 for x in shipments if any(m["id"] == "truck" for m in x["messages"])),
                 db=os.path.basename(a.db), generated=dt.datetime.now().strftime("%d %b %H:%M"))
    data = json.dumps(dict(stats=stats, shipments=shipments), ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        page = f.read().replace("/*DATA*/null", data)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            f.write(data)
    print(f"{stats['bookings']} confirmed bookings → {stats['messages']} messages drafted, nothing sent. Wrote {a.out}")


if __name__ == "__main__":
    main()
