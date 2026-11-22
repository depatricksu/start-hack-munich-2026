// Run: node --experimental-strip-types --test lib/alert-rules.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { mailAlert } from "./alert-rules.ts";

const type = (body, subject = "Booking BK-1") => mailAlert(subject, body)?.type ?? null;

test("big news alerts", () => {
  assert.equal(type("Flight MD 731 is delayed by 24 hours."), "delayed");
  assert.equal(type("Der Flug ist um 6 Stunden verspätet."), "delayed");
  assert.equal(type("Your cargo was offloaded and is delayed."), "offloaded");
  assert.equal(type("Booking BK-1 is cancelled: no capacity."), "cancelled");
  assert.equal(type("See below.", "Booking BK-1 delayed"), "delayed");
});

test("everyday mails stay quiet", () => {
  for (const b of ["Your booking is confirmed.", "Departed on time, no delays.", "Free cancellation until Friday.",
    "In case of delay we will inform you.", "The flight is not delayed.", "Arrived and delivered.",
    "Thanks.\n\nOn Sat, Lena wrote:\nIs it delayed?", "Thanks.\n> the flight was cancelled"]) assert.equal(type(b), null, b);
});
