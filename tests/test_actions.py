"""Run: python -m unittest tests.test_actions -v   (no network, no key)"""
import os, tempfile, unittest

os.environ["DRY_RUN"] = "1"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")

from core import db            # noqa: E402  (env must be set before import)
from actions import queue       # noqa: E402


def session(tid, status, quoted_at=None, subject="Quote HAM to BOG"):
    db.con().execute("INSERT INTO sessions(thread_id,customer,subject,status,received_at,quoted_at) VALUES(?,?,?,?,?,?)",
                     (tid, "anna@customer.mail", subject, status, 1.0, quoted_at))


def last_action(tid):
    return dict(db.con().execute("SELECT * FROM actions WHERE thread_id=? ORDER BY id DESC", (tid,)).fetchone())


class TestActions(unittest.TestCase):
    def test_human_reply_on_needs_human_becomes_first_quote(self):
        session(1, "needs_human")
        queue.add(1, "send_reply", "Hello Anna, 400 EUR all-in.")
        queue.tick()
        s = db.session(1)
        self.assertEqual((s["status"], s["reply"], s["note"]), ("quoted", "Hello Anna, 400 EUR all-in.", "sent by a human"))
        self.assertIsNotNone(s["quoted_at"])
        self.assertEqual(last_action(1)["result"], "sent")

    def test_waiting_session_is_claimed_so_the_loop_never_double_quotes(self):
        session(2, "waiting_bids")
        queue.add(2, "send_reply", "Quote by hand.")
        queue.tick()
        self.assertEqual(db.session(2)["status"], "quoted")
        self.assertFalse(db.claim_for_sending(2))            # the loop can no longer send a second quote

    def test_follow_up_after_a_quote_keeps_status_and_original_reply(self):
        session(3, "quoted", quoted_at=5.0)
        db.update_session(3, reply="original")
        queue.add(3, "send_reply", "One more thing.")
        queue.tick()
        s = db.session(3)
        self.assertEqual((s["status"], s["reply"], s["quoted_at"]), ("quoted", "original", 5.0))
        self.assertEqual(last_action(3)["result"], "sent")

    def test_bad_actions_are_closed_with_an_error_and_never_raise(self):
        session(4, "needs_human")
        queue.add(4, "send_reply", "   ")
        queue.add(4, "launch_rocket", "x")
        queue.add(999, "send_reply", "no such session")
        queue.tick()
        rows = [dict(r)["result"] for r in db.con().execute("SELECT * FROM actions WHERE thread_id IN (4,999) ORDER BY id")]
        self.assertEqual(rows, ["error: empty reply", "error: unsupported kind launch_rocket", "error: no such session"])
        self.assertEqual(db.session(4)["status"], "needs_human")

    def test_done_actions_are_not_sent_twice(self):
        session(5, "needs_human")
        queue.add(5, "send_reply", "Once.")
        queue.tick(); queue.tick()
        n = db.con().execute("SELECT COUNT(*) AS n FROM events WHERE kind='mail_out_dry_run' AND thread_id=5").fetchone()["n"]
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
