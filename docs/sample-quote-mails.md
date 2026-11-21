# Sample quote mails (human-email upgrade)

Real gateway output from the forwarder's reply engine. One gateway call per quote. On top of the
price, the mail answers the customer's own line, opens and closes a little differently each time
(4x5 shapes per thread), and speaks native DE/IT/FR/ES. This is the play for the jury's +10
"most human mail" bonus. Toggle off with `HUMAN_VOICE=0`. Names are the hackathon's test personas.

---

### 1. pickup -> PEK, cheapest, door pickup, EN

```
Hi Petra,

My week is going fine, thanks for asking, and I hope yours is as well. I've checked the route to
Beijing for your shipment. The cheapest option is with Gannet Airways at 3325.60 EUR all-in, with a
transit time of around 5 days. I've noted your pickup request from your site on the 27th. Because of
the volume (8.03 cbm), the chargeable weight here is 1,341 kg.

A quick yes, and I'll get it booked.

Have a lovely day too!
```
Human touch: answers her "how's your week?", notes the pickup date, explains the chargeable-weight
bump in plain words, sends her parting wish back.

---

### 2. STR -> SIN, cheapest, self-delivery, DE

```
Guten Tag Katharina,

Ihre vier Kisten Messgeräte werden von Stuttgart nach Singapur transportiert, und ich kann Ihnen das
günstigste Angebot mit Meridian Freightways für 1284.60 EUR all-in anbieten, die Laufzeit beträgt etwa
4 Tage. Ich habe vermerkt, dass Sie die Ware am 2. Dezember selbst am Flughafen anliefern.

Eine kurze Bestätigung reicht aus, und ich buche es.

Beste Grüße nach Esslingen
```
Human touch: names the cargo, repeats back that she delivers to the airport herself, signs off to her
town (Esslingen).

---

### 3. MUC -> GRU, cheapest, self-delivery, IT

```
Buongiorno Giulia,

La quotazione più economica per la spedizione dei vostri 5 colli di campioni di tessuto da Monaco a San
Paolo è con Juniper Cargo Lines: 1136.20 EUR tutto incluso, con una durata di circa 5 giorni. Ho preso
nota che la merce sarà pronta dal 30 novembre e che la porterete voi in aeroporto.

Posso procedere con la prenotazione?

Buona giornata anche a voi!
```
Human touch: native Italian, the 5 colli of fabric samples named, ready date and self-delivery
acknowledged, warm close.

---

### 4. pickup -> SGN, cheapest, weight-break saving, EN

```
Hi Sara,

I've looked at your lane for shipping to SGN. The cheapest option is with Lumen Air Cargo, priced at
2358.88 EUR all-in, transit time is about 4 days. I've noted that the goods are ready for pickup on the
29th and that our truck will collect from your warehouse. I've billed it at 1,000 kg rather than 874 kg,
since the next weight bracket is cheaper per kilo and that brings your total down.

A quick yes from you and I'll book it.
```
Human touch: explains the higher weight break as a saving, not jargon: billed at 1,000 kg because it is
cheaper than her actual 874 kg.

---

### 5. pickup -> air export, fastest, urgent, EN

```
Hi Klaus,

No worries about the rush. I can get your 9 crates of replacement gearboxes shipped fast with Fjordline
Air Cargo at 6412.90 EUR all-in, about 2 days.

I've noted that the goods are ready today and our truck will collect them at your plant in Nuremberg.

Does that work for you? Just reply to confirm and I'll book it right away.
```
Human touch: matches his urgency, names the 9 crates of gearboxes and his plant in Nuremberg, short and
fast.

---

## Most human quote mails (real, from the runner)

Picked from the runner snapshot (`python3 -m core.share --get`, newest mail Sat 21 Nov 21:23 CET, 53 quote mails).
The customer accepted all 5 and all 5 bookings are **confirmed**. The price is the quoted option stored in the DB.
The scorer's round number is not in the snapshot (it has no `board_results` table yet), so each mail is labeled
with its request id (`thread_id`). Times are CET, when the quote went out. The data so far has only EN and DE quotes.

