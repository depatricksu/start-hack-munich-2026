"""Transient API failures must not lose a round. No network, no key, no real sleeping.

    python3 -m unittest tests.test_retries -v

Gateway (llm/extract.py): 429, 5xx and timeouts are retried inside one time budget, a success never is.
Portal (sourcing/portal.py): one airline's 429 or exception keeps the other airlines.
Quote send (core/main.py): a failed send is retried, a send that may have worked never is.
"""
import email.message, io, json, os, socket, tempfile, threading, unittest, urllib.error
from unittest import mock

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test.db"))
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("LLM_FAKE", "1")
os.environ.setdefault("FIVEU_API_KEY", "")

from core import config, db, main, mailbox  # noqa: E402
from llm import extract as E  # noqa: E402
from sourcing import portal  # noqa: E402

GOOD = '{"origin": "FRA", "destination": "JFK", "weight_kg": 100, "reply": "Hi, ok."}'
MAIL = {"subject": "Quote", "body": "100 kg FRA to JFK please", "sender": "a@b.mail"}


def ok(content=GOOD):
    return 200, {"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 10}}


def limit(retry_after):
    return 429, {"retry_after": float(retry_after), "detail": {"detail": "slow down"}}   # shape of mailbox.api on 429


class Clock:
    """A fake clock: sleeping only moves the time forward."""

    def __init__(self):
        self.t, self.sleeps = 1000.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class Gateway(unittest.TestCase):
    """Runs extract() against a scripted mailbox.api. Each script item is a (status, data) pair or an exception."""

    def run_extract(self, script, mail=MAIL, repeat_last=False, calls_time_out=False):
        self.clock, self.calls = Clock(), []

        def api(method, path, timeout=None, body=None):
            self.calls.append({"path": path, "timeout": timeout, "at": self.clock.t})
            self.clock.t += timeout if calls_time_out else 0          # a timed-out call costs its whole timeout
            step = script[min(len(self.calls), len(script)) - 1] if repeat_last else script[len(self.calls) - 1]
            if isinstance(step, BaseException):
                raise step
            return step

        with mock.patch.object(E.mailbox, "api", side_effect=api), mock.patch.object(E.config, "LLM_FAKE", False), \
                mock.patch.object(E, "_sleep", self.clock.sleep), mock.patch.object(E, "_clock", self.clock.now), \
                mock.patch.object(E, "_log") as self.log:
            return E.extract(dict(mail))

    def test_429_then_200_is_one_retry_after_the_retry_after(self):
        fields, usage = self.run_extract([limit(3), ok()])
        self.assertEqual((fields["origin"], fields["destination"]), ("FRA", "JFK"))
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.clock.sleeps, [3.0])                      # waited exactly what the server asked
        self.assertEqual(self.log.call_args[0][0], "gateway_retry")

    def test_5xx_then_200_is_one_retry(self):
        for status in (500, 502, 503, 504):
            fields, _ = self.run_extract([(status, "upstream down"), ok()])
            self.assertEqual(fields["weight_kg"], 100)
            self.assertEqual((len(self.calls), self.clock.sleeps), (2, [1]))

    def test_timeout_and_connection_errors_are_retried(self):
        for err in (socket.timeout("timed out"), urllib.error.URLError("connection refused"), ConnectionResetError()):
            fields, _ = self.run_extract([err, ok()])
            self.assertEqual(fields["origin"], "FRA")
            self.assertEqual(len(self.calls), 2)

    def test_success_is_exactly_one_call_and_no_wait(self):
        self.run_extract([ok()])
        self.assertEqual((len(self.calls), self.clock.sleeps), (1, []))
        self.assertEqual(self.calls[0]["timeout"], 45)                  # the success path is unchanged
        self.log.assert_not_called()

    def test_persistent_429_raises_only_after_the_budget(self):
        with self.assertRaises(RuntimeError) as cm:
            self.run_extract([limit(20)], repeat_last=True)
        self.assertEqual(len(self.calls), 5)                            # at 0, 20, 40, 60, 80 s
        self.assertEqual(sum(self.clock.sleeps), 80)
        self.assertLessEqual(sum(self.clock.sleeps), E.GATEWAY_RETRY_BUDGET_S)
        self.assertGreater(sum(self.clock.sleeps) + 20, E.GATEWAY_RETRY_BUDGET_S)   # one more wait would not fit
        self.assertIn("gateway 429", str(cm.exception))

    def test_persistent_5xx_stops_at_the_attempt_cap(self):
        with self.assertRaises(RuntimeError):
            self.run_extract([(503, "down")], repeat_last=True)
        self.assertEqual(len(self.calls), E.GATEWAY_MAX_ATTEMPTS)
        self.assertEqual(self.clock.sleeps, [1, 2, 4, 8, 8])

    def test_persistent_timeouts_stay_inside_the_budget(self):
        with self.assertRaises(RuntimeError):
            self.run_extract([socket.timeout("timed out")], repeat_last=True, calls_time_out=True)
        self.assertEqual(len(self.calls), 2)                            # 45 s + 1 s pause + 44 s = 90 s
        self.assertEqual([c["timeout"] for c in self.calls], [45, 44])  # the second try only gets what is left
        self.assertLessEqual(self.clock.t - 1000.0, E.GATEWAY_RETRY_BUDGET_S)

    def test_retry_after_longer_than_the_budget_raises_at_once(self):
        with self.assertRaises(RuntimeError):
            self.run_extract([limit(120), ok()])
        self.assertEqual((len(self.calls), self.clock.sleeps), (1, []))

    def test_other_4xx_is_not_retried(self):
        for status in (400, 401, 404, 422):
            with self.assertRaises(RuntimeError):
                self.run_extract([(status, {"detail": "bad request"}), ok()])
            self.assertEqual((len(self.calls), self.clock.sleeps), (1, []))

    def test_an_old_rfq_gets_a_smaller_budget(self):
        import time
        old = dict(MAIL, received_at=time.time() - (config.RFQ_MAX_AGE_S - 30))      # 30 s before it expires
        with self.assertRaises(RuntimeError):
            self.run_extract([limit(20)], mail=old, repeat_last=True)
        self.assertEqual(len(self.calls), 2)                            # at 0 and 20 s; 40 s would be past expiry

    def test_truncated_json_after_a_retry_still_gets_its_second_call(self):
        fields, usage = self.run_extract([(503, "down"), ok('{"origin": "FRA", "reply": "Hi, the pri'), ok()])
        self.assertEqual((fields["origin"], len(self.calls)), ("FRA", 3))
        self.assertEqual(usage["out"], 20)                              # both answered calls are counted


