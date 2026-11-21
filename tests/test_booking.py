"""Task 04: every customer answer to a quote, with fake mails, no network.
Run: python -m unittest tests.test_booking -v
"""
import datetime as dt, json, os, tempfile, unittest
from unittest import mock
from zoneinfo import ZoneInfo

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import config, db, main  # noqa: E402
from booking import crm, handlers, meeting, replies  # noqa: E402

CUSTOMER = "anna.schmidt@customer-example.mail"
RFQ = "Hi, please quote 90 kg, 0.4 cbm from HAM to BOG. Cheapest please."
BERLIN = ZoneInfo("Europe/Berlin")


def mail(id, body, subject="Quote HAM to BOG", sender=CUSTOMER, refs=None):
    return main.mailbox.normalize({"id": id, "from": sender, "subject": subject, "body": body,
                                   "references": refs or [], "in_reply_to": refs[-1] if refs else None})


def sent(thread_id):
    rows = db.con().execute("SELECT data FROM events WHERE kind IN ('mail_out_dry_run','mail_out') AND thread_id=?",
                            (thread_id,))
    return [json.loads(r["data"]) for r in rows]


def quote(tid, portal=False, rfq=RFQ, sender=CUSTOMER):
    main.process(mail(tid, rfq, sender=sender))
    if portal:   # pretend the portal won: chosen option carries a rate_id
        s = db.session(tid)
        chosen = dict(json.loads(s["chosen"]), source="portal", rate_id="R-test12345678", airline="Riverbend Cargo")
        db.update_session(tid, chosen=chosen)
    return db.session(tid)


def answer(tid, n, body, sender=CUSTOMER):
    main.process(mail(tid + n, body, "Re: Quote HAM to BOG", sender=sender, refs=[tid]))


class TestClassify(unittest.TestCase):
    def test_words(self):
        c = handlers.classify
        self.assertEqual(c("Great, please book it."), "accept")
        self.assertEqual(c("Passt, bitte buchen."), "accept")
        self.assertEqual(c("No thanks, too expensive."), "decline")
        self.assertEqual(c("We went with another forwarder."), "decline")
        self.assertEqual(c("Too expensive, can you do better?"), "better_price")
        self.assertEqual(c("Geht es günstiger?"), "better_price")
        self.assertEqual(c("Could you do it faster?"), "faster")          # red-team round 4: we offer the fastest option
        self.assertEqual(c("Yes please book.\n\n> Our all-in price is ... could you?"), "accept")


