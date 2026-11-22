"""5U, about once an hour: two shipments in one quote, then "Please go ahead and book the first shipment now; we will
confirm the second shipment later" (live: requests 25791, 26215, 33297, 37892). The clerk read that as unclear and a
script outside the clerk booked it. Now booking/parts.py books the named shipment and keeps the other on hold.
Run: python -m unittest tests.test_book_named_shipments -v"""
import json, os, tempfile, time, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import config, db, main  # noqa: E402
from booking import crm, handlers, parts  # noqa: E402

CUSTOMER = "two-shipments@parts-test.mail"                    # its own address: one DB for the whole suite
SUBJECT = "Air freight quotes from MUC to SGN and ICN"
REQUEST = ("Could you check the fastest air freight option for each of the two shipments below?\n\n"
           "1. To SGN (Ho Chi Minh City, VN): automotive sensors, 6 pieces, gross weight 1592 kg, volume 6.77 cbm.\n"
           "2. To ICN (Seoul, KR): printed marketing material, 7 pieces, gross weight 813 kg, volume 6.04 cbm.")
LIVE = ("Thank you for your offer. Both prices work for us. Please go ahead and book the first shipment now; "
        "we will confirm the second shipment later.\n\nThanks a lot and have a lovely day!\nPetra Hofmann\nExport Desk")
P = [{"n": 1, "destination": "SGN"}, {"n": 2, "destination": "ICN"}]
CALLED = {1: ["SGN", "Ho Chi Minh City"], 2: ["ICN", "Seoul"]}


def part(dest, code, name, total, rate):
    return {"airline": name, "airline_code": code, "origin": "MUC", "destination": dest, "transit_days": 3, "currency": "EUR",
            "total": total, "total_eur": total, "source": "portal", "rate_id": rate, "billed_kg": "1592.0"}


def quoted(tid):
    """A sent quote for two shipments, as pricing/multi.py stored it before the shipments were numbered."""
    m = {"id": tid, "thread_id": tid, "sender": CUSTOMER, "subject": SUBJECT, "body": REQUEST, "received_at": time.time(), "raw": {}}
    db.save_mail(m)
    db.new_session(m)
    chosen = {"airline": "Nova Atlas Cargo + Ibisair Cargo", "total": "9250.40", "total_eur": "9250.40", "currency": "EUR",
              "transit_days": 3, "origin": "MUC", "destination": "SGN", "source": "multi",
              "parts": [part("SGN", "NV", "Nova Atlas Cargo", "5810.80", "R-test-sgn-%d" % tid),
                        part("ICN", "IB", "Ibisair Cargo", "3439.60", "R-test-icn-%d" % tid)]}
    fields = {"language": "en", "customer_first_name": "Petra", "multi_shipment": True, "shipments": [
        {"origin": "MUC", "destination": "SGN", "weight_kg": 1592, "volume_cbm": 6.77, "pieces": [], "prefer": "fastest"},
        {"origin": "MUC", "destination": "ICN", "weight_kg": 813, "volume_cbm": 6.04, "pieces": [], "prefer": "fastest"}]}
    db.update_session(tid, status="quoted", chosen=chosen, fields=fields, quoted_at=time.time(), reply="quote")


def answer(tid, n, body, sender=CUSTOMER, subject="Re: " + SUBJECT):
    main.process(main.mailbox.normalize({"id": tid + n, "from": sender, "subject": subject, "body": body,
                                         "references": [tid], "in_reply_to": tid}))
    s = db.session(tid)
    return s, json.loads(s["chosen"])["parts"]


def sent(tid):
    rows = db.con().execute("SELECT data FROM events WHERE kind IN ('mail_out_dry_run','mail_out') AND thread_id=?", (tid,))
    return [json.loads(r["data"]) for r in rows]


def events(tid, kind):
    return [json.loads(r["data"]) for r in db.con().execute("SELECT data FROM events WHERE thread_id=? AND kind=?", (tid, kind))]


