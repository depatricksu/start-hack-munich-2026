# 5U AI · "Who answers at 2 a.m.?"

Source: 5U challenge brief + deep dive (posted in #5u-ai, 21.11. 12:55). First RFQs planned for **~16:00 Sat**.

## Goal
Build a **digital air forwarder**: one mailbox that quotes, books and tracks air-export shipments **on its own, all night**.

A forwarder buys transport for a customer: customer sends an RFQ → you find the best price from airlines/truckers → quote → book → answer tracking questions.

## The flow (per request)
1. **Quote** – RFQ arrives → check rates (sheets + portal) → ask 2–5 carriers by email → reply with ONE all-in price + currency, **within 6 min** (RFQ expires after 6 min, a new one every 6 min).
2. **Book** – customer accepts → book on the portal with the **rate ID** (valid 15 min) → confirm to customer.
3. **Track** – customer asks "where is it?" → answer from **our own CRM**.

## What we must build
| Part | Job |
|---|---|
| **Router** | Classify every incoming mail: customer RFQ / follow-up, carrier bid, rate-desk reply, tariff sheet, tracking question |
| **RFQ agent** | Price, quote (cheapest *or* fastest — whatever the customer asked), book |
| **Tracking agent** | Answer status questions from the CRM |
| **Tariff ingestion agent** | Read new rate sheets (airlines mail monthly tariffs) into the pricing module |
| **Pricing module** | Tariffs stored as structured prices; auto-ingest new ones |
| **CRM** | Quotes + bookings, history, won/lost, dashboard |
| **Sessions UI with streaming** | Watch each conversation live; a human can easily find a session and step in |

## What 5U gives us
- **Start kit:** 10 airline rate sheets (mixed formats), carrier list with airline + trucker emails, pickup zones. Some airlines only in sheets, others only on the portal.
- **Mailbox:** one per team, all mail logged.
- **Rate portal:** API (rate IDs + booking, rate-limited), a browser page behind a bot challenge, and an email desk `ratedesk@hackloop.mail`.
- **Customer agents:** RFQs/follow-ups; tracking questions from `tracking@hackloop.mail`.
- **Carrier agents:** 2–5 per destination, answer bid requests by email.
- **LLM gateway:** one key per team, **OpenAI models only** (uses our own OpenAI key), measures cost.
- **Leaderboard** + **Swagger docs** at `<Base URL from kit card>/docs`.

Scope: air export only (incl. door-to-port = trucking pickup + flight). Not: TMS, margins, ocean.

## Scoring (per accepted quote, max 100)
| | Points | Rule |
|---|---|---|
| Price accuracy | 45 | Full at best price, less the higher above |
| LLM cost | 40 | Gateway spend per accepted quote; full at $0, zero at $0.10 |
| Response time | 15 | Full ≤ 2 min, zero at 6 min |

- **Accepted** = within **5 %** of best price, **first reply in thread only**, within 6 min. Otherwise 0.
- Carrier bids: "right" one balances **price and speed 50/50**.
- "Read the rate sheets closely — the best price is not always the obvious one" (surcharges, min charges, weight breaks, zones…).
- Bonus: **+10** correct tracking answer on a booked shipment; **+10** (jury) most human-sounding email.

## Rules / traps
- Same request to all teams at once; scored independently.
- No second chance: missed/rejected = lost.
- **After a few hours, the setup changes ~hourly, unannounced** — you notice via failed quotes. Build logging + make it easy to adapt.

## Winning
Leaderboard alone doesn't decide. Final pitch **3 min + 2 min Q&A**. Jury: pitch, UX/design, tech depth/codebase, leaderboard, human-sounding emails.
Prizes: 1st fly an ultralight plane yourself · 2nd Hans Zimmer concert tickets · 3rd founders dinner (+ €300/200/100 START cash).

## Strategy implications
- **Do the math in code, not the LLM.** Pricing = deterministic Python over parsed tariffs. LLM cost is 40% of points → use the cheapest model (e.g. `gpt-4o-mini` / nano) only for: routing, extracting RFQ fields, writing the reply. Must make ≥1 gateway call per quote.
- **Speed:** quote within 2 min → don't wait long for carrier bids; set a timeout and quote from best available.
- **Parse the 10 rate sheets early** (before 16:00) into one clean table.
- **Reply in-thread**, one quote, total + currency, friendly human tone.
- **Log everything** so hourly changes are spotted fast.
