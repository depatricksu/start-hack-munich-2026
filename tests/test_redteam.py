"""Fixes from the 5U-style red-team run (21 Nov ~19:00). Run: python -m unittest tests.test_redteam"""
import os, tempfile, unittest
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
os.environ.setdefault("DRY_RUN", "1"); os.environ.setdefault("LLM_FAKE", "1"); os.environ.setdefault("FIVEU_API_KEY", "")
from llm import extract as llm  # noqa: E402
from core import main  # noqa: E402
from humanize.polish import signed_name  # noqa: E402

US = {"subject": "Air quote FRA to ORD",
      "body": "Hi,\n\ncheapest FRA to ORD please. 4 crates, 48 x 40 x 50 in each, total 2,200 lbs.\n\nThanks,\nMegan Cole"}


class TestUnits(unittest.TestCase):
    def test_pounds_and_inches_copied_by_the_model_are_converted(self):
        f = {"weight_kg": 2200, "pieces": [{"count": 4, "l_cm": 48, "w_cm": 40, "h_cm": 50, "kg_each": None}]}
        llm.fix_units(f, US)
        self.assertAlmostEqual(f["weight_kg"], 997.9, places=1)
        self.assertEqual((f["pieces"][0]["l_cm"], f["pieces"][0]["w_cm"], f["pieces"][0]["h_cm"]), (121.9, 101.6, 127.0))

    def test_already_converted_values_stay(self):
        f = {"weight_kg": 998, "pieces": [{"count": 4, "l_cm": 122, "w_cm": 102, "h_cm": 127, "kg_each": None}]}
        self.assertEqual(llm.fix_units(f, US), [])
        self.assertEqual(f["weight_kg"], 998)

    def test_metric_mail_untouched(self):
        f = {"weight_kg": 640, "pieces": [{"count": 2, "l_cm": 120, "w_cm": 80, "h_cm": 110, "kg_each": 320}]}
        mail = {"subject": "x", "body": "2 pallets 120 x 80 x 110 cm, 640 kg, ready in 2 days"}
        self.assertEqual(llm.fix_units(f, mail), [])

    def test_per_piece_pounds(self):
        f = {"weight_kg": None, "pieces": [{"count": 3, "l_cm": None, "w_cm": None, "h_cm": None, "kg_each": 550}]}
        llm.fix_units(f, {"subject": "", "body": "3 drums, each 550 lb"})
        self.assertAlmostEqual(f["pieces"][0]["kg_each"], 249.5, places=1)


class TestDeadline(unittest.TestCase):
    def test_must_arrive_by(self):
        t = "cheapest MUC to SIN, but it MUST arrive by 2026-11-27 at the latest. Ready at MUC on 2026-11-24."
        self.assertEqual(main.max_transit_days(t), 3)

    def test_german_deadline(self):
        self.assertEqual(main.max_transit_days("Ware ist am 2026-11-24 abholbereit und muss spätestens am 2026-11-28 in Dubai sein."), 4)

    def test_drop_off_date_is_not_a_deadline(self):
        self.assertIsNone(main.max_transit_days("ready on 2026-11-25, we deliver to FRA on 2026-11-26"))
        self.assertIsNone(main.max_transit_days("ready on 2026-11-25, pickup on 2026-11-26 at the latest."))
        self.assertIsNone(main.max_transit_days("ready for pickup on 2026-11-25. Please confirm the earliest available arrival."))


class TestSignedName(unittest.TestCase):
    def test_gruss_is_a_closing_not_a_name(self):
        self.assertEqual(signed_name("Hallo,\n\nMUC nach ORD bitte.\n\nGruß\nOliver Krause"), "Oliver")
        self.assertEqual(signed_name("Hallo,\n\nbitte.\n\nGruss\nOliver"), "Oliver")

    def test_unknown_language_closing_is_not_a_name(self):
        mail = "Dzień dobry,\n\nproszę o ofertę.\n\nPozdrawiam\nKatarzyna Nowak\nBaltic Meble, Gdańsk"
        self.assertEqual(signed_name(mail), "Katarzyna")
        self.assertEqual(signed_name("Hej,\n\noffert tack.\n\nMvh\nSven Berg"), "Sven")


