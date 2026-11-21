# Who answers at 2 a.m.? A digital air forwarder

**Team Google · START Hack Munich 2026 · 5U AI challenge**

One mailbox, a new air-export request every 6 minutes, all night. This program reads every mail, prices every
request from rate sheets, the rate portal and carrier bids, replies in the customer's thread with one all-in total,
books on acceptance, answers tracking questions, and hands the judgement calls to a person.

> **Our rule:** code does the math, AI reads the mail, people make the calls.
> One small gateway call per quote. Prices never come from the model. When something is unclear, the session goes to
> `needs_human` instead of a guess, because only the first quote in a thread counts.

## How one request flows

```
mail in ─► router ─► one gateway call ─► gate ─► price ─► pick ─► reply in thread ─► book ─► track
            rules     fields as JSON    stop or   sheets   cheapest   one all-in      rate ID   from our
            by sender (+ reply text)    warn      portal   fastest    total + DG      on accept own CRM
                                                  bids     balanced   paragraph
                         ▲                                                  │
              attachments: DG declaration,                         unsure ─► needs_human ─► control room
              packing-list weight/volume (dg/)                                              "send as human"
```

| Step | Where | What it does |
|---|---|---|
| Poll, log, send | `core/` | The one loop: polls the mailbox, saves every mail and decision to SQLite, the only place that sends mail |
| Route | `router/` | Rules by sender and subject, no LLM: RFQ, follow-up, carrier bid, rate desk, tracking, tariff, booking |
| Read | `llm/` | The single gateway call: the RFQ as JSON + reply text with `{PRICE}` placeholders; language detection; a quality gate on every reply |
| Gate | `shared/rfq.py` | Stops or warns with reason codes: missing data, multi-shipment, unclear request |
| Price | `pricing/` | Tariffs from the 10 rate sheets (PDF, XLSX, DOCX, TXT, and two JPG pages transcribed by hand), chargeable weight, minimums, every weight break; live tariff mails update prices |
| Source | `sourcing/` | Rate portal (rate IDs, deeper weight breaks, rate limits, FX), carrier and trucker bids by mail, balanced 50/50 pick |
| Dangerous goods | `dg/` | Reads attachments (xlsx, docx, pdf), finds UN number / class, adds the DG paragraph to the quote; compares packing-list weight and volume with the mail |
| Book and track | `booking/` | Book by rate ID on acceptance, keep the customer informed, answer tracking from our own bookings |
| Take over | `actions/` + `ui/` | Next.js control room: sessions with status and countdown, live event stream, "send as human" |
| Learn and watch | `learn/`, `monitor/`, `core/alarm.py` | Inverts the scorer's points to find its best price, diffs 5U's setup every minute, posts alarms with the full log into the team chat |
| Audit | `audit/` | Re-parses every rate sheet independently and diffs it with `pricing/tariffs.json` |

## What the night taught us

We treated the public leaderboard as data. Each finding became a fix within minutes:

| Finding | Evidence | Fix |
|---|---|---|
| The scorer prices at a higher weight break when it is cheaper per kilo | Leaders booked 676 kg as 1,000 kg and 1,233 kg as 2,000 kg | Price every higher bracket, sheets and portal |
| The scorer picks the **balanced** trucker (price and speed 50/50), not the cheapest | Round 4 reproduced to the cent | `BID_PICK=balanced` |
| Accuracy is symmetric: too low is rejected like too high | `too_low` verdict, round 9 | Count every lot; never drop a leg |
| 5U's hourly change at 17:00: dangerous goods declared only in the attachment | `dg_docs_missing`, rounds 10–11 | `dg/`: read attachments, quote with the DG documents paragraph |
| A USD portal price without an exchange rate was labelled EUR | ~8 % off | Keep the currency, flag `fx_missing` |

## Running it

Python 3.9+, standard library only. Keys live in `.env` (see `env.example`), never in git.

```bash
python3 -m core.main --fake examples/rfq.json   # one fake mail through the whole loop, no key, no network
DRY_RUN=1 python3 -m core.main                  # read the live mailbox, never send
DRY_RUN=0 python3 -m core.supervise             # the one live runner: restarts the clerk after a crash
python3 -m core.restart --check                 # imports, all tests, a fake quote: is this code safe to go live?
python3 -m core.replay                          # today's code on every real request we got, vs 5U's points
python3 -m audit.sheets                         # rate sheets vs tariffs.json
python3 -m unittest discover -s tests           # 200+ tests
cd ui && npm install && npm run dev             # the control room
```

## How four people and four agents built it in one night

One repo, one folder per owner, small commits to `main`, and one rule: only the runner sends mail (`DRY_RUN=1`
everywhere else). The agents coordinate in a GitHub issue with four words: `CLAIM` before building, `DONE` with the
commit, `NEED` from another owner, `CHANGE` when a shared interface moves. A change goes live only through
`core.restart`, which runs the tests and a fake quote first and keeps the old code running if anything fails.
Rules for every agent: [`CLAUDE.md`](CLAUDE.md). Challenge brief: [`docs/5u-challenge.md`](docs/5u-challenge.md).
Event logistics: [`docs/event-notes.md`](docs/event-notes.md).
