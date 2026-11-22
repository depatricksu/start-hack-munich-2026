// Which carrier mails are big enough to interrupt the forwarder. Pure, tested with alert-rules.test.mjs.
// Deliberately stricter than carrier-rules.ts: there every mail gets a label, here a false hit is a false alarm.

export type MailAlert = "delayed" | "offloaded" | "cancelled";

const RULES: [MailAlert, RegExp][] = [
  ["offloaded", /\boff-?load(?:ed|ing)?\b|\bleft behind\b|\b(?:not|could not be|was not) loaded\b|nicht verladen|ausgeladen/i],
  ["cancelled", /\bcancel+ed\b|\b(?:must|have to|had to|need to) cancel\b|\bno capacity\b|\bunable to (?:confirm|accept)\b|\bstorniert\b|\bstornieren\b|keine kapazität/i],
  ["delayed", /\bdelay(?:ed|s)?\b|\bpostponed\b|\brescheduled\b|\b(?:new|revised) et[ad]\b|verspät|verzöger|\bverschoben\b/i],
];
// Sentences that mention the word without being the news.
const BENIGN = /\b(?:no|without|avoid|any|possible|potential) delays?\b|\bnot (?:been |be )?(?:delayed|cancel+ed|offloaded)\b|free cancellation|\b(?:if|in case of|in the event of|falls)\b[^,]{0,50}(?:delay|cancel|offload|verspät|storn)|keine verspätung|nicht (?:verspätet|storniert)/i;

export function mailAlert(subject: string, body: string): { type: MailAlert; sentence: string } | null {
  const own: string[] = [];
  for (const line of body.split(/\r?\n/)) {
    if (/^\s*(on .+wrote:|am .+schrieb.*:|-----\s*original message)/i.test(line)) break;
    if (!/^\s*>/.test(line)) own.push(line);
  }
  const parts = own.join("\n").split(/\n\s*\n|(?<=[.!?])\s+/).map((s) => s.replace(/\s+/g, " ").trim()).filter(Boolean);
  // The body sentence says more than the subject, so it is searched first; the subject still counts.
  const news = [...parts, subject].filter((s) => !BENIGN.test(s));
  for (const [type, re] of RULES) {
    const hit = news.find((s) => re.test(s));
    if (hit) return { type, sentence: hit.length > 170 ? `${hit.slice(0, 169)}…` : hit };
  }
  return null;
}