class TestForeignLanguage(unittest.TestCase):
    def test_language_without_own_texts_gets_one_clean_english_mail(self):
        best = {"airline": "Fjordline Air Cargo", "total": "1767.33", "currency": "EUR", "transit_days": 4}
        fields = {"origin": "HAM", "destination": "JFK", "weight_kg_total": 690, "language": "pl"}
        tpl = ("Dzień dobry,\n\ndziękujemy za zapytanie. Dla przesyłki {ROUTE} oferujemy {PRICE} all-in z {AIRLINE}, "
               "czas tranzytu ok. {TRANSIT_DAYS} dni.\n\nPozdrawiamy\nAir Export Team")
        body, _ = llm.final_reply(tpl, best, fields, "k.nowak@baltic-meble.mail", 4242)
        self.assertNotIn("Dzień", body)
        self.assertNotIn("Pozdrawiamy", body)
        self.assertIn("1767.33", body)
        self.assertEqual(body.count(llm.SIGNER), 1)              # one signature, not two


class TestRound2(unittest.TestCase):
    """Red-team round 2 (21 Nov ~19:20): more raw units, EXW, customer replies."""
    def test_tonnes(self):
        f = {"weight_kg": 2.4}
        llm.fix_units(f, {"subject": "", "body": "6 crates, total 2.4 t, 9.8 cbm"})
        self.assertEqual(f["weight_kg"], 2400)

    def test_millimetres(self):
        f = {"weight_kg": 780, "pieces": [{"count": 3, "l_cm": 1200, "w_cm": 800, "h_cm": 1100, "kg_each": None}]}
        llm.fix_units(f, {"subject": "", "body": "3 Paletten, je 1200 x 800 x 1100 mm, gesamt 780 kg"})
        self.assertEqual((f["pieces"][0]["l_cm"], f["pieces"][0]["w_cm"], f["pieces"][0]["h_cm"]), (120, 80, 110))

    def test_net_becomes_gross(self):
        f = {"weight_kg": 640}
        llm.fix_units(f, {"subject": "", "body": "8 drums, net weight 640 kg, gross weight 712 kg, 2.1 cbm"})
        self.assertEqual(f["weight_kg"], 712)
        f = {"weight_kg": 712}
        self.assertEqual(llm.fix_units(f, {"subject": "", "body": "net weight 640 kg, gross weight 712 kg"}), [])

    def test_exw_means_door_pickup(self):
        mail = {"subject": "Quotation EXW Stuttgart - ORD", "body": "Incoterm EXW Brandt GmbH, Industriestr. 12, 70565 Stuttgart, "
                "to ORD. Tel +49 711 12345."}
        f = {"origin": "STR"}
        self.assertEqual(llm.fix_incoterm(f, mail), "70565")
        self.assertEqual(f["pickup_postcode"], "70565")
        self.assertIsNone(llm.fix_incoterm({"origin": "FRA"}, {"subject": "", "body": "FCA Frankfurt airport, 60549"}))

    def test_customer_replies(self):
        from booking.handlers import classify
        for text in ("Perfect, thank you. Please proceed with the booking.", "OK for us. Please arrange.",
                     "Yes, that works for us.", "Alles klar, machen wir so.", "Va bene, procedete pure."):
            self.assertEqual(classify(text), "accept", text)
        self.assertEqual(classify("Can you do any better on the price?"), "better_price")
        self.assertEqual(classify("Thanks, but we won't proceed."), "decline")
        self.assertEqual(classify("Please book, but only after we confirm the pickup date on Monday."), "unclear")
        self.assertEqual(classify("Yes, but please send the invoice in USD."), "unclear")


