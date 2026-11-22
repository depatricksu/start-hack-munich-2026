"""Classification and extraction. The first block is the same cases as ui/lib/carrier-rules.test.mjs, so the UI and
carrierops read a mail the same way."""
import unittest

from carrierops import rules
from carrierops.rules import classify, dates_in, flight_in, awb_in, key_sentence


class SameAsUI(unittest.TestCase):
    def test_confirmations_from_the_snapshot(self):
        self.assertEqual(classify("Booking BK-XLWLOHNP confirmed", "your booking BK-XLWLOHNP is confirmed.\nStatus: booked and ready to ship"), "confirmed")
        self.assertEqual(classify("Re: Booking request GOOGLE-25263 DUS-TLV", "thank you for your booking.\nStatus: booked\nThe confirmation follows by mail."), "booked")
        self.assertEqual(classify("Ihre Buchung", "Ihre Buchung ist bestätigt."), "confirmed")

    def test_bad_news_wins(self):
        self.assertEqual(classify("Re: BK-1", "Your booking was confirmed, but the flight is delayed. New ETA 27 Nov."), "delayed")
        self.assertEqual(classify("Offload notice", "Shipment offloaded from flight XY123"), "cancelled")
        self.assertEqual(classify("Re: Buchung", "Leider müssen wir die Buchung stornieren."), "cancelled")
        self.assertEqual(classify("Re: Buchung", "Die Sendung ist verspätet."), "delayed")
        self.assertEqual(classify("Re: BK-1", "We are unable to accept this shipment."), "cancelled")
        self.assertEqual(classify("Re: BK-1", "Your cargo was rebooked on a new flight."), "rebooked")
        self.assertEqual(classify("Re: BK-1", "A fuel surcharge of 0.20 EUR/kg applies from Monday."), "price")

    def test_movement_and_info(self):
        self.assertEqual(classify("Status", "The flight has departed."), "departed")
        self.assertEqual(classify("Status", "Cargo arrived at JFK."), "arrived")
        self.assertEqual(classify("POD", "Delivered to consignee, POD attached."), "delivered")
        self.assertEqual(classify("Hello", "Please find our office hours below."), "info")

    def test_quoted_text_does_not_count(self):
        self.assertEqual(classify("Re: BK-1", "Confirmed.\n\nOn Mon, Ops wrote:\n> please cancel if not possible"), "confirmed")
        self.assertEqual(classify("Re: BK-1", "Confirmed.\n> could you cancel?"), "confirmed")

    def test_dates_flights_awb(self):
        self.assertEqual(dates_in("New ETA 2026-11-27, departure 28 Nov", 2026), ["27 Nov 2026", "28 Nov 2026"])
        self.assertEqual(dates_in("neue Ankunft am 29.11.2026"), ["29 Nov 2026"])
        self.assertEqual(dates_in("This quote is valid until 21 Nov 2026 15:16 UTC."), [])
        self.assertEqual(flight_in("rebooked on flight LH 8160", None), "LH 8160")
        self.assertEqual(flight_in("now on MD1234 tomorrow", "MD"), "MD 1234")
        self.assertIsNone(flight_in("Booking BK-XLWLOHNP Lane CGN-ORD", "MD"))
        self.assertEqual(awb_in("AWB 020-12345675 attached"), "020-12345675")

    def test_key_sentence(self):
        self.assertEqual(key_sentence("Hi there, Thanks for the update! We need to cancel the shipment. Best", r"cancel"),
                         "We need to cancel the shipment.")


