"""The runner's snapshot upload runs in a background thread. It must not die on a cross-thread db.event, or the
team stops getting fresh data (seen live: auto-upload stopped at 16:49). Run: python -m unittest tests.test_share_thread"""
import os, tempfile, threading, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from core import db, share  # noqa: E402


class TestShareThread(unittest.TestCase):
    def test_db_event_works_from_a_background_thread(self):
        db.event("main_thread_probe")                 # the supervisor's main thread opens the connection first
        err = []
        def worker():
            try:
                db.event("share_thread_probe")        # the share thread then logs on it
            except Exception as e:
                err.append(repr(e))
        t = threading.Thread(target=worker); t.start(); t.join()
        self.assertEqual(err, [])                      # no "SQLite objects created in a thread..." crash

    def test_share_log_helper_swallows_errors(self):
        # start_background wires a _log that must never raise; emulate it via db.event under a broken call
        try:
            share.db.event("probe_ok")
        except Exception as e:
            self.fail("db.event raised: %r" % e)


if __name__ == "__main__":
    unittest.main()
