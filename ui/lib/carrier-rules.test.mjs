// Run: node --test lib/carrier-rules.test.mjs  (Node 22.6+ reads the .ts file directly)
import test from "node:test";
import assert from "node:assert/strict";
import { classify, datesIn, flightIn, awbIn, keySentence } from "./carrier-rules.ts";

test("confirmations from the snapshot", () => {
  assert.equal(classify("Booking BK-XLWLOHNP confirmed", "your booking BK-XLWLOHNP is confirmed.\nStatus: booked and ready to ship"), "confirmed");
  assert.equal(classify("Re: Booking request GOOGLE-25263 DUS-TLV", "thank you for your booking.\nStatus: booked\nThe confirmation follows by mail."), "booked");
  assert.equal(classify("Ihre Buchung", "Ihre Buchung ist bestätigt."), "confirmed");
});

test("bad news wins over good news", () => {
  assert.equal(classify("Re: BK-1", "Your booking was confirmed, but the flight is delayed. New ETA 27 Nov."), "delayed");
  assert.equal(classify("Offload notice", "Shipment offloaded from flight XY123"), "cancelled");
  assert.equal(classify("Re: Buchung", "Leider müssen wir die Buchung stornieren."), "cancelled");
  assert.equal(classify("Re: Buchung", "Die Sendung ist verspätet."), "delayed");
  assert.equal(classify("Re: BK-1", "We are unable to accept this shipment."), "cancelled");
  assert.equal(classify("Re: BK-1", "Your cargo was rebooked on a new flight."), "rebooked");
  assert.equal(classify("Re: BK-1", "A fuel surcharge of 0.20 EUR/kg applies from Monday."), "price");
});

test("movement and info", () => {
  assert.equal(classify("Status", "The flight has departed."), "departed");
  assert.equal(classify("Status", "Cargo arrived at JFK."), "arrived");
  assert.equal(classify("POD", "Delivered to consignee, POD attached."), "delivered");
  assert.equal(classify("Hello", "Please find our office hours below."), "info");
});

test("our own quoted text does not change the type", () => {
  assert.equal(classify("Re: BK-1", "Confirmed.\n\nOn Mon, Ops wrote:\n> please cancel if not possible"), "confirmed");
  assert.equal(classify("Re: BK-1", "Confirmed.\n> could you cancel?"), "confirmed");
});

test("dates, flights, AWB", () => {
  assert.deepEqual(datesIn("New ETA 2026-11-27, departure 28 Nov", 2026), ["27 Nov 2026", "28 Nov 2026"]);
  assert.deepEqual(datesIn("neue Ankunft am 29.11.2026"), ["29 Nov 2026"]);
  assert.deepEqual(datesIn("This quote is valid until 21 Nov 2026 15:16 UTC."), []);
  assert.equal(flightIn("rebooked on flight LH 8160", null), "LH 8160");
  assert.equal(flightIn("now on MD1234 tomorrow", "MD"), "MD 1234");
  assert.equal(flightIn("Booking BK-XLWLOHNP Lane CGN-ORD", "MD"), null);
  assert.equal(awbIn("AWB 020-12345675 attached"), "020-12345675");
});

test("summary picks the sentence with the news", () => {
  assert.equal(keySentence("Hi there, Thanks for the update! We need to cancel the shipment. Best", /cancel/i), "We need to cancel the shipment.");
});
