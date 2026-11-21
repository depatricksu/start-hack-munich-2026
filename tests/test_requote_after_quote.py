"""5U, 22 Nov 00:38 (round 86): the customer changes the shipment AFTER our quote and asks for a new offer.

"Sorry for the change - the final packing list came in, and the shipment details have changed to:
 5 pieces, 1317 kg gross weight, 8.18 cbm. Everything else stays the same. Could you please update your offer?"
The clerk parked it as an unclear reply. It was re-quoted by hand (4511.03 EUR) and accepted.
"""
import json, os, tempfile, time, unittest
from unittest import mock

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import db, main  # noqa: E402
from booking import handlers  # noqa: E402
from sourcing import bids  # noqa: E402

CHANGE = ("Hi there,\n\nHope your day’s going well! Sorry for the change—the final packing list came in, and the shipment "
          "details have changed to:\n\n5 pieces, 1317 kg gross weight, 8.18 cbm\n\nEverything else stays the same. Could you "
          "please update your offer?\n\nCheers,\nKlaus Weidner")
CUSTOMER = "klaus@weidner.mail"


def quoted(tid, status="quoted"):
    fields = {"origin": "FRA", "destination": "SGN", "prefer": "fastest", "weight_kg": 753, "volume_cbm": 4.87,
              "weight_kg_total": 753.0, "volume_cbm_total": 4.87, "pickup_postcode": "64344", "language": "en",
              "pieces": [{"count": 3, "l_cm": None, "w_cm": None, "h_cm": None, "kg_each": None}], "customer_numbers": ["3", "753"]}
    chosen = {"airline": "Polaris Air Logistics", "origin": "FRA", "destination": "SGN", "total": "3118.58", "currency": "EUR",
              "transit_days": 2, "source": "portal", "rate_id": "R-old"}
    c = db.con()
    for t in ("sessions", "bids", "events"):
        c.execute("DELETE FROM %s WHERE thread_id IN (?, ?)" % t, (tid, -tid))
    c.execute("DELETE FROM mails WHERE thread_id=?", (tid,))
    c.execute("INSERT INTO mails(id, thread_id, sender, subject, body, received_at, raw) VALUES(?,?,?,?,?,?,?)",
              (tid, tid, CUSTOMER, "Fastest air freight option to SGN", "3 pieces, 753 kg, 4.87 cbm to SGN, fastest please",
               time.time() - 200, json.dumps({"id": tid, "from": CUSTOMER, "subject": "Fastest air freight option to SGN", "body": "x"})))
    c.execute("INSERT INTO sessions(thread_id, customer, subject, status, fields, chosen, received_at, deadline, quoted_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (tid, CUSTOMER, "Fastest air freight option to SGN", status, json.dumps(fields), json.dumps(chosen), time.time() - 200,
               time.time() - 110, time.time() - 120))
    bids.ensure()
    c.execute("INSERT INTO bids(thread_id, carrier, kind, requested_at, replied_at, email, role, required, status, total_eur) "
              "VALUES(?, 'Alpenblick Logistik', 'trucker', ?, ?, 'alpenblick@hackloop.mail', 'trucker', 1, 'ok', '158.20')",
              (tid, time.time() - 190, time.time() - 150))
    c.commit()


def follow(tid, body, mid):
    return {"id": mid, "thread_id": tid, "sender": CUSTOMER, "subject": "Re: Fastest air freight option to SGN", "body": body,
            "attachments": [], "received_at": time.time(), "is_thread_start": False}


class Requote(unittest.TestCase):
    def test_changed_details_on_an_open_quote_are_priced_again(self):
        tid = 8860001
        quoted(tid)
        with mock.patch.object(main, "price_and_quote") as price:
            handlers.handle_follow_up(follow(tid, CHANGE, tid + 1))
        self.assertEqual(price.call_count, 1)
        s = db.session(tid)
        f = json.loads(s["fields"])
        self.assertEqual((f["weight_kg_total"], f["volume_cbm_total"], f["pieces"][0]["count"]), (1317.0, 8.18, 5))
        self.assertEqual(f["revised"]["total"], "3118.58")                       # the mail can say which offer it replaces
        self.assertEqual(s["status"], "new")                                      # the normal path may send again
        self.assertGreater(s["deadline"], time.time() + 60)                       # a fresh bid wait, not the old one
        self.assertEqual(bids.rows(tid), [])                                      # old bids were for 753 kg: ask again
        self.assertEqual(len(bids.rows(-tid)), 1)                                 # and kept as history
        self.assertNotEqual(s["status"], "needs_human")

    def test_a_question_without_new_numbers_still_goes_to_a_person(self):
        tid = 8860002
        quoted(tid)
        with mock.patch.object(main, "price_and_quote") as price:
            handlers.handle_follow_up(follow(tid, "Could you update your offer with a later pickup date?", tid + 1))
        self.assertEqual(price.call_count, 0)
        self.assertEqual(db.session(tid)["status"], "needs_human")

    def test_a_plain_yes_still_books(self):
        self.assertEqual(handlers.classify("Thank you for your offer. That works for us, please go ahead and book it."), "accept")
        tid = 8860003
        quoted(tid)
        self.assertFalse(handlers.correction_after_quote(db.session(tid), follow(tid, "Yes please, book it.", tid + 1)))

    def test_the_same_numbers_are_no_change(self):
        tid = 8860004
        quoted(tid)
        self.assertFalse(handlers.correction_after_quote(db.session(tid), follow(tid, "Please update your offer: still 753 kg and 4.87 cbm.", tid + 1)))

    def test_the_new_offer_says_which_one_it_replaces(self):
        body = "Hi Klaus,\n\nPolaris Air Logistics is the best fit: 4511.03 EUR all-in.\n\nCheers\nLena Hofmann"
        out = main.revised_note(body, {"revised": {"total": "3118.58"}}, "en")
        self.assertTrue(out.startswith("Hi Klaus,\n\nThanks for the updated details. This offer replaces my earlier one (3118.58 EUR).\n\nPolaris"))
        self.assertIn("ersetzt mein vorheriges", main.revised_note(body, {"revised": {}}, "de"))


if __name__ == "__main__":
    unittest.main()
