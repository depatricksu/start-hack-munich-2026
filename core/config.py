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
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "400"))

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
QUOTE_EUR = os.environ.get("QUOTE_EUR", "1") == "1"        # quote in EUR even if the cheapest flight came in USD
# Which bid we take among truckers / airline bids. auto = the 5U booth rule (see sourcing/bids.py pick_bid):
# customer says fast -> fastest, says cheapest -> cheapest, says nothing -> balanced 50/50 price and speed.
# Override with cheapest | balanced | fastest if the board shows the rule is different.
BID_PICK = os.environ.get("BID_PICK", "auto").lower()
# The supervisor uploads a snapshot of the live DB for the team this often (core/share.py). 0 = never.
SHARE_EVERY_S = float(os.environ.get("SHARE_EVERY_S", "900"))
# An RFQ older than this is dead (expires after 6 min). We do not answer it, e.g. after a restart.
RFQ_MAX_AGE_S = float(os.environ.get("RFQ_MAX_AGE_S", "330"))
CLARIFY = os.environ.get("CLARIFY", "1") == "1"     # ask the customer when only data is missing (Erik, 21 Nov)