class GatewayThroughUrlopen(unittest.TestCase):
    """The same through the real mailbox.api: it must surface Retry-After and a timeout the way the retry reads them."""

    class Response:
        status, headers = 200, {}

        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def http_error(self, code, retry_after=None):
        headers = email.message.Message()
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return urllib.error.HTTPError("http://x", code, "error", headers, io.BytesIO(b'{"detail": "no"}'))

    def run_extract(self, script):
        clock, seen = Clock(), []

        def urlopen(req, timeout=None):
            seen.append(req.full_url)
            step = script[len(seen) - 1]
            if isinstance(step, BaseException):
                raise step
            return self.Response(step)

        with mock.patch.object(mailbox.urllib.request, "urlopen", side_effect=urlopen), \
                mock.patch.object(E.config, "LLM_FAKE", False), mock.patch.object(E, "_log"), \
                mock.patch.object(E, "_sleep", clock.sleep), mock.patch.object(E, "_clock", clock.now):
            fields, _ = E.extract(dict(MAIL))
        return fields, seen, clock

    def test_http_429_with_retry_after_header_then_200(self):
        fields, seen, clock = self.run_extract([self.http_error(429, retry_after=7), ok()[1]])
        self.assertEqual((fields["origin"], len(seen), clock.sleeps), ("FRA", 2, [7.0]))
        self.assertTrue(seen[0].endswith("/v1/gateway/chat/completions"))

    def test_http_503_then_200(self):
        fields, seen, clock = self.run_extract([self.http_error(503), ok()[1]])
        self.assertEqual((fields["origin"], len(seen), clock.sleeps), ("FRA", 2, [1]))

    def test_urlopen_timeout_then_200(self):
        fields, seen, clock = self.run_extract([socket.timeout("timed out"), ok()[1]])
        self.assertEqual((fields["origin"], len(seen)), ("FRA", 2))