class TestPriceOutliers(unittest.TestCase):
    """A misread bid must never win the quote (core/main.py drop_price_outliers)."""
    def opts(self, *totals):
        return [{"airline": "A%d" % i, "total_eur": str(t), "transit_days": 3, "source": "bid"} for i, t in enumerate(totals)]

    def test_per_kg_rate_read_as_total_is_dropped(self):
        kept = main.drop_price_outliers(1, self.opts(2.85, 2400, 2550, 2610))
        self.assertEqual(sorted(x["total_eur"] for x in kept), ["2400", "2550", "2610"])

    def test_thousand_times_too_high_is_dropped(self):
        kept = main.drop_price_outliers(1, self.opts(2400, 2550, 2610000))
        self.assertEqual(len(kept), 2)

    def test_real_spread_is_kept(self):           # 3630 on 21 Nov: cheapest 0.51x the median, accepted
        o = self.opts(1000, 1800, 1960, 2000, 2400, 3600)
        self.assertEqual(main.drop_price_outliers(1, o), o)

    def test_too_few_options_untouched(self):
        o = self.opts(3, 2400)
        self.assertEqual(main.drop_price_outliers(1, o), o)


class TestExcludedAirlines(unittest.TestCase):
    """5U trap 21 Nov 20:09 (request 10823): 'Please do not offer Zephyr Steppe Cargo (ZS) for this shipment or for
    any of our future inquiries.'"""
    ULN = ("Could you please quote your cheapest air freight option to ULN (Ulaanbaatar, MN), including truck collection "
           "from our site in 65797 (Wiesbaden)?\n\nPlease do not offer Zephyr Steppe Cargo (ZS) for this shipment or for "
           "any of our future inquiries.\n\nBest regards\nPetra Meyer")

    def mail(self, mid, sender, body):
        from core import db, mailbox
        m = mailbox.normalize({"id": mid, "from": sender, "subject": "Air freight quote", "body": body})
        db.save_mail(m)
        db.new_session(m)
        return mid

    def opts(self):
        return [{"airline": a, "total_eur": t} for a, t in (("Zephyr Steppe Cargo", "2100"), ("Himalaya Bridge Air", "2300"),
                                                            ("Pampero Air Cargo", "2450"))]

    def test_excluded_airline_is_never_quoted(self):
        tid = self.mail(9810001, "petra@meyer-industrie.mail", self.ULN)
        kept = main.drop_excluded(tid, self.opts())
        self.assertNotIn("Zephyr Steppe Cargo", [x["airline"] for x in kept])
        self.assertEqual(len(kept), 2)

    def test_future_inquiry_of_the_same_customer(self):
        self.mail(9810011, "anna@future-test.mail", self.ULN)
        tid = self.mail(9810012, "anna@future-test.mail", "Cheapest to ULN please, 300 kg, 1.2 cbm, pickup 65797.")
        self.assertIn("Zephyr Steppe Cargo", main.excluded_airlines(tid))

    def test_other_customers_and_harmless_mentions_untouched(self):
        tid = self.mail(9810021, "x@other.mail", "Cheapest to ULN please. Zephyr Steppe Cargo was fine last time, no preference.")
        self.assertEqual(main.drop_excluded(tid, self.opts()), self.opts())
        tid = self.mail(9810022, "y@other.mail", "Fastest to ULN, 300 kg. We don't need pickup.")
        self.assertEqual(main.excluded_airlines(tid), set())


