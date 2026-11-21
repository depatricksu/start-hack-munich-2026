"""5U, 21 Nov 22:17: requests and trucker offers come as attached files (PDF, Word, text, voice message).

Live: round 63 (thr 17236) and round 64 (thr 17565) were parked as not_a_request because the mail only said "please
find our request attached", and every trucker answer was routed to `tariff` because it had a file, so no bid was read.
"""
import os, random, tempfile, time, unittest

# As in every test module: a fresh database, set BEFORE core is imported. Without these lines this module (first in
# the alphabet to import core) pinned the whole suite to the persistent data/forwarder.db, and a second run failed.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DRY_RUN"], os.environ["LLM_FAKE"], os.environ["FIVEU_API_KEY"] = "1", "1", ""

from core import attachments, db  # noqa: E402
from router.route import route  # noqa: E402
from sourcing import bids  # noqa: E402

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


VOICE_RFQ = ("Hello this is Klaus Weidner from Weiner Spielmann GmbH I am calling with a request for an airfreight quotation "
             "we have textile samples 11 pieces the gross weight is 1804 kg the volume is 17.18 m³ please collect the goods "
             "at our site in Germany the postcode is 51943 the shipment goes to Lima airport airport code LIM we want the "
             "cheapest option")
VOICE_OFFER = ("Good day Bowden Efrat here with a message for the forwarding team collection at postcode 51252 delivery to "
               "Cologne Airport 1410 kg the base charge is €115 the weight charge is €225.60 so the total is €340.60 waiting "
               "time after the first 30 minutes is €45 for each hour and that is not part of the total we need 12 hours from "
               "your order to the collection")


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

    def tearDown(self):                                   # leave nothing behind: other tests read the mails table
        db.con().execute("DELETE FROM mails WHERE id=?", (self.tid,))
        db.con().execute("DELETE FROM events WHERE thread_id=?", (self.tid,))
        db.con().commit()

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
        self.assertEqual(bids.lead_hours(VOICE_OFFER), 12)                    # a trucker's voice message, as transcribed

    def test_the_reader_gets_the_file_text(self):
        mail = {"subject": "Re: Pickup 20103 to HAM airport, 827 kg [BID-405]", "body": "You find our price offer in the attachment.",
                "attachments_text": [f("price-offer-TRK-5967.pdf", ELBKANTE)]}
        self.assertIn("Total 142.43", attachments.as_text(mail))
        form, _ = bids.read_answer(mail)                                      # LLM_FAKE in tests: the crude regex reader
        self.assertFalse(form["declined"])
        self.assertIsNotNone(form["total"])


class VoiceMessage(unittest.TestCase):
    """5U 22:29: 'I recorded our quotation request as a voice message (voice-message.mp3)'. Live: thr 18001."""

    def setUp(self):
        from dg import attach
        self.attach = attach
        self.saved = (attach.transcribe, attach.stt_binary, attach._STT_OFF_UNTIL[0])

    def tearDown(self):
        self.attach.transcribe, self.attach.stt_binary, self.attach._STT_OFF_UNTIL[0] = self.saved

    def test_an_mp3_goes_to_speech_recognition(self):
        self.attach.transcribe = lambda data, suffix=".mp3", locale="en-US": VOICE_RFQ
        self.assertEqual(self.attach.attachment_text(b"ID3\x04\x00" + b"\x00" * 50, "voice-message.mp3"), VOICE_RFQ)

    def test_the_transcript_becomes_the_request(self):
        tid = random.randint(10**8, 10**9)
        body = "Hello,\n\nI am on the road today, so I recorded our quotation request as a voice message."
        db.con().execute("INSERT INTO mails(id, thread_id, sender, subject, body, received_at) VALUES(?,?,?,?,?,?)",
                         (tid, tid, "klaus@hackloop.mail", "Voice message: quotation request", body, time.time()))
        mail = {"id": tid, "thread_id": tid, "body": body, "attachments_text": [f("voice-message.mp3", VOICE_RFQ)]}
        try:
            self.assertTrue(attachments.inline_request(mail))
            self.assertIn("1804 kg", mail["body"])
            self.assertIn("airport code LIM", mail["body"])
        finally:
            db.con().execute("DELETE FROM mails WHERE id=?", (tid,))
            db.con().execute("DELETE FROM events WHERE thread_id=?", (tid,))
            db.con().commit()

    def test_no_speech_tool_means_unreadable_and_no_second_wait(self):
        self.attach._STT_OFF_UNTIL[0] = 0.0
        self.attach.stt_binary = lambda report=None: None
        self.assertEqual(self.attach.transcribe(b"ID3" + b"\x00" * 20), "")
        self.assertGreater(self.attach._STT_OFF_UNTIL[0], time.time())       # the breaker is on: the next file returns at once
        self.assertEqual(self.attach.attachment_text(b"ID3" + b"\x00" * 20, "voice-message.mp3"), "")


if __name__ == "__main__":
    unittest.main()
