"""5U, 21 Nov 22:17: requests and trucker offers come as attached files (PDF, Word, text, voice message).

Live: round 63 (thr 17236) and round 64 (thr 17565) were parked as not_a_request because the mail only said "please
find our request attached", and every trucker answer was routed to `tariff` because it had a file, so no bid was read.
"""
import os, random, time, unittest
from core import attachments, db
from router.route import route
from sourcing import bids

RFQ_BODY = ("Hello,\n\nplease find our request for an air freight quotation attached, as a Word document "
            "(quotation-request.docx). It has all details of the shipment.\n\nPlease reply by mail with your all-in "
            "price in EUR.\n\nPetra Hofmann\nExport Desk, Hofmann Textilwerk KG")
RFQ_FILE = ("Request for quotation\nHofmann Textilwerk KG\nAir freight quote request: Hamburg to YYZ\n\nCould you quote "
            "the fastest air freight option to YYZ (Toronto, CA), including the truck you'd arrange from our site in "
            "20103 (Hamburg), Germany?\n\nIt's 1 piece, with a gross weight of 827 kg and a volume of 2.92 cbm.")
ELBKANTE = ("OFFER TRK-5967\nElbkante Logistik | elbkante-logistik@hackloop.mail\nOffer valid until Offer date Lead time "
            "Route 21 Nov 2026 21:39 UTC\n21 Nov 2026 21:24 UTC\n27 hours from order to collection\n20103 (zone 20) to HAM "
            "Hamburg\nPos Description Quantity Unit price (EUR) Amount (EUR)\n1 Base charge, zone 20 1 68.00 68.00\n"
            "2 Weight charge 827 kg 0.09 74.43\nTotal 142.43\nNot part of this offer: waiting time at the pickup address "
            "after the first 30 minutes, 45.00\nEUR for each hour.")


def f(name, text):
    return {"filename": name, "ext": name.rsplit(".", 1)[-1], "bytes": len(text), "downloaded": True,
            "readable": bool(text), "known_type": True, "text": text}


class Router(unittest.TestCase):
    def mail(self, subject, files):
        return {"sender": "elbkante-logistik@hackloop.mail", "subject": subject, "body": "see the file",
                "attachments": files, "is_thread_start": False}

    def test_answer_to_our_bid_mail_with_a_file_is_a_bid(self):
        self.assertEqual(route(self.mail("Re: Pickup 20103 to HAM airport, 827 kg [BID-405]", [{"filename": "o.pdf"}])), "carrier_bid")

    def test_a_carrier_file_without_our_reference_is_still_a_tariff(self):
        self.assertEqual(route(self.mail("New rates from December", [{"filename": "rates.xlsx"}])), "tariff")


class RequestInTheFile(unittest.TestCase):
    def setUp(self):
        self.tid = random.randint(10**8, 10**9)
        db.con().execute("INSERT INTO mails(id, thread_id, sender, subject, body, received_at) VALUES(?,?,?,?,?,?)",
                         (self.tid, self.tid, "petra@hackloop.mail", "Request for quotation", RFQ_BODY, time.time()))

    def test_file_text_becomes_part_of_the_request(self):
        mail = {"id": self.tid, "thread_id": self.tid, "body": RFQ_BODY, "attachments_text": [f("quotation-request.docx", RFQ_FILE)]}
        self.assertTrue(attachments.inline_request(mail))
        self.assertIn("827 kg", mail["body"])
        self.assertIn("quotation-request.docx ---", mail["body"])
        self.assertIn("827 kg", db.con().execute("SELECT body FROM mails WHERE id=?", (self.tid,)).fetchone()["body"])

    def test_a_normal_request_with_a_packing_list_is_not_touched(self):
        body = "Please quote 827 kg, 2.92 cbm from HAM to YYZ, cheapest option."
        mail = {"id": self.tid, "thread_id": self.tid, "body": body, "attachments_text": [f("PL_1.xlsx", "Gross weight (kg) | 910")]}
        self.assertFalse(attachments.inline_request(mail))
        self.assertEqual(mail["body"], body)

    def test_a_file_we_cannot_read_changes_nothing(self):
        mail = {"id": self.tid, "thread_id": self.tid, "body": RFQ_BODY, "attachments_text": [f("voice-message.mp3", "")]}
        self.assertFalse(attachments.inline_request(mail))
        self.assertEqual(attachments.unreadable(mail), ["voice-message.mp3"])


class OfferInTheFile(unittest.TestCase):
    def test_lead_time_is_read_by_code(self):
        self.assertEqual(bids.lead_hours(ELBKANTE), 27)                       # not the "30 minutes" or "each hour" of the footnote
        self.assertEqual(bids.lead_hours("Collection          in 31 hours"), 31)
        self.assertEqual(bids.lead_hours("Collection: in 11 hours"), 11)
        self.assertEqual(bids.lead_hours("Lead time           28 hours from order to collection"), 28)
        self.assertEqual(bids.lead_hours("Our driver can be at the pickup address 13 hours after your order."), 13)
        self.assertIsNone(bids.lead_hours("We deliver in 2 days."))

    def test_the_reader_gets_the_file_text(self):
        mail = {"subject": "Re: Pickup 20103 to HAM airport, 827 kg [BID-405]", "body": "You find our price offer in the attachment.",
                "attachments_text": [f("price-offer-TRK-5967.pdf", ELBKANTE)]}
        self.assertIn("Total 142.43", attachments.as_text(mail))
        form, _ = bids.read_answer(mail)                                      # LLM_FAKE in tests: the crude regex reader
        self.assertFalse(form["declined"])
        self.assertIsNotNone(form["total"])


if __name__ == "__main__":
    unittest.main()