class TestOutcomes(unittest.TestCase):
    def test_accept_portal_then_confirmed(self):
        tid = 1000
        self.assertEqual(quote(tid, portal=True)["status"], "quoted")
        answer(tid, 1, "Yes, please book it.")
        b = crm.get(tid)
        self.assertEqual((b["status"], b["booking_reference"]), ("booked", "BK-DRYRUN00"))
        self.assertEqual(db.session(tid)["status"], "booked")
        self.assertIn("BK-DRYRUN00", sent(tid)[-1]["body"])
        main.process(mail(1100, "Your booking is confirmed.", "Booking BK-DRYRUN00 confirmed",
                          sender="riverbend-airlines-cargo@hackloop.mail"))
        self.assertEqual(crm.get(tid)["status"], "confirmed")
        self.assertIn("confirmed", sent(tid)[-1]["body"])

    def test_accept_sheet_airline_books_by_mail(self):
        tid = 2000
        self.assertEqual(json.loads(quote(tid)["chosen"])["source"], "sheet")
        answer(tid, 1, "Go ahead.")
        self.assertEqual(crm.get(tid)["status"], "requested")
        to = [m["to"] for m in sent(tid)]
        self.assertIn("cobalt-skylift@hackloop.mail", to)
        self.assertEqual(to[-1], CUSTOMER)
        main.process(mail(2100, "Booked for GOOGLE-2000.", "Booking BK-ABC12345 confirmed",
                          sender="cobalt-skylift@hackloop.mail"))
        self.assertEqual((crm.get(tid)["status"], crm.get(tid)["booking_reference"]), ("confirmed", "BK-ABC12345"))

    def test_decline_is_just_lost(self):
        tid = 3000
        quote(tid)
        answer(tid, 1, "No thanks, we found another option.")
        self.assertEqual(db.session(tid)["status"], "lost")
        self.assertEqual(len(sent(tid)), 1)        # only the quote, no decline mail
        self.assertIsNone(crm.get(tid))

    def test_german_decline_is_lost(self):
        tid = 3500
        quote(tid)
        answer(tid, 1, "Nein danke, wir haben einen anderen Anbieter.")
        self.assertEqual(db.session(tid)["status"], "lost")
        self.assertEqual(len(sent(tid)), 1)

    def test_better_price_small_shipment_keeps_best_rate(self):
        tid = 4000
        quote(tid)                                            # cheapest already quoted, 432.00 EUR < 1500
        answer(tid, 1, "Too expensive for us. Can you do a better price?")
        s = db.session(tid)
        self.assertEqual(s["status"], "quoted")               # offer stays open, a "book it" still books
        self.assertIn("432.00 EUR", sent(tid)[-1]["body"])
        answer(tid, 2, "Ok, please book it.")
        self.assertEqual(crm.get(tid)["status"], "requested")

    def test_better_price_offers_cheaper_option(self):
        tid = 4100
        quote(tid, rfq=RFQ.replace("Cheapest", "Fastest"))    # fastest quoted: Yellowtail 514.80
        self.assertIn("Yellowtail", json.loads(db.session(tid)["chosen"])["airline"])
        answer(tid, 1, "Hmm, is there something cheaper?")
        body = sent(tid)[-1]["body"]
        self.assertIn("Cobalt Skylift", body)
        self.assertIn("432.00 EUR", body)
        self.assertEqual(json.loads(db.session(tid)["chosen"])["airline"], "Cobalt Skylift")
        answer(tid, 2, "Great, book it.")                     # books the cheaper one
        self.assertEqual(crm.get(tid)["airline"], "Cobalt Skylift")

    def test_better_price_big_shipment_offers_meeting_in_customer_time(self):
        tid = 4200
        quote(tid, sender="joe@buyer-example.us")
        with mock.patch.object(handlers, "MEETING_MIN_EUR", handlers.Decimal("100")):
            answer(tid, 1, "Too expensive for us. Can you do a better price? I'm in New York (EST).",
                   sender="joe@buyer-example.us")
        s = db.session(tid)
        self.assertEqual(s["status"], "meeting_proposed")
        body = sent(tid)[-1]["body"]
        self.assertIn("EST", body)                 # times shown in the customer's zone
        self.assertIn("CET", body)                 # and in ours
        self.assertEqual(body.count("\n- "), 3)    # three slots offered
        self.assertIsNone(crm.get(tid))            # nothing booked
        answer(tid, 2, "Tuesday works, please confirm.", sender="joe@buyer-example.us")       # picking a time is not a booking
        self.assertEqual(db.session(tid)["status"], "needs_human")
        self.assertIsNone(crm.get(tid))

    def test_unclear_goes_to_human(self):
        tid = 5000
        quote(tid)
        answer(tid, 1, "Can you ship it on Friday instead?")
        self.assertEqual(db.session(tid)["status"], "needs_human")
        self.assertEqual(len(sent(tid)), 1)        # only the quote, no guessing

    def test_second_answer_after_booking_is_ignored(self):
        tid = 5500
        quote(tid, portal=True)
        answer(tid, 1, "Please book.")
        answer(tid, 2, "Please book.")
        self.assertEqual(sum(1 for m in sent(tid) if "BK-DRYRUN" in m["body"]), 1)


