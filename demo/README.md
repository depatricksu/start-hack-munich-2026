# After the yes (pitch demo)

Our agent quotes, books and tracks. After the customer says yes, a forwarder still writes about seven more
messages by hand: pickup order to the trucker, shipment details to the airline, a thank-you to the carriers we
did not pick, next steps and papers to the customer, a pre-alert to the destination partner, the day-before check
with the trucker, and status mails during the trip. Every field they need is already in our database.

This folder drafts those messages from the **runner's real data**. It is read-only: it opens the DB with
`mode=ro`, sends nothing, makes no gateway call, and nothing in `core/` imports it.

```bash
python3 -m core.share --get                                   # newest runner snapshot
DB_PATH=examples/real/snapshot.db python3 -m demo.after_yes   # → demo/out/after-the-yes.html
open demo/out/after-the-yes.html
```

Options: `--db`, `--out`, `--json data.json` (raw drafts), `--featured 9869` (booking shown first).

On the 21:54 snapshot: 55 confirmed bookings → 345 drafted messages, 39 truck pickup orders,
47 bookings where losing bidders never heard back.

## Ideas for the team (make it a product a forwarder would use)
- Turn the drafts into a real **outbox** in the control room: approve, edit, send, per party.
- Read the trucker's and airline's replies back into the shipment (driver window, delivery receipt, delay).
- A per-shipment timeline that a forwarder can open from the customer's mail.
- Same data, other channels: an export to the TMS, a status link for the customer.
