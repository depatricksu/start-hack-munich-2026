# Jury Q&A: the 10 most likely questions

Two sentences each. Say the first sentence, add the second only if there is time.

**1. Why are you not first on the leaderboard?**
On every quote 5U accepted we score as much as the leaders: the same cost points per quote and the price within 5 %.
Our gap comes from early rounds lost to new tricks (dangerous goods in attachments, the portal outage), and each one
became a fix with a test, so later in the night almost every round was accepted.

**2. What happens when the AI gets it wrong?**
The AI never sets a price: it only turns the mail into fields and writes the words, and code checks those fields
against rules (weights, airports, postcodes) before anything is sent. If a check fails, the request goes to a person
in the control room instead of a guess, because only the first answer in a thread counts.

**3. How much does one quote cost?**
About $0.0009 of AI per quote, one small gateway call, because rules and code do everything that does not need
language. Carrier bids are plain emails, read by code with one tiny call each.

**4. How fast is it?**
In the runner's data the median time from request to quote was 62 seconds, all under the 2 minute limit. Most of
that time is waiting for carrier and trucker bids by email, which answer in about 38 seconds.

**5. How do you handle dangerous goods?**
We read every attachment (Excel, Word, PDF, and photos with on-device text recognition) and look for UN numbers,
classes and dangerous commodities like aerosols or lithium batteries, even when the mail says "non-dangerous". The
quote then asks for the Shipper's Declaration and safety data sheet, and the booking waits for them.

**6. What if 5U, or a real customer, sends something new tomorrow?**
Every change tonight followed the same loop: an alarm posts the full log into our team chat, we replay the real
requests against the new code, and a change goes live only after all tests and a fake quote pass. The old code keeps
running if a check fails, so a bad fix cannot take the system down.

**7. Is this safe against a malicious email, for example prompt injection?**
We tested 16 attack mails with a model that obeys the attacker: prices, links, payment details and promises are all
replaced by our fixed template, so the price always stays ours. Phishing and vendor pitches are routed as spam and
never answered.

**8. Why would a forwarder trust it with real customers?**
Because people stay in charge of the judgement calls: unclear requests, unusual cargo and price changes land in the
control room with the whole history and a "send as human" button. The system takes the repetitive 80 % so the team
spends its time on the cases that need experience.

**9. How did four people build this in one night?**
One repository, one folder per owner, and four AI coding agents that coordinate in a GitHub issue with CLAIM, DONE
and NEED messages. Only one machine is allowed to send mail; every other one runs in dry-run mode.

**10. What would you build next?**
Learning from every won and lost quote to tune the price pick per lane, and connecting to a real forwarder's mailbox
and rate systems. The structure is ready: every decision is already logged with its reason.