class TestScams(unittest.TestCase):
    """Found by red-teaming: fake confirmations, strangers, conditional yes, new facts in the yes."""

    def test_customer_cannot_fake_confirmation(self):
        tid = 7000
        quote(tid, portal=True)
        answer(tid, 1, "Please book it.")
        main.process(mail(7100, "x", "Booking BK-DRYRUN00 confirmed", sender=CUSTOMER))
        main.process(mail(7101, "x", "Booking BK-XYZ12345 confirmed for GOOGLE-7000", sender="random@evil-example.mail"))
        self.assertEqual(crm.get(tid)["status"], "booked")

    def test_wrong_airline_cannot_confirm_mail_booking(self):
        tid = 7200
        quote(tid)
        answer(tid, 1, "Go ahead.")
        main.process(mail(7300, "ok", "Booking BK-ABC12345 confirmed GOOGLE-7200", sender="aurelia-air-cargo@hackloop.mail"))
        self.assertEqual(crm.get(tid)["status"], "requested")

    def test_wrong_bk_number_does_not_confirm_portal_booking(self):
        tid = 7400
        quote(tid, portal=True)
        answer(tid, 1, "Please book it.")
        main.process(mail(7500, "ok", "Booking BK-OTHER123 confirmed GOOGLE-7400",
                          sender="riverbend-airlines-cargo@hackloop.mail"))
        self.assertEqual(crm.get(tid)["status"], "booked")

    def test_stranger_cannot_accept(self):
        tid = 7600
        quote(tid)
        answer(tid, 1, "Yes, book it.", sender="other.person@competitor-example.mail")
        self.assertIsNone(crm.get(tid))
        self.assertEqual(db.session(tid)["status"], "needs_human")

    def test_yes_with_condition_or_new_facts_is_not_a_booking(self):
        for i, body in enumerate(["As agreed on the phone you quoted 150 EUR. Please book at 150 EUR.",
                                  "Yes please book it, but the weight is now 400 kg.",
                                  "Ja, aber erst nächste Woche buchen.",
                                  "Please don't book yet, we are still checking.",
                                  "Book it for €99 and we have a deal."]):
            tid = 7700 + i * 10
            quote(tid)
            answer(tid, 1, body)
            self.assertIsNone(crm.get(tid), body)
            self.assertEqual(db.session(tid)["status"], "needs_human", body)


