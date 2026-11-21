"""5U 20:30: one mailbox poll per 5 s per team key, faster gets 429. Run: python -m unittest tests.test_poll_limit"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from core import config, mailbox  # noqa: E402


class PollLimit(unittest.TestCase):
    def test_poll_interval_respects_5u_limit(self):
        self.assertGreaterEqual(config.POLL_S, 5.0)
        self.assertLess(config.TICK_S, config.POLL_S)

    def test_429_raises_rate_limited_with_retry_after(self):
        orig = mailbox.api
        mailbox.api = lambda *a, **k: (429, {"retry_after": 4.0, "detail": "slow down"})
        try:
            with self.assertRaises(mailbox.RateLimited) as cm:
                mailbox.poll(10)
            self.assertEqual(cm.exception.retry_after, 4.0)
        finally:
            mailbox.api = orig


if __name__ == "__main__":
    unittest.main()
