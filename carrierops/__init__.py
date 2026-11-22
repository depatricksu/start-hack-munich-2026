"""carrierops: the forwarder's job AFTER the booking is confirmed (the carrier part).

A separate program from the RFQ clerk. It reads the clerk's SQLite DB read-only (bookings, sessions, mails, bids)
and writes only its own tables (shipment_state, shipment_updates, outbox, ops_invoices, carrier_log,
carrierops_cursor). It never sends mail and never calls any API: every outgoing message is a draft in `outbox`.
Standard library only, no network modules.

    python3 -m carrierops.run --db PATH [--ops-db PATH] [--once] [--now TS]
"""
