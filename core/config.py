"""All settings in one place. Values come from .env or the shell (shell wins)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env():
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            k, _, v = line.strip().partition("=")
            if k and v and not k.startswith("#"):
                os.environ.setdefault(k, v)


_load_env()

API_KEY = os.environ.get("FIVEU_API_KEY", "")
BASE_URL = os.environ.get("FIVEU_BASE_URL", "https://api.start-hack.5u.ai").rstrip("/")
OUR_ADDRESS = os.environ.get("OUR_ADDRESS", "google@hackloop.mail")

# Safety: only Erik's MacBook sets DRY_RUN=0. With 1 (default) nothing is ever sent.
DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
# LLM_FAKE=1 skips the gateway and reads the mail with a crude regex. It is ON by default in DRY_RUN,
# so only the runner spends gateway money (4 machines calling the gateway = 4x LLM cost on our score).
# To test the real prompt on your machine: DRY_RUN=1 LLM_FAKE=0.
LLM_FAKE = os.environ.get("LLM_FAKE", "1" if DRY_RUN else "0") == "1"
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")   # check GET /v1/gateway/models for a cheaper one
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "700"))   # 400 truncated the JSON on a 2-lot mail (live crash 21 Nov 16:46)

DB_PATH = os.environ.get("DB_PATH", os.path.join(ROOT, "data", "forwarder.db"))
POLL_S = float(os.environ.get("POLL_S", "1.5"))

# How long we wait for carrier/trucker bids, counted from RFQ arrival, before we quote with what we have.
# 90 is a START VALUE, NOT SETTLED. Calibrate with real data: `python -m core.stats` shows how fast bids
# really come back. Time score: full under 120 s, zero at 360 s.
BID_WAIT_S = float(os.environ.get("BID_WAIT_S", "90"))
# If a leg we cannot quote without (trucker for door pickup, or the only flight price) has not answered at
# BID_WAIT_S, keep waiting until this many seconds after RFQ arrival. A late correct quote beats none.
# Also a start value: an RFQ expires at 360 s.
BID_MAX_WAIT_S = float(os.environ.get("BID_MAX_WAIT_S", "300"))
# 1 = on normal requests also ask up to 3 airlines by mail, without waiting, to learn if bids beat sheet/portal.
# Turn off (0) once we know. See `python -m core.stats`.
BID_EXPERIMENT = os.environ.get("BID_EXPERIMENT", "1") == "1"
# 1 = ask up to BID_MAX_CARRIERS carriers + the rate desk on EVERY request and WAIT for them, even when the
# portal/sheet already priced the lane. The brief mandates pricing from "sheets, portal AND bids from 2 to 5
# carriers", and board evidence (21 Nov) shows airline bids beat our portal/sheet price ~80% of the time, so
# skipping them loses "cheapest"/"fastest" rounds as too_high. Costs ~BID_WAIT_S of latency per quote (still
# under the 120 s full-time window). Overrides BID_EXPERIMENT when on.
BID_ALWAYS = os.environ.get("BID_ALWAYS", "0") == "1"
BID_MAX_CARRIERS = int(os.environ.get("BID_MAX_CARRIERS", "5"))   # the brief: bids from 2 to 5 carriers
QUOTE_EUR = os.environ.get("QUOTE_EUR", "1") == "1"        # quote in EUR even if the cheapest flight came in USD
# Which bid we take among truckers / airline bids (sourcing/bids.py pick_bid).
# balanced (default) = price and speed 50/50. Board evidence 21 Nov (rounds 1, 2, 4 fit to the cent): 5U's scorer
# ALWAYS uses the balanced trucker, also for customers who ask for the cheapest, and a quote BELOW its best price
# loses points too (more than about 5% below is rejected as too_low). So the cheapest trucker is not the safe side.
# Other values: auto (booth rule: fast -> fastest, cheapest -> cheapest, nothing said -> balanced) | cheapest | fastest.
BID_PICK = os.environ.get("BID_PICK", "balanced").lower()
# The supervisor uploads a snapshot of the live DB for the team this often (core/share.py). 0 = never.
SHARE_EVERY_S = float(os.environ.get("SHARE_EVERY_S", "900"))
# 1 = the gateway call also gets the text of the customer's attachments (core/attachments.py). Off until one real
# request with an attachment was tried with the real gateway in DRY_RUN: it changes what the model reads.
ATTACH_LLM = os.environ.get("ATTACH_LLM", "0") == "1"
# An RFQ older than this is dead (expires after 6 min). We do not answer it, e.g. after a restart.
RFQ_MAX_AGE_S = float(os.environ.get("RFQ_MAX_AGE_S", "330"))
CLARIFY = os.environ.get("CLARIFY", "1") == "1"     # ask the customer when only data is missing (Erik, 21 Nov)