class Reading(unittest.TestCase):
    def test_the_live_wording_books_only_the_first(self):
        self.assertEqual(parts.wanted(LIVE, P, CALLED), [1])

    def test_named_by_number_code_or_city(self):
        self.assertEqual(parts.wanted("We can now confirm the second shipment. Please go ahead and book it.", P, CALLED), [2])
        self.assertEqual(parts.wanted("Please book the Seoul shipment.", P, CALLED), [2])
        self.assertEqual(parts.wanted("Please go ahead with the shipment to SGN.", P, CALLED), [1])
        self.assertEqual(parts.wanted("Please book both.", P, CALLED), [1, 2])
        self.assertEqual(parts.wanted("Bitte buchen Sie die erste Sendung, die zweite bestätigen wir später.", P, CALLED), [1])
        self.assertEqual(parts.wanted("Both prices are fine, please go ahead.", P, CALLED), [1, 2])
        self.assertEqual(parts.wanted("Please book the first, not the second.", P, CALLED), [1])

    def test_a_thank_you_or_a_later_books_nothing(self):
        for text in ("Thanks for getting the SGN shipment booked! I’ll keep an eye out for the airline confirmation.",
                     "Good morning Lena, Thanks for confirming the SGN booking. Glad it’s all set!",
                     "Both look fine, we need to check internally and will confirm later.",
                     "Please do not book the second shipment yet.",
                     "That works for us, please go ahead and book it."):       # names none: on_quote decides (all of them)
            self.assertEqual(parts.wanted(text, P, CALLED), [], text)
        self.assertFalse(parts.mentions("That works for us, please go ahead and book it.", P, CALLED))

    def test_a_booked_shipment_is_never_wanted_again(self):
        done = [dict(P[0], booking_reference="BK-AAAA1111"), P[1]]
        self.assertEqual(parts.wanted("Please book both.", done, CALLED), [2])
        self.assertEqual(parts.wanted("Please book the remaining shipment as well.", done, CALLED), [2])


