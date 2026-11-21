# 5U API cheat sheet

Base URL `https://api.start-hack.5u.ai` · Swagger `/docs` · spec in `docs/openapi.json`
Auth: header `X-API-Key: <team key>` (or `Authorization: Bearer`). One key for mailbox, portal, gateway. Never commit it.
Mailbox of the team: `google@hackloop.mail`. First request at 16:00 Sat.

## Mailbox
- `GET /v1/mailbox/messages?since_id=N&limit=200` poll, oldest first. No push. Keep `next_since_id`. Poll every 1 to 2 s, response time is scored.
- `POST /v1/mailbox/messages` send `{to, subject, body, in_reply_to, attachments[]}`. 60 mails/min, then 429.
  - Quote counts only as a reply (`in_reply_to`) in a thread a customer started. Only the first quote in a thread counts.
  - Allowed recipients: customers, carriers in `carrier-list.csv`, `ratedesk@hackloop.mail`, `tracking@hackloop.mail`. Others get 422.
- `GET /v1/mailbox/messages/{id}` and `/attachments/{att_id}` read one mail, download an attachment.
- Everything arrives here: customer RFQs, carrier bids, rate desk answers, booking confirmations, monthly airline tariffs, tracking questions.

## Rate portal
- `GET /v1/portal/ports` lanes and airlines the portal prices. Lanes not listed are priced by email to the airline.
- `GET /v1/portal/brackets?airline=` weight breaks. 404 means "email the airline".
- `GET /v1/portal/rates?origin&destination&airline&weight_kg&volume_cbm` returns a `rate_id`, valid 15 min. Rate limited per minute (see `X-RateLimit-*`, 429 + `Retry-After`).
- `POST /v1/portal/bookings {rate_id, team_reference}`. 201 booked, 200 retry, 404 unknown, 409 booked under another reference, 410 expired, 503 down (book by email). Confirmation mail "Booking BK-... confirmed" follows. No status call: keep bookings in our own CRM.

## LLM gateway (OpenAI models only)
1. Once: `POST /v1/gateway/openai-key {"api_key":"sk-..."}` with the team key. Our own OpenAI key.
2. OpenAI SDK with `base_url=<base>/v1/gateway`, `api_key=<team key>`. Chat completions, responses, embeddings, streaming.
3. A quote made without a gateway call earns no cost points.

## Board
- `GET /v1/board` public leaderboard. `GET /v1/board/me` our result per request (verdict, reason code, points). Use it to debug failed quotes.

## Scoring (brief is right, deck is now aligned)
Price 45 (accepted = within 5% of best), LLM cost 40 (full at 0, zero at 0.10 USD per quote), time 15 (full at 2 min, zero at 6). +10 tracking, +10 jury for most human email.

## Pricing rules seen in the start kit (verify per sheet)
- Rate per kg by weight bracket x chargeable weight. Chargeable = max(actual kg, cbm x 167).
- Minimum charge applies to freight before surcharges.
- Fuel and security surcharges are per kg of billed weight, on top.
- Door-to-port: `pickup_zones.csv` maps a German postcode zone to FRA, MUC, DUS, HAM, STR or CGN. Truckers in `carrier-list.csv` cover zones.
- Tariff formats are mixed: PDF, XLSX, DOCX, TXT and JPG pages.

## Where each airline is priced (checked 21 Nov 14:10 with the team key)
- 15 airlines are on the portal API (114 lanes, 6 German origins, 36 destinations): Aurelia, Borealis, Fjordline, Gannet, Ibisair, Juniper, Lumen, Meridian, Nova Atlas, Polaris, Riverbend, Solace, Tamarind, Ultraviolet, Xenon. Lanes in `docs/portal-lanes.json`.
- 10 airlines are only in the start kit sheets: Cobalt, Danube Wings, Elbflug, Helix, Kestrel, Orion, Quetzal, Vega, Wayzata, Yellowtail.
- 4 airlines serve only exotic destinations (ASU KTM PPT TNR ULN) and are priced by email: Zephyr Steppe, Himalaya Bridge, Lagoon Isles, Pampero.
- Truckers are priced by email for the door-to-port leg.
- Mailbox was empty before 16:00. Team mailbox `google@hackloop.mail`.
