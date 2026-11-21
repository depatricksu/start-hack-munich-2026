# Demo backup: control room script, screenshots, recording

We use this backup if the network or the mailbox fails during the pitch. The control room is the Next.js app in `ui/`,
served at `localhost:3000` on the runner Mac. Its top bar reads **Forwarder Control Room**, with the tabs
**Sessions** (`/`), **Dashboard** (`/dashboard`) and **Score** (`/score`).
The labels below come from `ui/` on `main`. If the `ui/redesign` branch is live when you record, check the names
again before you go.

Reference request if no new one arrives in time: **12870, DUS -> BOM, Tobias / Auer Maschinenbau** (real, from the
runner). It has sheet, portal and carrier-bid options, was quoted in 83 s, the booking was made at +114 s and
confirmed by the airline at +153 s, and the customer also asked for tracking.

## 60-90 s demo script (what to click, in order)

| Time | Click | What the screen shows |
|---|---|---|
| 0-10 s | **Sessions** tab | Left: **Requests** list with the green **Live data** pill. A new card shows the route, customer, status chip **New**, and the countdown "m:ss left". |
| 10-25 s | Click the new request card | Right panel: route, the tiles **Weight / Volume / Wants / Language**, **What the system did** timeline ("Mail received", "Read by the AI", "Prices found", `bid_requested`, "Waiting for carrier bids"). The chip turns **Waiting for bids**. |
| 25-40 s | Scroll to **Price options** | Table **Airline / Source / Days / Total**: rows with source `sheet`, `portal` and `bid`. The chosen row is green and tagged **quoted**. The big **Quote** box above it shows the price and "via portal". |
| 40-55 s | Scroll to **Thread** | The customer mail, then the green **Our reply** box with the quote mail. The card in the list now says "quoted in NNs" in green (under 120 s = full time points). |
| 55-70 s | Stay on the request and wait for the customer's "please go ahead and book it" | The new mail appears in **Thread**, the timeline adds `booking_call` and then `booking_confirmed`, and the chip goes **Booked**, then **Confirmed**. |
| 70-80 s | Tracking answer (see shot 5) | Our status answer with booking ref, airline, route and ETA. |
| 80-90 s | **Score** tab, then quickly **Dashboard** | Score: 5U verdict per request (**accepted** green). Dashboard: **Quotes sent**, **Median response**, **LLM cost per quote**. |

## The 6 screenshots, one sentence each

1. **`shot-1.png`: a new request.** Sessions tab, new card selected, chip **New**, countdown running.
   Say: "A customer mail just arrived, and the AI has already read the route, weight, volume and whether they want cheapest or fastest."
2. **`shot-2.png`: price options with carrier bids.** **Price options** table with `sheet`, `portal` and `bid` rows,
   the **quoted** row in green.
   Say: "In one pass we compare our own rate sheets, the live rate portal and bids that carriers sent back by mail, then pick the option the customer asked for."
3. **`shot-3.png`: the quote mail.** **Thread** with the green **Our reply** box, and "quoted in NNs" on the card.
   Say: "The quote goes out in under two minutes, in the customer's language, and it answers their own questions like a colleague would."
4. **`shot-4.png`: the booking.** Same request with the chip **Booked** or **Confirmed**, the customer's "please book it" in
   **Thread**, and `booking_call` / `booking_confirmed` in the timeline.
   Say: "The customer says yes, we book with the airline right away and send them the booking reference."
5. **`shot-5.png`: a tracking answer.** The reply to a "where is my shipment?" mail, with the BK reference, airline and ETA.
   Say: "When the customer asks where the shipment is, they get an answer in seconds, matched to their booking."
6. **`shot-6.png`: the score page.** **Score** tab with the verdicts per request.
   Say: "This is 5U's own scorer: price, cost and speed for every request we handled."

Note for shot 5: on `main` the Sessions page shows no tracking mails. They come in on their own thread with no session.
Until the UI shows them, put the answer on screen in Terminal on the runner (read only):
```bash
sqlite3 data/forwarder.db "select json_extract(data,'\$.body') from events where kind='mail_out' and thread_id=(select max(thread_id) from events where kind='tracking_answered')"
```
Known glitch to avoid on camera: for 12870 the tracking answer says "arrive around 23 Nov", but the quote said
25 Nov (ready on the 23rd plus 2 days). Use a different tracking answer, or crop out the ETA line.

## How to record (Erik's Mac)

- [ ] Ask Erik when to record. Do not touch the runner (no restart, no `DRY_RUN` change, no Ctrl+C on the clerk).
- [ ] Record when a fresh request arrives: they come about every 6 minutes. You need the whole path from **New** to **Confirmed** (about 3 min live, which you trim to 60-90 s).
- [ ] Browser at `localhost:3000`, full screen, zoom 110-125 % so the text is readable on the projector. Close other tabs and notifications (Focus mode on).
- [ ] **Cmd+Shift+5** -> "Record Selected Portion" around the browser window -> Options: microphone **None** -> Record. Stop with the stop icon in the menu bar (or Cmd+Ctrl+Esc).
- [ ] Trim in QuickTime (Cmd+T) to 60-90 s and save as **`docs/pitch/demo.mov`**. It must make sense with no sound.
- [ ] Screenshots: **Cmd+Shift+4**, then Space, then click the browser window (or **Cmd+Shift+5** -> "Capture Selected Window"). Take them in the order 1-6 above while the request moves, and save as **`docs/pitch/shot-1.png`** ... **`docs/pitch/shot-6.png`**.
- [ ] Check that no real keys or `.env` content are visible. The customer names are fake game data, so they are fine.
- [ ] Commit only the `.mov`/`.png` files in `docs/pitch/` on a branch and open a PR (never `data/` or `examples/real/`).
