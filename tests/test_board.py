"""Board monitor. Run: python -m unittest tests.test_board -v"""
import json, os, tempfile, time, unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main  # noqa: E402
from monitor import board  # noqa: E402


def events(kind):
    return [json.loads(r["data"]) for r in db.con().execute("SELECT data FROM events WHERE kind=?", (kind,))]


class TestBoard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        main.process(main.mailbox.normalize({"id": 99001, "from": "x@c.mail", "subject": "Q",
                                             "body": "90 kg 0.4 cbm HAM to BOG cheapest"}))
        cls.t = db.session(99001)["received_at"]

    def test_match_by_mail_id_and_verdict_change(self):
        board.ingest({"requests": [{"round": "r1", "message_id": 99001, "verdict": "pending"}]})
        board.ingest({"requests": [{"round": "r1", "message_id": 99001, "verdict": "accepted",
                                    "points": {"accuracy": 45, "time": 15, "cost": 40}}]})
        row = board.con().execute("SELECT * FROM board_results WHERE round='r1'").fetchone()
        self.assertEqual((row["thread_id"], row["verdict"], row["points"]), (99001, "accepted", 100))
        verdicts = [e["verdict"] for e in events("board_verdict") if e["round"] == "r1"]
        self.assertEqual(verdicts, ["pending", "accepted"])
        board.ingest({"requests": [{"round": "r1", "message_id": 99001, "verdict": "accepted"}]})
        self.assertEqual(len([e for e in events("board_verdict") if e["round"] == "r1"]), 2)   # no duplicate

    def test_match_by_time(self):
        iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(self.t + 3))
        board.ingest([{"round_id": "r2", "status": "rejected", "reason_code": "price_off", "sent_at": iso}])
        row = board.con().execute("SELECT thread_id, reason FROM board_results WHERE round='r2'").fetchone()
        self.assertEqual((row["thread_id"], row["reason"]), (99001, "price_off"))

    def test_alert_on_same_reason(self):
        now = time.time()
        board.ingest({"results": [{"round": "a%d" % i, "verdict": "rejected", "reason": "price_too_high",
                                   "sent_at": now + i} for i in range(3)]})
        a = board.alert()
        self.assertEqual(a["reason"], "price_too_high")
        self.assertIn("price_too_high", board.summary())

    def test_unknown_shape_is_ignored(self):
        self.assertEqual(board.ingest({"something": "else"}), [])


if __name__ == "__main__":
    unittest.main()
