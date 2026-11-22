// Which carrier mails are big enough to interrupt the forwarder. Pure, tested with alert-rules.test.mjs.
// Deliberately stricter than carrier-rules.ts: there every mail gets a label, here a false hit is a false alarm.

export type MailAlert = "delayed" | "offloaded" | "cancelled" | "damaged";

const RULES: [MailAlert, RegExp][] = [
  ["damaged", /\b(?:is|was|been|are|were) (?:\w+ )?damaged\b|\b(?:cannot|unable to) locate\b|(?:ist|wurde) beschädigt|nicht auffindbar/i],
  ["offloaded", /\boff-?load(?:ed|ing)?\b|\bleft behind\b|\b(?:not|could not be|was not) loaded\b|nicht verladen|ausgeladen/i],
  ["cancelled", /\bcancel+ed\b|\b(?:must|have to|had to|need to) cancel\b|\bno capacity\b|\bunable to (?:confirm|accept)\b|\bstorniert\b|\bstornieren\b|keine kapazität/i],
  ["delayed", /\bdelay(?:ed|s)?\b|\bpostponed\b|\brescheduled\b|\b(?:new|revised) et[ad]\b|verspät|verzöger|\bverschoben\b|(?:weather|storm|snow|\bfog\b|strike|customs|airport|airspace|runway|technical|unwetter|streik|\bzoll\b).{0,80}\b(?:suspended|grounded|closed|halted|stuck|held|on hold|pushed back|affects|nicht|gesperrt|fest)\b|\bwas diverted\b|missed (?:its|the) connection/i],
];
// Sentences that mention the word without being the news.
const BENIGN = /\bmay\b|\bmight\b|\bdespite\b|\breopened\b|\bresumed\b|\bnot (?:be |been )?(?:affected|damaged)\b|nicht (?:betroffen|beschädigt)|\b(?:no|without|avoid|any|possible|potential) delays?\b|\bnot (?:been |be )?(?:delayed|cancel+ed|offloaded)\b|free cancellation|\b(?:if|in case of|in the event of|falls)\b[^,]{0,50}(?:delay|cancel|offload|verspät|storn)|keine verspätung|nicht (?:verspätet|storniert)/i;

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