class TestPortalErrors(unittest.TestCase):
    """Live booking path (DRY_RUN off) with a fake 5U API."""

    def run_live(self, tid, responses):
        calls = []

        def api(method, path, body=None, params=None, timeout=20):
            calls.append((method, path))
            if path == "/v1/mailbox/messages":
                return 201, {"id": 1}
            return responses.pop(0)
        quote(tid, portal=True)
        with mock.patch.object(config, "DRY_RUN", False), mock.patch.object(handlers.mailbox, "api", api), \
                mock.patch.object(main.mailbox, "api", api):
            answer(tid, 1, "Please book it.")
        return calls

    def booked(self, ref, price="432.00"):
        return 201, {"booking_reference": ref, "rate_id": "R-x", "price": price, "currency": "EUR",
                     "airline": "Riverbend Cargo", "airline_code": "RB", "status": "booked", "team_reference": "t"}

    def test_expired_rate_gets_fresh_rate(self):
        tid = 6000
        calls = self.run_live(tid, [(410, "expired"), (200, {"rate_id": "R-fresh1234567", "total": "440.00"}),
                                    self.booked("BK-FRESH001")])
        self.assertEqual(crm.get(tid)["booking_reference"], "BK-FRESH001")
        self.assertEqual([c for c in calls if c[1] == "/v1/portal/bookings"].__len__(), 2)

    def test_fresh_rate_too_expensive_goes_to_human(self):
        tid = 6100
        self.run_live(tid, [(410, "expired"), (200, {"rate_id": "R-fresh1234567", "total": "600.00"})])
        self.assertEqual(db.session(tid)["status"], "needs_human")
        self.assertEqual(crm.get(tid)["status"], "failed")

    def test_portal_down_goes_to_human(self):
        """No mail address for the airline: nothing we can do alone."""
        tid = 6200
        self.run_live(tid, [(503, "booking system down, mail the airline")])
        self.assertIn("book by email", db.session(tid)["note"])

    def test_portal_down_books_by_mail_when_we_know_the_airline(self):
        """5U 21:00 (request 13471): 503 'Booking is not available for Xenon. Please book by email' -> mail the airline."""
        tid = 6250
        with mock.patch.dict(handlers.AIRLINE_EMAIL, {"riverbend cargo": "riverbend-cargo@hackloop.mail"}):
            self.run_live(tid, [(503, {"detail": "Booking is not available for Riverbend Cargo. Please book by email"})])
        self.assertEqual(db.session(tid)["status"], "booking_requested")       # not needs_human
        self.assertEqual(crm.get(tid)["status"], "requested")
        mails = sent(tid)
        self.assertTrue(any(m["to"] == "riverbend-cargo@hackloop.mail" and "R-test12345678" in m["body"] for m in mails))
        self.assertTrue(any(m["to"] == CUSTOMER for m in mails[1:]))            # the customer was told

    def live(self, responses):
        """Patches for the live path; use as a context manager around answer()/main.process()."""
        def api(method, path, body=None, params=None, timeout=20):
            if path == "/v1/mailbox/messages":
                return 201, {"id": 1}
            return responses.pop(0)
        return mock.patch.multiple(handlers.mailbox, api=api), mock.patch.object(config, "DRY_RUN", False)

    def test_booking_price_above_quote_asks_the_customer(self):
        """5U 20:45 (rounds 48, 49): the portal booked 10% above the quoted rate and we confirmed the old price
        (-22.5 points each). Now: no 'booked at <old price>' mail; the customer gets the new total and a question."""
        tid = 6400
        quote(tid, portal=True)
        p1, p2 = self.live([self.booked("BK-UP000001", price="475.20")])          # quote was 432.00
        with p1, p2, mock.patch.object(main.mailbox, "api", handlers.mailbox.api):
            answer(tid, 1, "Please book it.")
            self.assertEqual(db.session(tid)["status"], "reprice_proposed")
            mails = [m for m in sent(tid) if m["to"] == CUSTOMER]
            self.assertIn("475.20", mails[-1]["body"]); self.assertIn("432.00", mails[-1]["body"])
            self.assertFalse(any("BK-UP000001" in m["body"] for m in mails))       # nothing confirmed at the old price
            # the airline's confirmation arrives before the customer answers: recorded, but no 'confirmed' mail yet
            main.process(main.mailbox.normalize({"id": tid + 5, "from": "riverbend-airlines-cargo@hackloop.mail",
                                                 "subject": "Booking BK-UP000001 confirmed",
                                                 "body": "Booking reference: BK-UP000001\nYour reference: %s\nPrice: 475.20 EUR" % crm.team_reference(tid)}))
            self.assertEqual(db.session(tid)["status"], "reprice_proposed")
            self.assertEqual(len([m for m in sent(tid) if m["to"] == CUSTOMER]), len(mails))
            answer(tid, 2, "Yes, that is fine. Please go ahead.")
        self.assertEqual(db.session(tid)["status"], "confirmed")
        last = [m for m in sent(tid) if m["to"] == CUSTOMER][-1]["body"]
        self.assertIn("BK-UP000001", last)
        self.assertEqual(crm.get(tid)["price"], "475.20")

    def test_customer_declines_the_new_price(self):
        tid = 6460
        quote(tid, portal=True)
        p1, p2 = self.live([self.booked("BK-UP000002", price="475.20")])
        with p1, p2, mock.patch.object(main.mailbox, "api", handlers.mailbox.api):
            answer(tid, 1, "Please book it.")
            answer(tid, 2, "No thanks, we will not go ahead at that price.")
        s = db.session(tid)
        self.assertEqual(s["status"], "needs_human")
        self.assertIn("cancel booking BK-UP000002", s["note"])
        self.assertEqual(crm.get(tid)["status"], "cancel_pending")

    def test_booking_at_the_quoted_price_is_confirmed_as_before(self):
        self.assertIsNone(handlers.booked_above_quote({"total": "432.00", "currency": "EUR"}, {"price": "432.00", "currency": "EUR"}))
        self.assertIsNone(handlers.booked_above_quote({"total": "432.00", "currency": "EUR"}, {"price": "420.00", "currency": "EUR"}))
        self.assertEqual(str(handlers.booked_above_quote(                      # truck leg stays, the flight goes up 10%
            {"total": "4128.50", "currency": "EUR", "flight_total": "3699.20", "flight_currency": "EUR"},
            {"price": "4069.12", "currency": "EUR"})), "4498.42")

    def test_retry_200_counts_as_booked(self):
        tid = 6300
        self.run_live(tid, [(200, self.booked("BK-RETRY001")[1])])
        self.assertEqual(crm.get(tid)["status"], "booked")