class TestBackAndForth(unittest.TestCase):
    """Red-team round 4 (21 Nov ~20:30): replies after our quote, and corrections before it."""
    QUOTE = "Hello Sara,\n\nwe can offer 1234.00 EUR all-in with Yellowtail, about 4 days. I'll book it right away if you agree?\n\nLena"

    def test_bottom_posted_yes(self):
        from booking.handlers import classify
        body = "On Sat, Lena Hofmann wrote:\n> " + self.QUOTE.replace("\n", "\n> ") + "\n\nOK, please book it. Thanks!\nSara"
        self.assertEqual(classify(body), "accept")

    def test_our_quoted_words_never_count(self):
        from booking.handlers import classify
        body = "Thanks, let me check internally.\n\nOn Sat, Lena Hofmann wrote:\n> " + self.QUOTE.replace("\n", "\n> ")
        self.assertEqual(classify(body), "unclear")

    def test_yes_in_subject_only(self):
        from booking.handlers import classify
        self.assertEqual(classify("", "Re: Air freight FRA-ORD - YES, BOOK IT"), "accept")
        self.assertEqual(classify("", "Re: Air freight FRA-ORD"), "unclear")

    def test_faster(self):
        from booking.handlers import classify
        self.assertEqual(classify("Do you have anything faster? We could pay a bit more."), "faster")
        self.assertEqual(classify("Gibt es auch etwas Schnelleres? Früher wäre gut."), "faster")
        self.assertEqual(classify("Can you do it cheaper?"), "better_price")

    def _session(self, tid, status, fields, note=""):
        from core import db, mailbox
        m = mailbox.normalize({"id": tid, "from": "sara@lindqvist-medtech.mail", "subject": "Air freight FRA-ORD",
                               "body": "cheapest FRA to ORD, 540 kg, 2.8 cbm"})
        db.save_mail(m)
        db.new_session(m)
        db.update_session(tid, status=status, fields=fields, note=note, customer="sara@lindqvist-medtech.mail",
                          chosen={"airline": "Yellowtail Air Freight", "origin": "FRA", "destination": "ORD", "total": "1234.00",
                                  "currency": "EUR", "transit_days": 4})

    def _reply(self, tid, n, body):
        from core import mailbox
        from booking import handlers
        handlers.handle_follow_up(mailbox.normalize({"id": tid + n, "from": "sara@lindqvist-medtech.mail", "subject": "Re: Air freight FRA-ORD",
                                                     "body": body, "in_reply_to": tid, "references": [tid]}))

    def test_clear_yes_after_an_unclear_reply_is_read(self):
        from core import db
        from booking import handlers
        tid = 9820000
        self._session(tid, "needs_human", {"origin": "FRA", "destination": "ORD", "weight_kg_total": 540}, note=handlers.UNCLEAR_NOTE)
        self._reply(tid, 1, "Great, then please book it.")
        self.assertNotEqual(db.session(tid)["status"], "needs_human")
        kinds = [r["kind"] for r in db.con().execute("SELECT kind FROM events WHERE thread_id=?", (tid,))]
        self.assertIn("follow_up", kinds)

    def test_correction_during_bid_wait_changes_the_weight(self):
        import json
        from core import db
        tid = 9820100
        self._session(tid, "waiting_bids", {"origin": "FRA", "destination": "ORD", "weight_kg_total": 540, "volume_cbm_total": 2.8})
        self._reply(tid, 1, "Sorry, correction: it is 6 pallets, total 760 kg and 3.6 cbm, not 540 kg.")
        f = json.loads(db.session(tid)["fields"])
        self.assertEqual((f["weight_kg_total"], f["volume_cbm_total"]), (760.0, 3.6))
        self.assertTrue(json.loads(db.session(tid)["options"]))            # sheet prices for the new weight


