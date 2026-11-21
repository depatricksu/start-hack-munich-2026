"""Truncated-JSON safety net in llm/extract.py. Run: python -m unittest tests.test_extract_retry -v"""
import os, unittest
from unittest.mock import patch

os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "0")
os.environ.setdefault("FIVEU_API_KEY", "x")

from llm import extract as E


def _resp(status, content, in_tok=10, out_tok=10):
    return status, {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok}}


class TestRetryOnTruncatedJson(unittest.TestCase):
    def test_second_call_rescues_a_truncated_first_call(self):
        calls = []

        def fake_api(method, path, timeout=None, body=None):
            calls.append(body["max_completion_tokens"])
            if len(calls) == 1:
                return _resp(200, '{"origin": "MUC", "destination": "CAI", "weight_kg": 486, "reply": "Hi, the price is')  # cut off
            return _resp(200, '{"origin": "MUC", "destination": "CAI", "weight_kg": 486, "reply": "Hi, the price is X."}', out_tok=40)

        with patch.object(E.mailbox, "api", side_effect=fake_api), patch.object(E.config, "LLM_FAKE", False):
            fields, usage = E.extract({"subject": "x", "body": "quote please", "sender": "a@b.mail"})
        self.assertEqual((fields["origin"], fields["destination"], fields["weight_kg"]), ("MUC", "CAI", 486))
        self.assertEqual(len(calls), 2)
        self.assertGreater(calls[1], calls[0])                       # second attempt got more room
        self.assertEqual(usage["out"], 50)                           # usage of both calls added up

    def test_two_truncated_calls_raise_instead_of_crashing_the_clerk(self):
        def fake_api(method, path, timeout=None, body=None):
            return _resp(200, '{"origin": "MUC"')

        with patch.object(E.mailbox, "api", side_effect=fake_api), patch.object(E.config, "LLM_FAKE", False):
            with self.assertRaises(RuntimeError):
                E.extract({"subject": "x", "body": "y", "sender": "a@b.mail"})

    def test_normal_call_is_not_retried(self):
        calls = []

        def fake_api(method, path, timeout=None, body=None):
            calls.append(1)
            return _resp(200, '{"origin": "FRA", "destination": "JFK", "weight_kg": 100, "reply": "Hi, ok."}')

        with patch.object(E.mailbox, "api", side_effect=fake_api), patch.object(E.config, "LLM_FAKE", False):
            E.extract({"subject": "x", "body": "y", "sender": "a@b.mail"})
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
