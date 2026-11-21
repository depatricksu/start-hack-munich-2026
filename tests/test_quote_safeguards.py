"""Quote safeguards. Run: python -m unittest tests.test_quote_safeguards -v"""
import os, tempfile, unittest
from decimal import Decimal

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")
os.environ.setdefault("FIVEU_API_KEY", "")

from core import config, db, main  # noqa: E402
from sourcing import bids  # noqa: E402
from tests.test_bids import rfq  # noqa: E402

_next = [7720000]   # own mail ids: test_bids is imported twice (as tests.test_bids and test_bids), each with its own counter


def answer(bid, text):
    _next[0] += 1
    main.process(main.mailbox.normalize({"id": _next[0], "from": bid["email"], "in_reply_to": 1,
                                         "subject": "Re: request [BID-%d]" % bid["id"], "body": text}))


class TestQuoteInEur(unittest.TestCase):
    def test_usd_option_is_quoted_in_eur_and_keeps_the_original(self):
        best = {"airline": "X", "total": "100.00", "currency": "USD", "total_eur": "92.40", "transit_days": 2}
        q = main.quote_in_eur(best)
        self.assertEqual((q["total"], q["currency"]), ("92.40", "EUR"))
        self.assertEqual((q["original_total"], q["original_currency"]), ("100.00", "USD"))

    def test_eur_option_is_unchanged(self):
        best = {"airline": "X", "total": "100.00", "currency": "EUR", "total_eur": "100.00", "transit_days": 2}
        self.assertEqual(main.quote_in_eur(best), best)

    def test_flag_turns_it_off(self):
        best = {"airline": "X", "total": "100.00", "currency": "USD", "total_eur": "92.40", "transit_days": 2}
        config.QUOTE_EUR = False
        try:
            self.assertEqual(main.quote_in_eur(best), best)
        finally:
            config.QUOTE_EUR = True


class TestUnclearBidIsKept(unittest.TestCase):
    def test_total_parsed_but_model_unsure_still_counts(self):
        rfq(772001, "MUC", "LAX", 120, 0.9, postcode="80331")
        t = [b for b in bids.rows(772001) if b["role"] == "trucker"][0]
        original = bids.read_answer
        bids.read_answer = lambda mail: ({"total": 150, "currency": "EUR", "transit_days": 1, "unclear": "two prices in the mail"}, None)
        try:
            answer(t, "whatever")
        finally:
            bids.read_answer = original
        row = [b for b in bids.rows(772001) if b["id"] == t["id"]][0]
        self.assertEqual((row["status"], Decimal(row["total_eur"])), ("ok", Decimal("150.00")))
        self.assertEqual(row["note"], "two prices in the mail")

    def test_no_total_is_still_unclear(self):
        rfq(772002, "MUC", "LAX", 120, 0.9, postcode="80331")
        t = [b for b in bids.rows(772002) if b["role"] == "trucker"][0]
        original = bids.read_answer
        bids.read_answer = lambda mail: ({"total": None, "currency": "EUR", "unclear": "no price given"}, None)
        try:
            answer(t, "whatever")
        finally:
            bids.read_answer = original
        self.assertEqual([b for b in bids.rows(772002) if b["id"] == t["id"]][0]["status"], "unclear")


if __name__ == "__main__":
    unittest.main()