class TestAirlineSaysNo(unittest.TestCase):
    """Red-team round 5 (21 Nov ~23:15): 'Booking BK-... cancelled: no capacity' was handled as a confirmation and the
    customer was told 'confirmed, everything is set'."""
    def test_cancelled_booking_is_not_confirmed(self):
        from core import db, mailbox
        from booking import crm, handlers
        tid = 9830000
        m = mailbox.normalize({"id": tid, "from": "sara@lindqvist-medtech.mail", "subject": "Air freight FRA-ORD", "body": "x"})
        db.save_mail(m); db.new_session(m)
        db.update_session(tid, status="booked", customer="sara@lindqvist-medtech.mail")
        crm.upsert(tid, customer="sara@lindqvist-medtech.mail", subject="Air freight FRA-ORD", last_customer_mail_id=tid,
                   airline="Meridian Freightways", origin="FRA", destination="ORD", status="booked", booking_reference="BK-CANC0001")
        handlers.handle_booking_confirmation(mailbox.normalize({"id": tid + 1, "from": "no-reply@hackloop.mail",
            "subject": "Booking BK-CANC0001 cancelled", "body": "Booking BK-CANC0001 was cancelled: no capacity on the flight."}))
        self.assertEqual(crm.get(tid)["status"], "cancelled_by_airline")
        self.assertEqual(db.session(tid)["status"], "needs_human")
        sent = [r for r in db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind LIKE 'mail_out%'", (tid,))]
        self.assertEqual(sent, [])                                         # nobody tells the customer "confirmed"

    def test_real_confirmation_wording_still_confirms(self):
        from booking.handlers import AIRLINE_NO
        for t in ("Booking BK-AW8CXJCM confirmed", "Your booking BK-AW8CXJCM is confirmed. Flight MD 123 departs 26 Nov.",
                  "Booking BK-X1 confirmed, no changes."):
            self.assertIsNone(AIRLINE_NO.search(t), t)


class TestRound5Batch1(unittest.TestCase):
    """Red-team round 5 batch 1: after-booking mails, out-of-office, only-this-airline."""
    def _booked(self, tid):
        from core import db, mailbox
        from booking import crm
        m = mailbox.normalize({"id": tid, "from": "sara@lindqvist-medtech.mail", "subject": "Air freight FRA-ORD",
                               "body": "cheapest FRA to ORD, 540 kg. Please only use Meridian Freightways, our contracted carrier."})
        db.save_mail(m); db.new_session(m)
        db.update_session(tid, status="booked", customer="sara@lindqvist-medtech.mail")
        crm.upsert(tid, customer="sara@lindqvist-medtech.mail", subject="Air freight FRA-ORD", last_customer_mail_id=tid,
                   airline="Meridian Freightways", origin="FRA", destination="ORD", status="booked", booking_reference="BK-R5B1%04d" % (tid % 10000))

    def _reply(self, tid, n, body):
        from core import mailbox
        from booking import handlers
        handlers.handle_follow_up(mailbox.normalize({"id": tid + n, "from": "sara@lindqvist-medtech.mail", "subject": "Re: Air freight FRA-ORD",
                                                     "body": body, "in_reply_to": tid, "references": [tid]}))

    def test_cancel_change_complaint_reach_a_human(self):
        from core import db
        for i, (body, kind) in enumerate((("Please cancel the booking, our customer cancelled.", "CANCELLATION"),
                                          ("The goods will only be ready on 2026-11-28, please adjust.", "CHANGE"),
                                          ("The truck did not show up today!", "COMPLAINT"))):
            tid = 9840000 + i * 10
            self._booked(tid)
            self._reply(tid, 1, body)
            s = db.session(tid)
            self.assertEqual(s["status"], "needs_human")
            self.assertIn(kind, s["note"])
            acks = list(db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind LIKE 'mail_out%'", (tid,)))
            self.assertEqual(len(acks), 1)                                   # the customer is not left in silence

    def test_thank_you_after_booking_is_quiet(self):
        from core import db
        tid = 9840100
        self._booked(tid)
        self._reply(tid, 1, "Dear Ms Hofmann, thank you for confirming the booking for our shipment to ORD. Kind regards, Sara")
        self.assertEqual(db.session(tid)["status"], "booked")

    def test_out_of_office(self):
        from booking.handlers import classify
        self.assertEqual(classify("I am out of the office until Monday with limited access to e-mail."), "auto_reply")

    def test_only_this_airline(self):
        tid = 9840200
        self._booked(tid)
        self.assertEqual(main.required_airlines(tid), {"Meridian Freightways"})
        opts = [{"airline": "Yellowtail Air Freight", "total_eur": "1300"}, {"airline": "Meridian Freightways", "total_eur": "1500"}]
        self.assertEqual([x["airline"] for x in main.keep_required(tid, opts)], ["Meridian Freightways"])


class TestRound6Batch2(TestRound5Batch1):
    """Red-team round 6: status question after booking, offer validity, accept + insurance, special cargo warnings."""
    def test_cancel_change_complaint_reach_a_human(self):      # inherited helpers only
        pass

    def test_thank_you_after_booking_is_quiet(self):
        pass

    def test_status_question_gets_an_answer_not_an_alarm(self):
        from core import db
        tid = 9850000
        self._booked(tid)
        self._reply(tid, 1, "Hi Lena, where is my shipment now? Has it left Frankfurt yet?")
        self.assertEqual(db.session(tid)["status"], "booked")
        kinds = [r["kind"] for r in db.con().execute("SELECT kind FROM events WHERE thread_id=?", (tid,))]
        self.assertIn("after_booking_status_answered", kinds)

    def test_validity_and_insurance(self):
        from booking.handlers import classify
        self.assertEqual(classify("How long is this offer valid? We need internal approval until Tuesday."), "validity")
        self.assertEqual(classify("Please book it, and please make sure the goods are insured for EUR 25,000."), "accept")
        self.assertEqual(classify("Please book it, but for 750 kg instead."), "unclear")          # a real new fact still stops

    def test_special_cargo_warnings(self):
        from shared.rfq import special_cargo
        self.assertTrue(special_cargo({"pieces": [{"count": 1, "l_cm": 420, "w_cm": 230, "h_cm": 210, "kg_each": 3200}]}, ""))
        self.assertTrue(special_cargo({}, "2 pallets of frozen food samples at -18 °C"))
        self.assertTrue(special_cargo({}, "Please quote DAP, door delivery to our customer's warehouse"))
        self.assertEqual(special_cargo({"pieces": [{"count": 6, "l_cm": 120, "w_cm": 80, "h_cm": 110, "kg_each": 180}]},
                                       "6 pallets of machine parts"), [])


class TestFootersAndOutlookQuotes(unittest.TestCase):
    """Red-team round 7: a corporate footer ('We accept no liability') or an Outlook-quoted copy of OUR quote
    ('I'll get it booked') read as the customer's yes -> false booking."""
    OUR = "Hi Sara,\n\nyour 540 kg can go with Yellowtail for 1301.40 EUR. Just say the word and I'll get it booked.\n\nLena"
    FOOT = ("\n\n--\nSara Lindqvist\nThis e-mail is confidential. We accept no liability for viruses. "
            "Any booking or order is subject to our general terms.")

    def test_footer_is_not_an_answer(self):
        from booking.handlers import classify
        self.assertEqual(classify("Thanks, I need to check internally and will come back to you." + self.FOOT), "unclear")
        self.assertEqual(classify("Yes please, book it." + self.FOOT), "accept")

    def test_outlook_quote_is_not_an_answer(self):
        from booking.handlers import classify
        for mark in ("-----Original Message-----\nFrom: Lena Hofmann\nSent: Saturday 23:40",
                     "Von: Lena Hofmann <google@hackloop.mail>\nGesendet: Samstag, 21. November 2026",
                     "________________________________\nFrom: Lena Hofmann"):
            self.assertEqual(classify("Let me check with my manager first.\n\n%s\n\n%s" % (mark, self.OUR)), "unclear", mark)
        self.assertEqual(classify("Yes please book.\n\n-----Original Message-----\nFrom: Lena\nSent: today\n\n" + self.OUR), "accept")


class TestLookalikeYesNo(unittest.TestCase):
    """Red-team round 8: 'confirming receipt' is not a yes (was BOOKED); 'not a problem, go ahead' is not a no (was lost)."""
    def test_receipt_and_later_are_not_a_yes(self):
        from booking.handlers import classify
        for t in ("Confirming receipt of your offer, we will get back to you.",
                  "We confirm we received your quote and will review it on Monday.",
                  "Passt soweit, ich gebe Ihnen morgen Bescheid."):
            self.assertEqual(classify(t), "unclear", t)

    def test_benign_negations_are_not_a_no(self):
        from booking.handlers import classify
        for t in ("Not a problem at all, please go ahead.", "Never mind my previous question, please book it.",
                  "I don't see any issue, please proceed.", "No objections from our side, go ahead and book."):
            self.assertEqual(classify(t), "accept", t)
        for t in ("Thanks, but we will not proceed this time.", "We won't go ahead, thanks."):
            self.assertEqual(classify(t), "decline", t)
        for t in ("Please don't book yet.", "No problem, but please wait until Monday before booking."):
            self.assertEqual(classify(t), "unclear", t)


if __name__ == "__main__":
    unittest.main()