class Refined(unittest.TestCase):
    def t(self, subject, body):
        return rules.classify_carrier(subject, body)[0]

    def test_flight_cancelled_but_rebooked_is_not_a_cancellation(self):
        body = ("flight YT 880 of 25 Nov has been cancelled for technical reasons. Your shipment BK-8RT4N1HX (GOOGLE-45001) "
                "is rebooked on YT 884 on 26 Nov 2026, ETA ORD 27 Nov 2026. No action needed.")
        self.assertEqual(rules.classify("Booking BK-8RT4N1HX - flight change", body), "cancelled")   # what the UI shows
        self.assertEqual(self.t("Booking BK-8RT4N1HX - flight change", body), "rebooked")           # what we act on
        self.assertEqual(rules.flights(body), ("YT 884", None))
        self.assertEqual(rules.eta_in(body, 2026), "2026-11-27")

    def test_offload(self):
        body = "your shipment was offloaded from YT 880 due to weight restrictions. We have protected it on YT 884, ETA ORD 29 Nov 2026."
        self.assertEqual(self.t("Booking BK-1 - offloaded", body), "offloaded")
        self.assertEqual(rules.flights(body), ("YT 884", "YT 880"))
        self.assertEqual(rules.eta_in(body, 2026), "2026-11-29")

    def test_booking_cancelled_with_offer(self):
        body = ("we regret that booking BK-9ZK3P6RE (your reference GOOGLE-43001) is cancelled: no capacity on YT 884. "
                "We can offer YT 890 on 28 Nov 2026 at the same rate.")
        self.assertEqual(self.t("Booking BK-9ZK3P6RE cancelled", body), "cancelled")
        self.assertEqual(rules.offer_in(body), ("YT 890", "2026-11-28"))

    def test_our_cancellation_confirmed(self):
        self.assertEqual(self.t("Booking BK-1 cancelled as requested", "has been cancelled as per your request."), "cancel_confirmed")

    def test_german_delay(self):
        body = ("Ihre Sendung mit Ihrer Referenz GOOGLE-42001 konnte wegen eines Fluggerätewechsels nicht mit YT 880 abfliegen. "
                "Neuer Flug YT 4412 am 26.11.2026, neue Ankunft in Chicago am 28.11.2026 gegen 09:15 Uhr.")
        self.assertEqual(self.t("Verspätung Ihrer Sendung GOOGLE-42001", body), "delayed")
        self.assertEqual(rules.eta_in(body, 2026), "2026-11-28 09:15")
        self.assertEqual(rules.flights(body)[0], "YT 4412")

    def test_delay_new_eta_not_old_date(self):
        body = ("was moved from YT 880 to YT 4412. New departure 26 Nov 2026 14:30, new ETA ORD 28 Nov 2026 09:15 (was 25 Nov).")
        self.assertEqual(rules.eta_in(body, 2026), "2026-11-28 09:15")
        self.assertEqual(rules.flights(body), ("YT 4412", "YT 880"))

    def test_delay_by_hours(self):
        self.assertEqual(rules.delay_by_hours("flight YT 880 FRA-ORD of 25 Nov is delayed by 24 hours"), 24.0)
        self.assertEqual(rules.delay_by_hours("All shipments will arrive one day later."), 24.0)
        self.assertEqual(rules.delay_by_hours("Die Sendung ist um 2 Tage verspätet"), 48.0)
        self.assertEqual(rules.delay_by_hours("verspätet um 2 Tage"), 48.0)

    def test_trucker_delivered_to_airport_is_not_pod(self):
        self.assertEqual(rules.classify_trucker("GOOGLE-1 pickup", "Picked up at 09:00, delivered to the airline terminal at FRA."), "handed_over")
        self.assertEqual(rules.classify_trucker("GOOGLE-1", "Ware heute abgeholt."), "picked_up")
        self.assertEqual(rules.classify_trucker("Re: Pickup order GOOGLE-1", "picked up today 09:10 and delivered to the "
                                                "Yellowtail cargo terminal FRA at 13:30."), "handed_over")
        self.assertEqual(rules.classify_trucker("GOOGLE-1", "Wir kommen 3 Stunden später."), "delayed")

    def test_price_and_refs(self):
        self.assertEqual(rules.price_in("Price: 1191.40 EUR"), 1191.40)
        self.assertEqual(rules.price_in("Preis: 1.191,40 EUR"), 1191.40)
        self.assertEqual(rules.refs_in("Booking BK-7Q2M9XKD / GOOGLE-41001"), {"bk": ["BK-7Q2M9XKD"], "google": [41001]})
        self.assertEqual(rules.lane_in("Flight YT 880 FRA-ORD 25 Nov delayed"), ("FRA", "ORD"))

    def test_customer_intent(self):
        self.assertEqual(rules.customer_intent("Re: x", "we have paid the invoice today by bank transfer."), "paid")
        self.assertEqual(rules.customer_intent("Re: x", "We will pay as soon as possible."), None)
        self.assertEqual(rules.customer_intent("Re: x", "where is our shipment now? When will it arrive?"), "status_question")
        self.assertEqual(rules.customer_intent("AW: x", "wo ist unsere Sendung gerade?"), "status_question")
        self.assertEqual(rules.customer_intent("Re: x", "Yes, please rebook.", "cancelled_by_airline"), "rebook_yes")
        self.assertEqual(rules.customer_intent("Re: x", "Thanks, that works. Please book it."), None)


if __name__ == "__main__":
    unittest.main()
