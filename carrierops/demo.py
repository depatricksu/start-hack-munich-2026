"""DEMO ONLY: a simulated carrier mail during transit, the carrier agent, the client informed.

    python3 -m carrierops.demo --db COPY.db                      # storm
    python3 -m carrierops.demo --db COPY.db --scenario strike    # storm, strike, customs, technical, damage
    python3 -m carrierops.demo --db COPY.db --thread 57843 --pause 4

Works on a copy only (refuses forwarder.db). No network, nothing is sent. The airline mail and the client mail are
written into the copy marked simulated, in the customer's case, so Relay shows the pop-up and both mails.
The agent in the middle is the real one (carrierops.run): it only gets the airline's mail and the clerk's record.
"""
import argparse, json, os, sys, time

from . import run, state

SCENARIOS = {
    "storm": ("Due to a severe winter storm all departures from {o} are suspended. Your cargo is safe in our warehouse.", 1),
    "strike": ("A ground handling strike affects all cargo at {o}, your shipment is stuck at our terminal.", 2),
    "customs": ("Your shipment is held by customs at {d} for a document check.", 0),
    "technical": ("Because of a technical problem the aircraft is grounded in {o}.", 1),
    "damage": ("During handling at {o} one piece of your shipment was damaged.", 0),
}


def play(db_path, scenario="storm", thread=None, pause=0.0, say=print):
    real = os.path.realpath(db_path)
    if os.path.basename(real) == "forwarder.db":
        raise SystemExit("refused: demo mails never go into a runner database. Use a copy.")
    if not os.path.isfile(real):
        raise SystemExit("no such database: %s" % db_path)
    import sqlite3
    clerk = sqlite3.connect(real, timeout=5, isolation_level=None)
    clerk.row_factory = sqlite3.Row
    ops = state.connect(real, real + ".ops")
    try:
        cmap = run.carriers(ops)
        run.baseline(ops, time.time())                         # the past is known, only the new mail is news
        used = {r[0] for r in clerk.execute("SELECT thread_id FROM mails WHERE route='booking_confirmation' AND raw LIKE '%\"simulated\": true%'")}
        s = next((s for s in sorted(state.active_shipments(ops), key=lambda x: -x["thread_id"])
                  if s.get("airline_email") and s.get("booking_ref")
                  and (s["thread_id"] == thread if thread else s["thread_id"] not in used)), None)
        if not s:
            raise SystemExit("no active confirmed shipment for the demo")
        tid = s["thread_id"]
        text, days = SCENARIOS[scenario]
        body = "Hello,\n\nbooking %s, %s-%s: %s" % (s["booking_ref"], s["origin"], s["destination"],
                                                    text.format(o=s["origin"], d=s["destination"]))
        if days:
            eta = time.strftime("%Y-%m-%d", time.gmtime((run.parse_now(s["eta_current"][:10])) + days * run.DAY))
            body += " New ETA: %s 14:00." % eta
        body += "\n\nBest regards\n%s" % s["airline"]

        def store(sender, to, subject, text_, route):
            now = time.time()
            mid = clerk.execute("SELECT COALESCE(MAX(id),0)+1 FROM mails").fetchone()[0]
            clerk.execute("INSERT INTO mails(id,sender,subject,body,thread_id,route,received_at,raw) VALUES(?,?,?,?,?,?,?,?)",
                          (mid, sender, subject, text_, tid, route, now,
                           json.dumps({"id": mid, "from": sender, "to": to, "simulated": True})))
            return now

        subject = "Booking %s update" % s["booking_ref"]
        store(s["airline_email"], run.OUR_ADDRESS, subject, body, "booking_confirmation")
        say("\n1. SIMULATED MAIL from %s\n\n%s" % (s["airline"], body))
        time.sleep(pause)
        before = state.one(ops, "SELECT COALESCE(MAX(id),0) AS m FROM outbox")["m"]
        run.process_mails(ops, time.time(), cmap)
        u = state.one(ops, "SELECT type, summary FROM shipment_updates WHERE thread_id=? ORDER BY id DESC LIMIT 1", (tid,))
        say("\n2. CARRIER AGENT: %s, case %s, client %s (from the clerk)" % (u["type"], tid, s["customer"]))
        time.sleep(pause)
        mails = state.rows(ops, "SELECT * FROM outbox WHERE id>? AND thread_id=? AND party='customer'", (before, tid))
        for m in mails:
            now = store(run.OUR_ADDRESS, m["to_addr"], m["subject"], m["body"], "own")
            clerk.execute("INSERT INTO events(ts,thread_id,kind,data) VALUES(?,?,'mail_out',?)", (now, tid, json.dumps(
                {"to": m["to_addr"], "subject": m["subject"], "body": m["body"], "simulated": True, "by": "carrierops"})))
            ops.execute("UPDATE outbox SET status='sent' WHERE id=?", (m["id"],))
            say("\n3. CLIENT INFORMED (simulated send) -> %s\n\n%s" % (m["to_addr"], m["body"]))
        if not mails:
            say("\n3. No new client mail: this news was already told.")
        return {"thread": tid, "type": u["type"], "mails": mails}
    finally:
        clerk.close()
        ops.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m carrierops.demo", description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--scenario", choices=list(SCENARIOS), default="storm")
    ap.add_argument("--thread", type=int)
    ap.add_argument("--pause", type=float, default=3.0, help="seconds between the steps, for recording")
    a = ap.parse_args(argv)
    play(a.db, a.scenario, a.thread, a.pause, lambda t: print(t, flush=True))


if __name__ == "__main__":
    sys.exit(main())