AIRLINES = [{"code": c, "name": c} for c in ("AA", "BB", "CC")]


def rate(code, weight, total="300.00"):
    return 200, {"airline": "Air " + code, "airline_code": code, "transit_days": 2, "currency": "EUR", "total": total,
                 "rate_id": "R-%s-%s" % (code, weight), "chargeable_weight_kg": str(weight)}


class Portal(unittest.TestCase):
    """options() on a three-airline lane. `answer(code, n, weight)` scripts read number n of one airline."""

    def run_options(self, answer, weight_break=False, brackets=None, each_read_takes=0):
        self.clock, self.reads, lock = Clock(), [], threading.Lock()

        def api(method, path, body=None, params=None, timeout=20):
            if path == "/v1/portal/brackets":
                if isinstance(brackets, BaseException):
                    raise brackets
                return 200, {"breaks_kg": brackets or [0, 100, 300, 500]}
            code, weight = params["airline"], float(params["weight_kg"])
            with lock:
                self.reads.append(code)
                n = self.reads.count(code)
                self.clock.t += each_read_takes
            step = answer(code, n, weight)
            if isinstance(step, BaseException):
                raise step
            return step

        portal._BREAKS.clear()
        with mock.patch.object(config, "API_KEY", "x"), mock.patch.object(portal.mailbox, "api", api), \
                mock.patch.object(portal, "refresh_lanes"), mock.patch.object(portal, "_log") as self.log, \
                mock.patch.object(portal, "_sleep", self.clock.sleep), mock.patch.object(portal, "_clock", self.clock.now), \
                mock.patch.dict(portal.LANES, {("FRA", "JFK"): AIRLINES}):
            return portal.options("FRA", "JFK", 120, 0.5, weight_break=weight_break)

    def logged(self, kind):
        return [c[1] for c in self.log.call_args_list if c[0][0] == kind]

    def codes(self, opts):
        return sorted(o["airline_code"] for o in opts)

    def test_429_on_one_airline_keeps_the_others_and_is_logged(self):
        opts = self.run_options(lambda c, n, w: limit(40) if c == "BB" else rate(c, w))
        self.assertEqual(self.codes(opts), ["AA", "CC"])
        self.assertEqual(self.clock.sleeps, [])                         # 40 s is too long to wait: quote with what we have
        self.assertEqual(sorted(self.reads), ["AA", "BB", "CC"])        # and the dropped read is not asked again
        log = self.logged("portal_limit")[0]
        self.assertEqual((log["airlines"], log["lost"], log["retried"], log["retry_after"]), (["BB"], ["BB"], False, 40.0))

    def test_short_retry_after_is_waited_out_and_the_dropped_read_comes_back(self):
        opts = self.run_options(lambda c, n, w: limit(2) if (c == "BB" and n == 1) else rate(c, w))
        self.assertEqual(self.codes(opts), ["AA", "BB", "CC"])
        self.assertEqual(self.clock.sleeps, [2.0])
        self.assertEqual(sorted(self.reads), ["AA", "BB", "BB", "CC"])  # only the dropped read is repeated
        log = self.logged("portal_limit")[0]
        self.assertEqual((log["retried"], log["lost"]), (True, []))

    def test_still_limited_after_the_wait_is_dropped_not_looped(self):
        opts = self.run_options(lambda c, n, w: limit(2) if c == "BB" else rate(c, w))
        self.assertEqual(self.codes(opts), ["AA", "CC"])
        self.assertEqual((self.clock.sleeps, self.reads.count("BB")), ([2.0], 2))
        self.assertEqual(self.logged("portal_limit")[0]["lost"], ["BB"])

    def test_one_exception_does_not_drop_all_portal_options(self):
        opts = self.run_options(lambda c, n, w: socket.timeout("timed out") if c == "AA" else rate(c, w))
        self.assertEqual(self.codes(opts), ["BB", "CC"])
        log = self.logged("portal_read_error")[0]
        self.assertEqual((list(log["errors"]), log["lost"]), (["AA"], ["AA"]))
        self.assertIn("timed out", log["errors"]["AA"])

    def test_a_transient_error_is_retried_once_and_recovers(self):
        for first in (ConnectionResetError("reset"), (500, "boom"), (200, {"unexpected": "payload"})):
            opts = self.run_options(lambda c, n, w: first if (c == "CC" and n == 1) else rate(c, w))
            self.assertEqual(self.codes(opts), ["AA", "BB", "CC"])
            self.assertEqual((self.reads.count("CC"), self.clock.sleeps), (2, []))

    def test_a_slow_failure_is_not_retried_past_the_budget(self):
        opts = self.run_options(lambda c, n, w: socket.timeout("timed out") if c == "AA" else rate(c, w),
                                each_read_takes=portal.RETRY_BUDGET_S)
        self.assertEqual((self.codes(opts), self.reads.count("AA")), (["BB", "CC"], 1))
        self.assertFalse(self.logged("portal_read_error")[0]["retried"])

    def test_503_and_404_mean_not_priced_here_and_are_not_retried(self):
        opts = self.run_options(lambda c, n, w: (503, "ask the airline") if c == "AA" else (404, "") if c == "BB" else rate(c, w))
        self.assertEqual((self.codes(opts), len(self.reads)), (["CC"], 3))
        self.log.assert_not_called()

    def test_failed_brackets_read_keeps_the_base_options(self):
        opts = self.run_options(lambda c, n, w: rate(c, w), weight_break=True, brackets=socket.timeout("timed out"))
        self.assertEqual(self.codes(opts), ["AA", "BB", "CC"])
        self.assertEqual(len(self.logged("portal_read_error")), 3)

    def test_429_in_the_base_reads_still_skips_the_weight_break(self):
        opts = self.run_options(lambda c, n, w: limit(2) if (c == "BB" and n == 1) else rate(c, w), weight_break=True)
        self.assertEqual(self.codes(opts), ["AA", "BB", "CC"])
        self.assertFalse(any(o.get("weight_break") for o in opts))

    def test_429_in_the_weight_break_keeps_everything_read_so_far(self):
        opts = self.run_options(lambda c, n, w: limit(40) if w > 120 else rate(c, w), weight_break=True)
        self.assertEqual(self.codes(opts), ["AA", "BB", "CC"])
        self.assertEqual(len(self.reads), 4)                            # three base reads, the first extra read hits the limit
        log = self.logged("portal_limit")[0]
        self.assertEqual((log["phase"], log["retried"]), ("weight_break", False))

    def test_error_in_the_weight_break_only_ends_that_airlines_ladder(self):
        opts = self.run_options(lambda c, n, w: socket.timeout("timed out") if (c == "AA" and w > 120) else rate(c, w, "%.2f" % w),
                                weight_break=True)
        self.assertEqual(self.codes([o for o in opts if not o.get("weight_break")]), ["AA", "BB", "CC"])
        self.assertEqual(sorted({o["airline_code"] for o in opts if o.get("weight_break")}), ["BB", "CC"])


