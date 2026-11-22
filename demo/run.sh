#!/bin/sh
# Demo run for the video. Fresh DB in demo/db, nothing leaves the Mac: no key, DRY_RUN=1, LLM_FAKE=1,
# INVOICE_MAIL=0, dead 5U address, all network blocked. Never touches data/forwarder.db or the live clerk.
HERE=$(cd "$(dirname "$0")" && pwd)
DB="$HERE/db/demo.db"
mkdir -p "$HERE/db" "$HERE/out"
rm -f "$DB" "$DB-wal" "$DB-shm" "$HERE/db/human_learn.json"
exec env -i PATH="$PATH" HOME="$HOME" PYTHONDONTWRITEBYTECODE=1 \
  FIVEU_API_KEY= DRY_RUN=1 LLM_FAKE=1 INVOICE_MAIL=0 DG_OCR_WARMUP=0 \
  DB_PATH="$DB" TARIFF_OVERRIDES="$HERE/db/tariff_overrides.json" FIVEU_BASE_URL=http://127.0.0.1:9 \
  DEMO_PACE_S="${DEMO_PACE_S:-9}" DEMO_START_S="${DEMO_START_S:-20}" \
  python3 "$HERE/demo_live.py"
