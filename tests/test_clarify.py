"""Clarifying question flow. Run: python -m unittest tests.test_clarify -v"""
import json, os, tempfile, unittest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import config, db, main  # noqa: E402
from llm import clarify  # noqa: E402

CUST = "jan@customer-example.mail"


def mail(id, body, subject="Quote request", refs=None, sender=CUST):
    return main.mailbox.normalize({"id": id, "from": sender, "subject": subject, "body": body,
                                   "references": refs or [], "in_reply_to": refs[-1] if refs else None})


def out(tid):
    rows = db.con().execute("SELECT data FROM events WHERE kind IN ('mail_out_dry_run','mail_out') AND thread_id=?",
                            (tid,))
    return [json.loads(r["data"]) for r in rows]


class TestClarify(unittest.TestCase):
    def test_missing_weight_ask_then_quote(self):
        main.process(mail(88001, "Hi, we need a quote from HAM to BOG, 0.4 cbm. Cheapest please."))
        s = db.session(88001)
        self.assertEqual(s["status"], "asked_customer")
        self.assertIn("weight_kg", s["note"])
        q = out(88001)
        self.assertEqual(len(q), 1)
        self.assertIn("gross weight", q[0]["body"])
        self.assertNotIn("{", q[0]["body"])
        main.process(mail(88002, "Sorry, it is 90 kg in total.", "Re: Quote request", refs=[88001]))
        s = db.session(88001)
        self.assertEqual(s["status"], "quoted", s["note"])
        self.assertEqual(json.loads(s["chosen"])["airline"], "Cobalt Skylift")
        self.assertEqual(len(out(88001)), 2)
        self.assertIn("432.00", out(88001)[1]["body"])

    def test_german_question(self):
        f = {"language": "de"}
        self.assertIn("Gesamtgewicht", clarify.question_text(["weight_kg"], clarify._lang(f)))
        self.assertIn(" und ", clarify.question_text(["destination", "weight_kg"], "de"))

    def test_decline_closes(self):
        main.process(mail(88011, "Quote from FRA to DFW please, cheapest."))
        self.assertEqual(db.session(88011)["status"], "asked_customer")
        main.process(mail(88012, "Thanks, no longer needed, we cancel.", "Re: Quote request", refs=[88011]))
        self.assertEqual(db.session(88011)["status"], "lost")
        self.assertEqual(len(out(88011)), 1)

    def test_non_answer_goes_to_human(self):
        main.process(mail(88021, "Quote from FRA to DFW please, cheapest."))
        main.process(mail(88022, "Can you call me tomorrow?", "Re: Quote request", refs=[88021]))
        self.assertEqual(db.session(88021)["status"], "needs_human")

    def test_never_asks_twice(self):
        main.process(mail(88031, "Quote from FRA please, 100 kg, cheapest."))
        self.assertEqual(db.session(88031)["status"], "asked_customer")
        main.process(mail(88032, "It is 0.5 cbm.", "Re: Quote request", refs=[88031]))
        s = db.session(88031)
        self.assertEqual(s["status"], "needs_human")
        self.assertEqual(len(out(88031)), 1)

    def test_scope_problems_are_not_asked(self):
        import os
        os.environ["DG_MODE"] = "human"                      # DG is only out of scope when DG_MODE=human (Riky, 17:00 change)
        try:
            main.process(mail(88041, "Quote FRA to ORD, lithium batteries UN3480, cheapest."))
        finally:
            os.environ.pop("DG_MODE", None)
        self.assertEqual(db.session(88041)["status"], "needs_human")
        self.assertEqual(out(88041), [])

    def test_answer_from_someone_else(self):
        main.process(mail(88051, "Quote from HAM to BOG please, 0.4 cbm."))
        main.process(mail(88052, "90 kg", "Re: Quote request", refs=[88051], sender="mallory@evil.mail"))
        self.assertEqual(db.session(88051)["status"], "needs_human")

    def test_switch_off(self):
        config.CLARIFY = False
        try:
            main.process(mail(88061, "Quote from HAM to BOG please, 0.4 cbm."))
            self.assertEqual(db.session(88061)["status"], "needs_human")
        finally:
            config.CLARIFY = True


if __name__ == "__main__":
    unittest.main()
