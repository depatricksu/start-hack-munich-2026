# RFQ template: what every request must contain

Code: [`shared/rfq.py`](../shared/rfq.py) · Tests: [`tests/test_rfq.py`](../tests/test_rfq.py)

Every incoming customer mail is turned into one `RFQ` object, then checked by `validate()`.
The check decides what happens next **before** any LLM money is spent.

```python
from shared.rfq import extract_rfq, validate, missing_fields, can_price

rfq = extract_rfq(subject, body, message_id=m["id"], customer_email=m["from"], received_at=m["date"])
issues = validate(rfq)
if missing_fields(issues):      # 1 cheap LLM call: fill ONLY these fields, then validate again
    ...
if can_price(issues):           # go to pricing
    ...
```

## The fields

| Field | Level | Example | Why it matters | If missing |
|---|---|---|---|---|
| `message_id` | envelope | `msg_123` | reply needs `in_reply_to`, only first reply counts | bug in poller |
| `customer_email` | envelope | `buyer@acme.hackloop.mail` | who we answer | bug in poller |
| `received_at` | envelope | `2026-11-21T16:00:04Z` | starts the 6-min clock | bug in poller |
| `origin` | **required** | `MUC` | one of FRA MUC DUS HAM STR CGN | derive from `pickup_postcode`, else LLM fill |
| `destination` | **required** | `LAX` | must be served by someone | LLM fill |
| `weight_kg` | **required** | `230` | basis of every price | LLM fill |
| `mode` | **required** | `cheapest` / `fastest` | decides which option we quote | default `cheapest` + warning |
| `volume_cbm` | recommended | `1.2` | chargeable = max(kg, cbm × 167) | from `pieces × dims_cm`, else warning |
| `pieces` | recommended | `3` | needed to turn dims into cbm | – |
| `dims_cm` | recommended | `(120, 80, 100)` | one piece, L × W × H in cm | – |
| `service` | door-to-port | `door_to_port` | adds a trucker leg | default airport-to-airport |
| `pickup_postcode` | door-to-port | `80331` | first 2 digits = zone → airport (`pickup_zones.csv`) | **required** when door-to-port |
| `dangerous_goods` | scope | `true` | out of scope | hand to a human |
| `currency_requested` | optional | `USD` | tariffs are EUR | warning |
| `commodity`, `ready_date`, `language` | optional | | nicer reply, reply in customer's language | – |
| `chargeable_kg`, `pickup_zone` | derived | `230.0`, `80` | filled by `normalize()` | – |

## Issue levels

| Level | Meaning | Action |
|---|---|---|
| `missing` | cannot price | one LLM call for exactly these fields; still missing → ask the customer (see open question in CLAUDE.md: does that count as our first reply?) |
| `warning` | can price, but risky (no volume, odd density, no mode, currency, origin vs pickup zone mismatch) | price it, show the warning in the sessions UI |
| `human` | out of scope (dangerous goods, unknown origin/destination/zone) | hand over to a person, do not auto-quote |

## Checks done by `validate()`

- origin is one of the 6 export airports, destination is served by someone (carrier list + portal lanes)
- weight between 0 and 50 000 kg
- density `kg / cbm` between 10 and 2000 (catches cm-vs-m mix-ups)
- door-to-port: postcode zone exists and its airport matches the stated origin
- dangerous goods, non-EUR currency

## What the free regex extractor understands

IATA codes and city names (EN/DE, e.g. *München*, *Köln*, *Tokio*), `kg`, `cbm`/`m3`, `pcs`/`pallets`/`Paletten`,
`120x80x100 cm`, decimal commas (`1.234,5`), *cheapest/günstigste* vs *fastest/urgent/eilig*,
pickup postcodes next to *pick up/abholen/collect/door*, *DGR/UN1234/lithium/Gefahrgut*.

Anything it misses shows up as `missing` and goes to the single LLM call.
