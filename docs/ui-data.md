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

**Trap: do not use `deadline` for the countdown.** `deadline` is when we stop waiting for carrier bids (arrival + 90 s by default).
If the countdown used `deadline`, it would show 90 seconds and say "expired" 4 minutes too early. Use arrival time plus 360 seconds.

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

## Stack: Next.js (decided by Erik, 21 Nov)
- `ui/` is a Next.js + Tailwind app. It runs on the same machine as the DB (the runner MacBook), so no separate API service is needed.
- Server route handlers open `data/forwarder.db` read-only with `better-sqlite3` (the DB is in WAL mode, so reads never block the loop).
- Live thread: a route handler streams new `events` rows to the browser (Server-Sent Events), polling the DB every second.
- Score panel: a route handler calls `/v1/board/me` with the key from the server env. The key never reaches the browser.
- Take-over writes only the `actions` table (proposal below). The UI never sends mail itself: only `core/` sends.

## The 4 additions the UI needs that the backend does not have yet
These need the `core/` owner to agree (they touch `core/`).
1. **Take-over.** You click "send my own reply" in the UI, but only the runner may send mail. So the UI writes a note into a new
   `actions` table (`id, thread_id, kind, body, created_at, done_at`: "send this text in thread X"; `kind` is `send_reply` or `pause`).
   The runner checks the table every second and sends it through `mailbox.send`.
2. **Booking.** When a customer accepts, the system books. The database needs a `booked` status and a booking reference
   (`booking_ref`, `rate_id`) so the screen can show them.
3. **Language.** DONE 21 Nov: `fields.language` (`en`, `de`, ...) is now filled by the extractor and the reply is written in it.
   The UI shows it as a flag.
4. **Reason codes.** When a case goes to a human, `note` is free text. Short codes like `missing_weight`, `no_lane`, `door_pickup`,
   `rate_expired` let the UI show an icon and a clear message. Format: `code: long text`.