class Booking(unittest.TestCase):
    def test_first_now_second_later(self):
        """Request 37892, live 22 Nov 04:46."""
        tid = 930117
        quoted(tid)
        s, ps = answer(tid, 1, LIVE)
        self.assertEqual(s["status"], "booked")
        self.assertEqual((ps[0]["booking_reference"], ps[1].get("booking_reference")), ("BK-DRYRUN171", None))
        self.assertEqual(crm.get(tid)["booking_reference"], "BK-DRYRUN171")          # tracking and the airline's confirmation
        self.assertEqual((crm.get(tid)["destination"], crm.get(tid)["weight_kg"], crm.get(tid)["price"]), ("SGN", 1592.0, "5810.80"))
        body = sent(tid)[-1]["body"]
        self.assertEqual(len(sent(tid)), 1)
        for text in ("Hi Petra,", "Shipment 1 is booked: MUC to SGN with Nova Atlas Cargo, booking BK-DRYRUN171, 5810.80 EUR",
                     "Shipment 2 (MUC to ICN, 3439.60 EUR all-in with Ibisair Cargo) is on hold for you"):
            self.assertIn(text, body)
        self.assertIn("ON HOLD (booked when the customer says so): shipment 2 ICN 3439.60 EUR", s["note"])
        self.assertEqual(events(tid, "shipments_to_book")[0]["wanted"], [1])

    def test_the_second_is_booked_when_the_customer_says_so_and_its_confirmation_reaches_them(self):
        tid = 930218
        quoted(tid)
        answer(tid, 1, LIVE)
        s, ps = answer(tid, 2, "Hi Lena,\n\nThanks for getting the SGN shipment booked! I’ll keep an eye out for the airline confirmation.")
        self.assertEqual((s["status"], ps[1].get("booking_reference"), len(sent(tid))), ("booked", None, 1))   # a thank you books nothing
        s, ps = answer(tid, 3, "We can now confirm the second shipment. Please go ahead and book it.")
        self.assertEqual((s["status"], ps[1]["booking_reference"]), ("booked", "BK-DRYRUN182"))
        self.assertIn("Shipment 2 is booked: MUC to ICN with Ibisair Cargo, booking BK-DRYRUN182", sent(tid)[-1]["body"])
        self.assertNotIn("on hold", sent(tid)[-1]["body"])
        self.assertEqual(crm.get(tid)["booking_reference"], "BK-DRYRUN181")          # the CRM row stays the first booking
        main.process(main.mailbox.normalize({"id": tid + 9, "from": "riverbend-airlines-cargo@hackloop.mail",
                                             "subject": "Booking BK-DRYRUN182 confirmed", "body": "Your booking is confirmed."}))
        self.assertEqual(events(tid, "booking_confirmed")[-1], {"booking_reference": "BK-DRYRUN182", "part": 2})
        self.assertIn("the airline has confirmed booking BK-DRYRUN182 for shipment 2 (MUC to ICN", sent(tid)[-1]["body"])
        self.assertFalse(events(tid + 9, "confirmation_unmatched"))

    def test_a_plain_yes_books_all_of_them(self):
        tid = 930319
        quoted(tid)
        s, ps = answer(tid, 1, "Thank you for your offer. That works for us, please go ahead and book it.")
        self.assertEqual((s["status"], [p["booking_reference"] for p in ps]), ("booked", ["BK-DRYRUN191", "BK-DRYRUN192"]))
        body = sent(tid)[-1]["body"]
        self.assertIn("booking BK-DRYRUN191", body)
        self.assertIn("booking BK-DRYRUN192", body)
        self.assertIn("ON HOLD (booked when the customer says so): nothing", s["note"])

    def test_no_clear_request_books_nothing(self):
        tid = 930420
        quoted(tid)
        s, ps = answer(tid, 1, "Both look fine, we need to check internally and will confirm later.")
        self.assertEqual((s["status"], s["note"]), ("needs_human", handlers.UNCLEAR_NOTE))
        self.assertFalse(any(p.get("booking_reference") for p in ps))
        self.assertEqual(sent(tid), [])
        s, ps = answer(tid, 2, "Approved. Please book the shipment to ICN now.")     # the next mail is read again
        self.assertEqual((s["status"], ps[0].get("booking_reference"), ps[1]["booking_reference"]), ("booked", None, "BK-DRYRUN202"))

    def live(self, responses):
        calls = []

        def api(method, path, body=None, params=None, timeout=20):
            calls.append((method, path, body))
            return (201, {"id": 1}) if path == "/v1/mailbox/messages" else responses.pop(0)
        return calls, mock.patch.object(handlers.mailbox, "api", api), mock.patch.object(config, "DRY_RUN", False)

    def test_each_shipment_has_its_own_rate_and_reference(self):
        tid = 930521
        quoted(tid)
        ok = lambda ref, price: (201, {"booking_reference": ref, "price": price, "currency": "EUR", "status": "booked"})
        calls, a, b = self.live([ok("BK-LIVE00001", "5810.80"), ok("BK-LIVE00002", "3439.60")])
        with a, b:
            s, ps = answer(tid, 1, "Please book both.")
        booked = [c[2] for c in calls if c[1] == "/v1/portal/bookings"]
        self.assertEqual(booked, [{"rate_id": "R-test-sgn-%d" % tid, "team_reference": "GOOGLE-%d-1" % tid},
                                  {"rate_id": "R-test-icn-%d" % tid, "team_reference": "GOOGLE-%d-2" % tid}])
        self.assertEqual((s["status"], [p["booking_reference"] for p in ps]), ("booked", ["BK-LIVE00001", "BK-LIVE00002"]))

    def test_a_refused_booking_goes_to_a_person_and_the_customer_is_told_nothing(self):
        tid = 930622
        quoted(tid)
        calls, a, b = self.live([(500, {"detail": "boom"})])
        with a, b:
            s, ps = answer(tid, 1, LIVE)
        self.assertEqual(s["status"], "needs_human")
        self.assertIn("shipment 1 (SGN) could not be booked: booking 500", s["note"])
        self.assertFalse([c for c in calls if c[1] == "/v1/mailbox/messages"])
        self.assertIsNone(ps[0].get("booking_reference"))

    def test_booked_above_the_quote_is_never_confirmed_as_quoted(self):
        tid = 930723
        quoted(tid)
        calls, a, b = self.live([(201, {"booking_reference": "BK-ABOVE0001", "price": "6400.00", "currency": "EUR", "status": "booked"})])
        with a, b:
            s, ps = answer(tid, 1, LIVE)
        self.assertEqual((s["status"], ps[0]["booking_reference"]), ("needs_human", "BK-ABOVE0001"))
        self.assertIn("ABOVE the quoted flight price (6400.00 vs 5810.80)", s["note"])
        self.assertFalse([c for c in calls if c[1] == "/v1/mailbox/messages"])


if __name__ == "__main__":
    unittest.main()
