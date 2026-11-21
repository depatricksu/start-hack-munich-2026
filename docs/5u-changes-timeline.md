# 5U changes tonight and how we answered (21 Nov 2026)

Times are local (CET = UTC+1). Rounds came about every 6 minutes, so a round time is approximate when no mail gives it.

| Time (local) | What 5U changed | How we noticed | What we did | PR or commit |
|---|---|---|---|---|
| about 16:50 | Round 9 sent one mail with several lots, and we priced only 730 of 1,952 kg. | The board rejected round 9 as too_low and Erik's agent found the under-count. | We add up every lot of a multi-lot mail before pricing. | PR #12 (2f48080) |
| about 17:00 | Rounds 10 and 11 hid dangerous goods in the attachment while the mail said non-dangerous. | The board rejected both rounds with dg_docs_missing and Erik's agent read the attachments. | The new `dg/` module reads every attachment and the quote asks for the DG documents. | 793a084, 1591fca, PR #15 (eaedc25) |
| 17:38 | In round 17 the customer gave only a pickup postcode (zone 72 = STR) and the model made up FRA as origin. | Riky saw the rejection on the public board and the snapshot showed we priced FRA instead of STR. | For a door pickup the postcode zone now decides the departure airport. | a0d7b00 |
| 18:40 to 18:54 | The portal rate API answered 503 on every lane, and rounds 27 to 29 were lost. | Erik's agent tested five lanes and got 503 on all of them. | When the portal is down we ask the airlines and the rate desk by mail and use their bids. | PR #25 (f9414f1), 45bdc0c |
| about 18:45 | Dangerous goods sat only in the commodity name ("maintenance spray cans"). | The customer declined because we quoted without asking for the DG documents. | A short list of dangerous commodities (aerosols, lithium, dry ice and more) now triggers the DG request. | PR #28 (bf3bb7e), 07901d3 |
| 19:15 | Carrier bids became cheaper than the portal, and rounds 33 to 35 were rejected too_high. | Riky saw on the board that only 3 of 12 teams were accepted in round 33. | We ask 2 to 5 carriers on every quote and a cheaper mailed price always competes. | PR #33 (1f89ebe), PR #34 (b980fe4) |
| about 19:50 | From round 39 customers answered "we will send the DG documents" right after our quote. | The clerk put these replies in needs_human, but the board counted them as accepted. | That reply now counts as a yes and we book right away. | PR #36 (7228e76), PR #37 (58e44e7) |
| 20:09 | Round 42 asked "do not offer Zephyr Steppe Cargo", and 0 of 11 teams were accepted. | Patrick's agent read the mail of request 10823. | An airline the customer excluded is never asked, picked or quoted. | 0597f5d, PR #42 (61309d2) |
| 20:30 | The mailbox allowed only one poll per 5 seconds and answered 429 to faster polls. | Two of our three polls failed with 429. | We poll every 5.2 seconds, honour Retry-After and run bid waits on their own timer. | 315c166 |
| about 20:40 | Round 47 was a bids-only lane where the customer asked for the cheapest option. | The board rejected our faster but dearer quote as too_high. | On a bids-only lane we now honour cheapest or fastest instead of the balanced pick. | PR #40 (fb17ddc) |
| about 20:45 | In rounds 48 and 49 the portal booked 10% above the quoted rate. | We lost 22.5 points twice and the booking response showed the higher price. | We ask the customer to confirm the new price before we confirm the booking. | PR #43 (316763f) |
| 21:00 | The portal refused bookings for Xenon Cargo Airlines with a 503 "book by email". | The runner's alarm posted request 13471 as needs_human in the agent chat. | We book with the airline by mail and tell the customer. | PR #41 (89868b9) |
| 21:21 | 5U sent a vendor cold pitch with no shipment in it. | It cost a gateway call and landed in needs_human. | A sales pitch with no shipment is routed as spam and gets no reply. | PR #49 (3d40bcb) |

Sources: merged PRs (`gh pr list --state merged`), `git log origin/main`, agent chat in issue #2 (UTC timestamps converted to CET) and issue #30.
