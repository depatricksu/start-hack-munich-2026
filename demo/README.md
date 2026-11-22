# Demo video (offline, safe on the runner)

Separate checkout, so the live clerk and data/forwarder.db are never touched:

    git fetch && git worktree add ../relay-demo origin/kai/demo-video
    cd ../relay-demo/ui && npm ci && cd ..
    sh demo/ui.sh          # terminal 1: demo UI on http://localhost:3300/v2
    sh demo/run.sh         # terminal 2: start recording; the shipment starts after 20 s, one step every 9 s

Faster: `DEMO_PACE_S=5 DEMO_START_S=10 sh demo/run.sh`. Every run starts from an empty demo DB.
All mails are invented. Carrierops drafts count as sent in this demo only (live it writes drafts).