class QuoteSend(unittest.TestCase):
    """finalize() with DRY_RUN off and a scripted mailbox.api, so the real mailbox.send runs but nothing leaves."""

    @classmethod
    def setUpClass(cls):
        cls._saved = (config.DB_PATH, config.DRY_RUN, db._con)
        config.DB_PATH = os.path.join(tempfile.mkdtemp(), "t.db")
        db._con = None

    @classmethod
    def tearDownClass(cls):
        config.DB_PATH, config.DRY_RUN, db._con = cls._saved

    _tid = [990000]

    def session(self):
        self._tid[0] += 1
        tid = self._tid[0]
        fields = {"origin": "FRA", "destination": "JFK", "weight_kg": 100, "weight_kg_total": 100,
                  "volume_cbm_total": 0.5, "prefer": "cheapest", "language": "en"}
        options = [{"airline": "Lumen", "total": "500.00", "currency": "EUR", "total_eur": "500.00",
                    "transit_days": 3, "source": "sheet"}]
        db.con().execute("INSERT INTO sessions(thread_id,customer,subject,status,fields,reply_template,options,received_at)"
                         " VALUES(?,?,?,?,?,?,?,?)", (tid, "anna@customer.mail", "Quote FRA JFK", "new",
                                                      json.dumps(fields), "", json.dumps(options), 1.0))
        return tid

    def run_finalize(self, tid, script, expect_raise=None):
        self.posts, self.sleeps = [], []

        def api(method, path, body=None, params=None, timeout=20):
            self.assertEqual((method, path), ("POST", "/v1/mailbox/messages"))
            self.posts.append(body)
            step = script[len(self.posts) - 1]
            if isinstance(step, BaseException):
                raise step
            return step

        with mock.patch.object(config, "DRY_RUN", False), mock.patch.object(mailbox, "api", side_effect=api), \
                mock.patch.object(main.time, "sleep", self.sleeps.append):
            if expect_raise:
                with self.assertRaises(expect_raise):
                    main.finalize(tid)
            else:
                main.finalize(tid)
        return db.session(tid)

    def events(self, tid):
        return [r["kind"] for r in db.con().execute("SELECT kind FROM events WHERE thread_id=? ORDER BY id", (tid,))]

    def test_first_success_sends_exactly_once(self):
        tid = self.session()
        s = self.run_finalize(tid, [(201, {"id": 1})])
        self.assertEqual((s["status"], len(self.posts), self.sleeps), ("quoted", 1, []))
        self.assertEqual(self.posts[0]["in_reply_to"], tid)
        self.assertNotIn("quote_send_retry", self.events(tid))

    def test_failed_send_is_retried_and_then_succeeds(self):
        tid = self.session()
        s = self.run_finalize(tid, [(500, "boom"), (201, {"id": 1})])
        self.assertEqual((s["status"], len(self.posts), self.sleeps), ("quoted", 2, [2.0]))
        self.assertEqual(self.posts[0], self.posts[1])                  # the very same quote, not a new one
        ev = self.events(tid)
        self.assertEqual((ev.count("mail_out_failed"), ev.count("mail_out"), ev.count("quote_sent")), (1, 1, 1))

    def test_connection_failure_before_the_request_is_retried(self):
        tid = self.session()
        s = self.run_finalize(tid, [urllib.error.URLError("connection refused"), (201, {"id": 1})])
        self.assertEqual((s["status"], len(self.posts)), ("quoted", 2))

    def test_three_failures_mark_the_session_failed(self):
        tid = self.session()
        s = self.run_finalize(tid, [(503, "down")] * 3)
        self.assertEqual((s["status"], len(self.posts), self.sleeps), ("failed", 3, [2.0, 5.0]))
        self.assertIn("quote_failed", self.events(tid))

    def test_a_send_that_may_have_worked_is_never_sent_again(self):
        tid = self.session()
        self.run_finalize(tid, [socket.timeout("timed out")], expect_raise=socket.timeout)   # the reply got lost, the mail maybe not
        self.assertEqual(len(self.posts), 1)
        self.assertIn("quote_send_unknown", self.events(tid))
        self.run_finalize(tid, [(201, {"id": 1})])                      # a later tick must not send it either
        self.assertEqual(len(self.posts), 0)

    def test_nothing_is_sent_again_after_a_success_or_after_giving_up(self):
        sent, failed = self.session(), self.session()
        self.run_finalize(sent, [(201, {"id": 1})])
        self.run_finalize(failed, [(500, "boom")] * 3)
        for tid in (sent, failed):
            self.run_finalize(tid, [(201, {"id": 2})])
            self.assertEqual(len(self.posts), 0)
            self.assertEqual(self.events(tid)[-1], "quote_skipped_already_sent")

    def test_dry_run_sends_nothing_and_does_not_retry(self):
        tid = self.session()
        with mock.patch.object(config, "DRY_RUN", True), mock.patch.object(mailbox, "api") as api, \
                mock.patch.object(main.time, "sleep") as sleep:
            main.finalize(tid)
        api.assert_not_called()
        sleep.assert_not_called()
        self.assertEqual(db.session(tid)["status"], "quoted")


if __name__ == "__main__":
    unittest.main()