class TestReplyVariety(unittest.TestCase):
    V = {"ROUTE": "HAM to BOG", "AIRLINE": "Riverbend", "PRICE": "358.20 EUR", "REF": "BK-1", "TRANSIT": 3}

    def test_many_variants_never_twice_in_a_row(self):
        texts = [replies.render("booked", "en", self.V, thread_id=t, customer="anna.schmidt@x.mail")[0]
                 for t in range(30)]
        self.assertGreaterEqual(len(set(texts)), 10)
        self.assertTrue(all(a != b for a, b in zip(texts, texts[1:])))
        self.assertTrue(all("{" not in t for t in texts))     # every placeholder filled

    def test_same_thread_same_text(self):
        a = replies.render("confirmed", "de", self.V, thread_id=77)[0]
        replies.render("confirmed", "de", self.V, thread_id=78)
        self.assertEqual(a.split("\n\n")[1], replies.render("confirmed", "de", self.V, thread_id=77)[0].split("\n\n")[1])

    def test_name_from_address(self):
        self.assertEqual(replies.first_name("anna.schmidt@x.mail"), "Anna")
        self.assertIsNone(replies.first_name("sales@x.mail"))
        self.assertIsNone(replies.first_name("j.doe@x.mail"))
        for t in range(10):
            text = replies.render("booked", "de", self.V, thread_id=t, customer="sales@x.mail")[0]
            self.assertNotIn("{NAME}", text)
            self.assertNotIn("Frau", text)


class TestCalendar(unittest.TestCase):
    NOW = dt.datetime(2026, 11, 21, 15, 0, tzinfo=BERLIN)          # Saturday afternoon

    def test_zone_detection(self):
        z = meeting.customer_zone
        self.assertEqual(str(z("call me, Singapore time", "x@y.mail")), "Asia/Singapore")
        self.assertEqual(str(z("", "buyer@firma.de")), "Europe/Berlin")
        self.assertEqual(z("I am on UTC+8", "x@y.mail").utcoffset(None), dt.timedelta(hours=8))

    def test_slots_skip_weekend_busy_and_night(self):
        ny = ZoneInfo("America/New_York")
        slots, _ = meeting.free_slots(ny, now=self.NOW)
        self.assertEqual(len(slots), 3)
        for s in slots:
            self.assertLess(s.weekday(), 5)                           # no weekend
            local = s.astimezone(ny)
            self.assertGreaterEqual(local.hour, 8)                    # not before 08:00 in New York
            self.assertTrue(9 <= s.astimezone(BERLIN).hour < 18)      # inside our working hours
        self.assertEqual(len({s.date() for s in slots}), 3)           # one per day

    def test_busy_slot_is_avoided(self):
        slots, _ = meeting.free_slots(BERLIN, now=self.NOW)
        mon = [s for s in slots if s.date() == dt.date(2026, 11, 23)][0]
        self.assertEqual(mon.astimezone(BERLIN).strftime("%H:%M"), "10:30")   # 09:00-10:30 team call is busy

    def test_far_east_customer(self):
        tokyo = ZoneInfo("Asia/Tokyo")
        slots, _ = meeting.free_slots(tokyo, now=self.NOW)
        for s in slots:
            self.assertTrue(8 <= s.astimezone(tokyo).hour < 19)


