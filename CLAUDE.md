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

## Folder ownership
| Folder | What | Owner |
|---|---|---|
| `core/` | main loop: poll mailbox (`since_id`), DRY_RUN, send replies, SQLite DB + event log | TBD |
| `router/` | sort each mail by sender/attachment (rules, no LLM): RFQ, follow-up, carrier bid, ratedesk, tracking, tariff | TBD |
| `pricing/` | tariff parsing + price math from sheets (exists) | TBD |
| `sourcing/` | rate portal API (rate_id, 429 handling), carrier/trucker bid requests + bid parsing, booking | TBD |
| `llm/` | gateway client, RFQ extraction (JSON) + reply text with `{PRICE}` placeholder, tracking replies | TBD |
| `ui/` | sessions UI (Streamlit) reading the DB. Only after the main loop works | later |
| `shared/` | tiny shared types. Frozen after first commit; change only after telling the team | TBD |

## Flow (one RFQ)
mail in → router → llm extracts fields + reply template → pricing (sheets) + sourcing (portal, bids, wait ~60–90 s
from RFQ arrival, not for lanes already covered) → pick cheapest or fastest as the customer asked → fill `{PRICE}`
→ core sends reply with `in_reply_to` → log. Door-to-port: postcode zone → airport (`pickup_zones.csv`) + trucker bid.

## Pricing facts (start kit)
chargeable = max(kg, cbm × 167) · freight = max(min_charge, rate(bracket) × chargeable) · + (fuel + security) × billed kg.
A higher weight break can be cheaper (90 kg vs billed 100 kg). Keep that behind a flag until 5U confirms the scorer uses it.

## Open questions for the 5U booth
- Does the scorer use the cheaper higher weight break?
- Does a clarifying question count as our first reply?
- Are non-OpenAI models allowed outside the gateway?

## Run
```bash
pip install -r requirements.txt
cp env.example .env   # fill in keys (Erik only for live)
DRY_RUN=1 python -m core.main          # everyone
DRY_RUN=0 caffeinate -i python -m core.main   # Erik's MacBook only
python -m pricing.price FRA LAX 120 0.9       # price check
```
