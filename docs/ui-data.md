# What the sessions UI reads (UI data contract)

Source: SQLite `data/forwarder.db` written by `core/` (schema in `core/db.py`). The UI only reads it.
All times are Unix seconds (float). JSON columns are stored as text: parse them.

## One session = one customer request (table `sessions`, key `thread_id`)
| Column | Meaning | UI use |
|---|---|---|
| `thread_id` | id of the customer's first mail | session id, links to `mails` and `events` |
| `customer`, `subject` | sender address, subject | list row |
| `status` | see below | status chip, filters |
| `fields` (JSON) | extracted request: `origin`, `destination`, `pickup_postcode`, `weight_kg`, `volume_cbm`, `pieces[]`, `prefer` (`cheapest` or `fastest`), `missing[]`, `reply` | request card |
| `options` (JSON list) | every price found: `airline`, `total`, `currency`, `total_eur`, `transit_days`, `source` (`sheet`, `portal`, bid), `rate_id`, `valid_until` | price comparison table |
| `chosen` (JSON) | the option we quoted (same shape as an option) | quote card |
| `reply` | the email text we sent | thread view |
| `note` | why it is `needs_human`, `expired` or `failed` | red banner text |
| `received_at` | RFQ arrival | start of the clock |
| `deadline` | `received_at + BID_WAIT_S`: when we stop waiting for bids. NOT the expiry | "quote by" marker |
| `quoted_at` | when the quote left | response time = `quoted_at - received_at` |
| `llm_cost_usd` | our estimate of gateway spend | cost per quote |

**Expiry countdown** = `received_at + 360` (an RFQ expires 6 minutes after arrival). Time score: full under 120 s, zero at 360 s.

## Session status
`new` > `waiting_bids` > `sending` > `quoted`. Side exits: `needs_human` (could not price safely), `expired`, `failed`.
Not built yet: `booked` (needs the follow-up and booking handler).

## Thread view (tables `mails`, `events`)
- `mails`: every mail in, with `sender`, `subject`, `body`, `thread_id`, `route`, `received_at`.
- `events`, ordered by `id`, filter by `thread_id`: `ts`, `kind`, `data` (JSON). Kinds in use: `mail_in`, `llm`, `options`,
  `waiting_bids`, `bid_wait_over`, `quote_sent`, `quote_skipped_already_sent`, `mail_out`, `mail_out_dry_run`, `needs_human`,
  `rfq_expired`, `portal_error`, `error`. Global (no thread): `start`, `loop_error`.
- `bids`: one row per carrier or trucker we asked: `carrier`, `kind`, `requested_at`, `replied_at`, `total`, `currency`, `transit_days`.

## Dashboard numbers (all derived, no new tables)
Quotes sent = count `quoted`. Needs human = count `needs_human`. Median response = median of `quoted_at - received_at`.
Cost per quote = sum `llm_cost_usd` / count `quoted`. Bid answer time = `replied_at - requested_at` (`python -m core.stats` already does this).

## Score panel (not in the DB)
`GET {BASE_URL}/v1/board/me` with `X-API-Key`: per request the verdict (`accepted`, `rejected`, `pending`, `no answer`, `voided`),
reason code and points. Call it from the UI server, never from the browser (the key stays secret). Match rows to sessions by round and time.

## Proposed additions (need the `core/` owner to agree)
1. **Take-over.** The UI is read-only, so a human reply needs a table `actions(id, thread_id, kind, body, created_at, done_at)`.
   The UI inserts `kind='send_reply'` or `'pause'`; `core/` polls it and sends through `mailbox.send` (the only sender).
2. **Booking.** When the customer accepts: session `status='booked'` plus columns `booking_ref`, `rate_id`.
3. **Language.** Add `language` to `fields` (the extractor already replies in the customer's language).
4. **Reason code.** Keep `note` short and machine-friendly (for example `no_lane`, `missing_weight`, `door_pickup`, `rate_expired`)
   so the UI can show an icon, with the long text after a colon.
