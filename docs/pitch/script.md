# Pitch: "Who answers at 2 a.m.?" (3 minutes)

Team Google · START Hack Munich 2026 · 5U AI challenge. About 420 words, about 2:50 read aloud at a calm pace.
Numbers marked **[board]** are refreshed from `https://api.start-hack.5u.ai/v1/board` right before the pitch
(command at the bottom). Sources for every number are in the table at the end.

## Slides (5)

| # | Slide | On screen |
|---|---|---|
| 1 | Who answers at 2 a.m.? | One customer mail, a clock at 02:00, our reply 62 s later |
| 2 | How one request flows | The flow line from `README.md`: mail in, router, one AI call, gate, price, pick, reply, book, track |
| 3 | 5U changed the rules every hour | Three rows from `docs/5u-changes-timeline.md`: trick, how we saw it, fix, minutes to fix |
| 4 | A real mail | One real quote from `docs/sample-quote-mails.md`, the customer's own question highlighted in the answer |
| 5 | Tonight in numbers | Accepted quotes, bookings, human bonuses, cost per quote, seconds to quote |

## Spoken text

**[Slide 1, 0:00]**
It is two in the morning. A textile company in Hamburg needs a price for air freight to Delhi, with a truck from
their site. At a forwarder, that mail waits until a person comes in at eight. By then the customer has asked three
others.

Ours answers in about a minute. It reads the mail, prices it from the rate sheets, the rate portal and live bids from
carriers and truckers, and replies in the customer's thread, in the customer's language, with one all-in price.
When the customer says yes, it books. When they ask where the goods are, it answers.

**[Slide 2, 0:40]**
Our rule is simple: code does the math, AI reads the mail, people make the calls.
The AI makes exactly one small call per quote: it turns the mail into fields and writes the words. It never makes
up a price. Every number comes from code we can test. And when something is unclear, the system does not guess. It
hands the case to a person in our control room, with the full history, because a wrong first answer cannot be
taken back.

**[Slide 3, 1:15]**
Then 5U changed the game every hour, without warning. We treated every lost round as data.
At five, dangerous goods were hidden in the attachment while the mail said "non-dangerous". We now read every
attachment and ask for the safety documents.
At twenty to seven, the rate portal went down. We fell back to bids by email within minutes.
Later, a customer wrote "do not offer this airline". No team passed that round. Now the excluded airline is never
even asked.
Four people and four AI agents built this in one night, in one shared repository, and every fix went live only
after all tests and a fake quote passed.

**[Slide 4, 2:05]**
And it does not read like a machine. This is a real reply. It greets the customer by the name she signed with,
answers the question she asked about arrival, and closes the way a person would.

**[Slide 5, 2:25]**
Tonight: **[board]** accepted quotes, **[board]** bookings, a quote in about one minute, and about one tenth of a
cent of AI cost per quote.
So who answers at two in the morning? Ours does. And at eight, the people only see the cases that really need
them. Thank you.

## Sources for every number

| Number in the text | Value | Source |
|---|---|---|
| "about a minute", "62 s" | median 62 s, range 9 to 76 s, 15 quotes, all under 120 s | runner DB snapshot to 17:47: `quote_sent` time minus first `mail_in` per thread |
| "one tenth of a cent of AI cost per quote" | $0.0009 average over 17 requests | `DB_PATH=examples/real/snapshot.db python3 -m core.stats` |
| carrier bids answer in | median 38 s, 86 of 86 asked answered | same `core.stats` run |
| accepted quotes, bookings, human bonuses | at 21:35: 43 accepted of 55 rounds, 41 bookings, 5 human bonuses, 5th of 13 | public board `ranking` |
| the three 5U changes | 17:00 DG in attachments, 18:40 portal 503, 20:09 excluded airline | `docs/5u-changes-timeline.md` (issue #45), PRs #25, #42 |
| four people, four agents, one repo | 130 commits, 38 merged PRs, 383 tests | `git log --oneline origin/main | wc -l`, `gh pr list --state merged`, `grep -rc "def test" tests` |

Refresh the board numbers right before the pitch:

```bash
curl -s https://api.start-hack.5u.ai/v1/board | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['rank'], r['team'], r['accepted'], r['answered'], r['bookings'], r['human']) for r in d['ranking'] if r['team']=='Google']"
```

Timing check: read it aloud once with a stopwatch. If it runs over 3:00, cut the second sentence of slide 2 and
the last sentence of slide 3.
