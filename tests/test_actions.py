"""Run: python -m unittest tests.test_actions -v   (no network, no key)

Imports `core` lazily and swaps in a temp DB only while this class runs, so other test files
(which set their own env before importing core) are not affected.
"""
import os, tempfile, unittest


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from core import config, db
        from actions import queue
        cls.config, cls.db, cls.queue = config, db, queue
        cls._saved = (config.DB_PATH, config.DRY_RUN, db._con, queue._ready)
        config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
        config.DRY_RUN = True
        db._con = None
        queue._ready = False

    @classmethod
    def tearDownClass(cls):
        cls.config.DB_PATH, cls.config.DRY_RUN, cls.db._con, cls.queue._ready = cls._saved


def session(tid, status, quoted_at=None, subject="Quote HAM to BOG"):
    db = TestActions.db
    db.con().execute("INSERT INTO sessions(thread_id,customer,subject,status,received_at,quoted_at) VALUES(?,?,?,?,?,?)",
                     (tid, "anna@customer.mail", subject, status, 1.0, quoted_at))


def last_action(tid):
    db = TestActions.db
    return dict(db.con().execute("SELECT * FROM actions WHERE thread_id=? ORDER BY id DESC", (tid,)).fetchone())


class TestActions(Base):
    def test_human_reply_on_needs_human_becomes_first_quote(self):
        db, queue = self.db, self.queue
        session(1, "needs_human")
        queue.add(1, "send_reply", "Hello Anna, 400 EUR all-in.")
        queue.tick()
        s = db.session(1)
        self.assertEqual((s["status"], s["reply"], s["note"]), ("quoted", "Hello Anna, 400 EUR all-in.", "sent by a human"))
        self.assertIsNotNone(s["quoted_at"])
        self.assertEqual(last_action(1)["result"], "sent")

    def test_waiting_session_is_claimed_so_the_loop_never_double_quotes(self):
        db, queue = self.db, self.queue
        session(2, "waiting_bids")
        queue.add(2, "send_reply", "Quote by hand.")
        queue.tick()
        self.assertEqual(db.session(2)["status"], "quoted")
        self.assertFalse(db.claim_for_sending(2))            # the loop can no longer send a second quote

    def test_follow_up_after_a_quote_keeps_status_and_original_reply(self):
        db, queue = self.db, self.queue
        session(3, "quoted", quoted_at=5.0)
        db.update_session(3, reply="original")
        queue.add(3, "send_reply", "One more thing.")
        queue.tick()
        s = db.session(3)
        self.assertEqual((s["status"], s["reply"], s["quoted_at"]), ("quoted", "original", 5.0))
        self.assertEqual(last_action(3)["result"], "sent")

    def test_bad_actions_are_closed_with_an_error_and_never_raise(self):
        db, queue = self.db, self.queue
        session(4, "needs_human")
        queue.add(4, "send_reply", "   ")
        queue.add(4, "launch_rocket", "x")
        queue.add(999, "send_reply", "no such session")
        queue.tick()
        rows = [dict(r)["result"] for r in db.con().execute("SELECT * FROM actions WHERE thread_id IN (4,999) ORDER BY id")]
        self.assertEqual(rows, ["error: empty reply", "error: unsupported kind launch_rocket", "error: no such session"])
        self.assertEqual(db.session(4)["status"], "needs_human")

    def test_done_actions_are_not_sent_twice(self):
        db, queue = self.db, self.queue
        session(5, "needs_human")
        queue.add(5, "send_reply", "Once.")
        queue.tick(); queue.tick()
        n = db.con().execute("SELECT COUNT(*) AS n FROM events WHERE kind='mail_out_dry_run' AND thread_id=5").fetchone()["n"]
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
