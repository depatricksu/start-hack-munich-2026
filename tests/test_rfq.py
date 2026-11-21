"""Run: python -m unittest tests.test_rfq -v"""
import unittest

from shared.rfq import Level, Mode, Service, can_price, extract_rfq, gate, missing_fields, validate

ENV = dict(message_id="m1", customer_email="buyer@acme.hackloop.mail", received_at="2026-11-21T16:00:00Z")


def levels(issues):
    return {(i.field, i.level) for i in issues}


class TestExtract(unittest.TestCase):
    def test_complete_english(self):
        r = extract_rfq("RFQ MUC-LAX", "Hi, please quote 230 kg, 1.2 cbm, 3 pcs from MUC to LAX. Cheapest option please.", **ENV)
        self.assertEqual((r.origin, r.destination, r.weight_kg, r.volume_cbm, r.pieces), ("MUC", "LAX", 230, 1.2, 3))
        self.assertEqual(r.mode, Mode.CHEAPEST)
        self.assertEqual(r.chargeable_kg, 230)
        self.assertTrue(can_price(validate(r)))

    def test_german_city_names_and_decimal_comma(self):
        r = extract_rfq("Anfrage", "Bitte Angebot München nach Tokio, 1.250,5 kg, 4 Paletten 120x80x100 cm, eilig!", **ENV)
        self.assertEqual((r.origin, r.destination, r.weight_kg), ("MUC", "NRT", 1250.5))
        self.assertEqual(r.volume_cbm, 3.84)
        self.assertEqual(r.mode, Mode.FASTEST)

    def test_volume_weight_wins(self):
        r = extract_rfq("RFQ", "FRA to JFK, 100 kg, 2 cbm, cheapest", **ENV)
        self.assertEqual(r.chargeable_kg, 334)

    def test_door_to_port_derives_origin(self):
        r = extract_rfq("RFQ", "Pick up at 80331 Munich warehouse, deliver to Singapore airport, 500 kg, 2 cbm, cheapest", **ENV)
        self.assertEqual(r.service, Service.DOOR_TO_PORT)
        self.assertEqual((r.pickup_zone, r.origin, r.destination), ("80", "MUC", "SIN"))

    def test_missing_fields_go_to_llm(self):
        r = extract_rfq("Quote", "Hello, we have a shipment to Dubai, can you help?", **ENV)
        issues = validate(r)
        self.assertEqual(set(missing_fields(issues)), {"origin", "weight_kg"})
        self.assertFalse(can_price(issues))

    def test_mode_missing_is_warning_not_blocker(self):
        r = extract_rfq("RFQ", "HAM to MEX, 300 kg, 1.5 cbm", **ENV)
        self.assertIn(("mode", Level.WARNING), levels(validate(r)))
        self.assertTrue(can_price(validate(r)))

    def test_dangerous_goods_to_human(self):
        r = extract_rfq("RFQ", "FRA-ORD 200 kg 1 cbm lithium batteries UN3480, cheapest", **ENV)
        self.assertIn(("dangerous_goods", Level.HUMAN), levels(validate(r)))
        self.assertFalse(can_price(validate(r)))

    def test_odd_density_flags_units(self):
        r = extract_rfq("RFQ", "DUS to BOM 100 kg 120 cbm cheapest", **ENV)
        self.assertIn(("volume_cbm", Level.WARNING), levels(validate(r)))

    def test_zone_vs_origin_mismatch(self):
        r = extract_rfq("RFQ", "collect from 20095 Hamburg, fly from FRA to DXB, 400 kg 2 cbm cheapest", **ENV)
        self.assertIn(("origin", Level.WARNING), levels(validate(r)))

    def test_missing_envelope(self):
        r = extract_rfq("RFQ", "MUC to LAX 100 kg 0.5 cbm cheapest")
        self.assertIn(("message_id", Level.MISSING), levels(validate(r)))


class TestGate(unittest.TestCase):
    MAIL = {"id": 7, "thread_id": 7, "sender": "anna@x.hackloop.mail",
            "subject": "Quote HAM to BOG", "body": "Please quote 90 kg, 0.4 cbm from HAM to BOG, cheapest."}
    OK = {"origin": "HAM", "destination": "BOG", "weight_kg": 90, "volume_cbm": 0.4, "prefer": "cheapest",
          "kind": "new_request", "weight_kg_total": 90.0, "volume_cbm_total": 0.4}

    def test_clean_request_passes(self):
        self.assertEqual(gate(self.OK, self.MAIL), (True, ""))

    def test_not_a_request(self):
        ok, note = gate(dict(self.OK, kind="question"), self.MAIL)
        self.assertFalse(ok)
        self.assertIn("not_a_request", note)

    def test_multi_shipment(self):
        ok, note = gate(dict(self.OK, multi_shipment=True), self.MAIL)
        self.assertFalse(ok)
        self.assertIn("multi_shipment", note)

    def test_missing_weight_stops(self):
        f = dict(self.OK, weight_kg=None, weight_kg_total=0)
        ok, note = gate(f, self.MAIL)
        self.assertFalse(ok)
        self.assertIn("missing: weight_kg", note)

    def test_dangerous_goods_stops(self):
        ok, note = gate(dict(self.OK, dangerous_goods=True), self.MAIL)
        self.assertFalse(ok)
        self.assertIn("dangerous_goods", note)

    def test_mismatch_only_warns(self):
        ok, note = gate(dict(self.OK, weight_kg=900, weight_kg_total=900.0), self.MAIL)
        self.assertTrue(ok)
        self.assertIn("llm_regex_mismatch", note)

    def test_old_form_without_kind_still_passes(self):
        f = {k: v for k, v in self.OK.items() if k != "kind"}
        self.assertTrue(gate(f, self.MAIL)[0])


if __name__ == "__main__":
    unittest.main()
