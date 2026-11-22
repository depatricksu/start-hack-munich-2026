#!/bin/sh
# Demo UI on port 3300, reading only demo/db/demo.db. Run once before: cd ui && npm ci
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HERE/db"
cd "$HERE/../ui" && DB_PATH="$HERE/db/demo.db" exec node node_modules/next/dist/bin/next dev -p 3300
