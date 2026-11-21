# CLAUDE.md: rules for every agent in this repo

4 people, 4 Claude Code agents, one repo. Read this before you change anything.

## What we build
A digital air forwarder for the 5U challenge. One Python program polls the 5U mailbox, routes each mail,
prices RFQs, replies in the thread, books, and answers tracking. Details: `docs/5u-challenge.md`, API: `docs/api.md`.
Score per quote: price 45 (only within 5% of best counts), LLM cost 40 (full at $0, zero at $0.10),
time 15 (full under 2 min). First RFQ Sat 16:00. Setup changes hourly without notice.

## Golden rules
1. **Only Erik's MacBook sends mail.** It is the runner. Everyone else runs with `DRY_RUN=1` (the default).
   Only the first quote in a thread counts, so a second machine sending can burn an RFQ.
2. **Stay in your folder.** Do not edit another owner's folder. Need a change there? Ask that person.
3. **`git pull` before you start, small commits to `main` often.** Only push code that runs. No long branches.
4. **Never commit keys.** Keys live in `.env` (git-ignored). Template: `env.example`.
5. **LLM calls go only through the 5U gateway (OpenAI models).** Rules and code first, LLM only where language
   is needed. Each quote must make exactly one gateway call (no call = no cost points). Set `max_tokens`.
6. **Log every decision** (mail in, route, all price options, chosen one, mail out) to the shared SQLite DB,
   so we can debug failed quotes with `GET /v1/board/me`.
7. **GitHub issues are the agent chat.** Run `gh issue list` when you start and after every `git pull`. To tell another
   agent something, open an issue: say who it is for in the first line, what to do, and the deadline. Answer in the
   issue and close it when done. Humans still decide who owns what.

## Folder ownership
| Folder | What | Owner |
|---|---|---|
| `core/` | main loop: poll mailbox (`since_id`), DRY_RUN, send replies, SQLite DB + event log (v1 exists) | TBD |
| `router/` | sort each mail by sender/attachment (rules, no LLM): RFQ, follow-up, carrier bid, ratedesk, tracking, tariff | TBD |
| `pricing/` | tariff parsing + price math from sheets (exists) | TBD |
| `sourcing/` | rate portal API (rate_id, 429 handling), carrier/trucker bid requests + bid parsing, booking | TBD |
| `llm/` | gateway client, RFQ extraction (JSON) + reply text with `{PRICE}` placeholder, tracking replies | TBD |
| `ui/` | sessions UI (Streamlit) reading the DB. Only after the main loop works | later |
| `shared/` | tiny shared types. Frozen after first commit; change only after telling the team | TBD |

## Flow (one RFQ)
mail in → router → llm extracts fields + reply template → pricing (sheets) + sourcing (portal, bids, wait `BID_WAIT_S`
from RFQ arrival, not for lanes already covered) → pick cheapest or fastest as the customer asked → fill `{PRICE}`
→ core sends reply with `in_reply_to` → log. Door-to-port: postcode zone → airport (`pickup_zones.csv`) + trucker bid.

## Pricing facts (start kit)
chargeable = max(kg, cbm × 167) · freight = max(min_charge, rate(bracket) × chargeable) · + (fuel + security) × billed kg.
A higher weight break can be cheaper (90 kg vs billed 100 kg). Keep that behind a flag until 5U confirms the scorer uses it.

## Open questions for the 5U booth
- Does the scorer use the cheaper higher weight break?
- Does a clarifying question count as our first reply?
- Are non-OpenAI models allowed outside the gateway?

## What exists now (the clerk, v1)
`core/main.py` is the one loop. It polls the mailbox, saves each mail, asks `router/route.py` for the route, and calls
`HANDLERS[route](mail)`. Today only `rfq` is handled: one gateway call (`llm/extract.py`) → price from sheets
(`pricing/price.py`) + portal (`sourcing/portal.py`) → cheapest or fastest → one reply in the thread.
When it cannot price safely (missing data, no lane, door pickup) it sets the session to `needs_human` and sends nothing.

| File | Job |
|---|---|
| `core/config.py` | every setting (env vars). Read this first |
| `core/db.py` | SQLite tables `mails`, `sessions`, `bids`, `events`, `state`. `db.event(...)` logs a step |
| `core/mailbox.py` | `api()`, `poll()`, `send()` (respects DRY_RUN). Only place that sends mail |
| `core/main.py` | loop, `HANDLERS`, `handle_rfq`, `finalize`, `tick` (bid wait) |
| `core/stats.py` | `python -m core.stats`: seconds to quote, bid answer times, LLM cost |
| `router/route.py` | rules by sender: rfq, follow_up, carrier_bid, tariff, ratedesk, tracking, booking_confirmation |
| `llm/extract.py` | the one gateway call: fields as JSON + reply with `{PRICE}` `{AIRLINE}` `{TRANSIT_DAYS}` |
| `sourcing/portal.py` | portal rates for a lane, with `rate_id` |

**Not checked against the live API yet** (no key on the machine that wrote it): field names of incoming mails
(`mailbox.normalize` accepts several), the `airline` parameter of the portal (we send the 2-letter code), the model name.
Erik: run `DRY_RUN=1 LLM_FAKE=0 python -m core.main` once before 16:00 and fix what the log shows.

## How to plug in (do not edit `core/` for this, except one line in `HANDLERS`)
- **New route** (follow-up/booking, tracking, tariff, ratedesk): write `def handle(mail)` in your folder, then add
  `"tracking": yourmodule.handle` to `HANDLERS` in `core/main.py`. Send only with `mailbox.send(...)`. Log with `db.event(...)`.
- **Bids** (`sourcing/bids.py`, not built yet). The loop already calls it when the file exists:
  - `request(session, fields) -> int`: mail the carriers/truckers, insert one `bids` row each (`requested_at`), return how many.
  - `on_reply(mail)`: parse the bid, fill `replied_at`, `total`, `currency`, `transit_days` on that row.
  - `final_options(thread_id, options) -> options`: add the bids (and the trucker leg) to the price options.
  The loop quotes when all bids are in or the wait is over, whichever is first.
- An option is a dict with `airline, total, currency, total_eur, transit_days, source` (+ `rate_id` from the portal).

## Bid wait: 90 s is a start value, not settled
`BID_WAIT_S` (default 90, counted from RFQ arrival) is a guess. Do not treat it as decided and do not hard-code it anywhere.
After the first real mails, run `python -m core.stats`, look at how fast bids really come back, and set it with the
env var. Time score: full under 120 s, zero at 360 s. Change it in `.env` on Erik's MacBook, then tell the team.

## Run
```bash
cp env.example .env   # fill in keys (Erik only for live)
DRY_RUN=1 python3 -m core.main                 # everyone: reads the mailbox, never sends, never calls the gateway
DRY_RUN=1 LLM_FAKE=0 python3 -m core.main      # also call the real gateway (costs money, use rarely)
DRY_RUN=0 caffeinate -i python3 -m core.main   # Erik's MacBook only, ONE process
python3 -m core.main --fake examples/rfq.json  # no key, no network: one fake mail through the whole loop
python3 -m core.stats                          # numbers to calibrate with
python3 -m pricing.price FRA LAX 120 0.9       # price check
```
No extra packages needed (standard library only, Python 3.9+).