if __name__ == "__main__":
    unittest.main()


class TestHumanQuoteAccept(unittest.TestCase):
    """Live bug 21 Nov 16:05: quote sent by a human (no `chosen`), customer accepts -> crash."""

    def _human_quote(self, tid, reply):
        quote(tid)
        db.update_session(tid, chosen=None, status="quoted", reply=reply, note="sent by a human")
        return json.loads(db.session(tid)["options"])

    def test_price_in_reply_is_matched(self):
        opts = self._human_quote(97701, "")
        db.update_session(97701, reply="Hi Anna, all-in %s EUR with %s." % (opts[0]["total"], opts[0]["airline"]))
        answer(97701, 1, "Please go ahead and book it.")
        s = db.session(97701)
        self.assertNotEqual(s["status"], "needs_human", s["note"])
        self.assertEqual(json.loads(s["chosen"])["airline"], opts[0]["airline"])

    def test_unknown_price_goes_to_human_without_crash(self):
        self._human_quote(97711, "Hi Anna, special price 999.99 EUR.")
        answer(97711, 1, "Please go ahead and book it.")
        s = db.session(97711)
        self.assertEqual(s["status"], "needs_human")
        self.assertIn("no_chosen_quote", s["note"])


class TestNeverBookDecline(unittest.TestCase):
    def test_negated_go_ahead_is_a_decline(self):
        from booking.handlers import classify
        self.assertEqual(classify("That seems too low to be right, so we will not go ahead with it."), "decline")
        self.assertEqual(classify("We won't proceed, thanks anyway."), "decline")
        self.assertEqual(classify("We've decided not to book this one."), "decline")
        self.assertEqual(classify("We do not want to book this."), "decline")
        self.assertEqual(classify("Wir werden nicht buchen."), "decline")

    def test_not_yet_is_a_hold_not_a_decline(self):
        from booking.handlers import classify
        self.assertEqual(classify("Please do not book it yet, we are still checking."), "unclear")

    def test_plain_go_ahead_still_accepts(self):
        from booking.handlers import classify
        self.assertEqual(classify("Great, please go ahead and book it."), "accept")
        self.assertEqual(classify("Yes, book it."), "accept")


class TestSendingDocs(unittest.TestCase):
    def test_sending_dg_docs_books_right_away(self):
        """'We will send the DG documents' is the customer's yes (5U counted rounds 39-41 accepted): book now, the
        rate ID expires in ~15 min and a second mail may never come."""
        tid = 1700
        self.assertEqual(quote(tid, portal=True)["status"], "quoted")
        answer(tid, 1, "Thank you, good point. We will send you the dangerous goods documents shortly.")
        self.assertIn(db.session(tid)["status"], ("booked", "booking", "confirmed"))

    def test_clear_accept_still_books_directly(self):
        tid = 1710
        quote(tid, portal=True)
        answer(tid, 1, "Yes, please go ahead and book it.")
        self.assertIn(db.session(tid)["status"], ("booked", "booking", "confirmed"))

    def test_decline_on_awaiting_docs_is_lost(self):
        """A session already waiting for documents (older code path) still closes as lost on a decline."""
        tid = 1720
        quote(tid, portal=True)
        db.update_session(tid, status="awaiting_docs")
        answer(tid, 2, "On second thought, we will not go ahead. Thanks anyway.")
        self.assertEqual(db.session(tid)["status"], "lost")