### A. Request 12870, 20:47:45, DUS -> BOM, fastest, EN (Tobias, Auer Maschinenbau)

```
Hi Tobias,

Your fastest option is with Fjordline Air Cargo at 5655.55 EUR all-in, and the transit is about 2 days.
I've noted that you'll bring the spare parts to Düsseldorf Airport on the 23rd.

Should I book it?

With the goods ready on Mon 23 Nov, it should depart soon after and arrive in Mumbai around Wed 25 Nov.

Best regards to Regensburg
Lena Hofmann
Air Export
```
Why human: he asked for the earliest arrival and gets a real date. His "Best greetings from Regensburg" comes
back as "Best regards to Regensburg". Quoted in 83 s, after a round of carrier bids.

### B. Request 11075, 20:17:20, HAM -> DEL, fastest, EN (Petra, Hofmann Textilwerk)

```
Hi Petra,

All good here, thanks, I hope your week is going well too. Your electronic control unit can fly from
Hamburg to Delhi with Ibisair Cargo, the fastest option I have for you is 4981.34 EUR all-in, with a
transit time of around 3 days. I've noted that you'll bring the shipment to the airport yourselves and
it'll be ready on the 26th.

Just say the word and I'll get it booked.

Have a lovely day too!

With the goods ready on Thu 26 Nov, it should depart soon after and arrive in Delhi around Sun 29 Nov.

Best regards
Lena Hofmann
Air Export
```
Why human: it answers "Hope your week's going well!", gives the arrival she asked for and returns her "have a
lovely day".

### C. Request 9869, 19:46:50, pickup Regensburg -> PVG, fastest, EN (Anna, Sonnberg Kaffeeroesterei)

```
Hi Anna,

I've looked at your lane to PVG. The fastest option available is with Meridian Freightways at 1921.60
EUR all-in, with a transit time of about 3 days. Our truck will collect the machine parts on the 26th
from your site.

Just say the word and I'll get it booked.

Always good to get a request from Regensburg.

With the goods ready on Thu 26 Nov, it should depart soon after and arrive in Shanghai around Sun 29 Nov.

Best regards
Lena Hofmann
Air Export
```
Why human: she asked for "the earliest pickup and arrival times" and gets both (truck on the 26th, arrival
Sun 29 Nov), plus a personal line about her town.

### D. Request 9107, 19:34:21, pickup Kiel -> SGN, cheapest, EN (Klaus, Weidner Spielwaren)

```
Hi Klaus,

All good here, thanks, I hope your week is going well too. Your shipment of 4 electronic control units
is heading to SGN. The cheapest option is with Juniper Cargo Lines for 2733.72 EUR all-in, and this
includes our truck for pickup from your site. I've noted it'll be ready on the 23rd.

Just reply with a yes and I'll get it booked.

Cheers
Lena Hofmann
Air Export
```
Why human: short and warm. It answers his small talk, matches his "Cheers", names the cargo and confirms the
truck is included in the price.

### E. Request 1463, 16:31:32, DUS -> KUL, cheapest, DE (Jonas, Kessler Feinmechanik)

```
Guten Tag,

Für Ihren Versand von DUS nach KUL mit einem Gesamtgewicht von 1.549 kg und einer Volumen von 8.26 cbm
kann ich Ihnen einen Gesamtpreis von 3949.95 EUR anbieten. Die Lieferung erfolgt mit Fjordline Air
Cargo, der Transport dauert voraussichtlich 5 Tage.

Sie können einfach auf diese Nachricht antworten, um die Buchung vorzunehmen.

Freundliche Grüße
Lena Hofmann
Luftfracht Export
```
Why human: he signed "Mit freundlichen Gruessen", so the reply switches to formal German and uses the German
number style (1.549 kg). This is the weakest of the five: the greeting has no name, and "einer Volumen" should be
"einem Volumen". It is still the better of the only two German quotes in the data (the other one, 940, is signed
with the customer's own name).
