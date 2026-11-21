# After the customer says yes: one request, every party informed

*Demo section for the pitch (Patrick). Everything in part 1 is real: request 9869 from the live game, 21 Nov,
from the runner's snapshot (`python3 -m core.share --get`). Part 2 shows the next step, built from the same record.*

## The forwarder's problem in one sentence

The customer's request already contains everything every other party needs: pickup address, ready date, pieces,
weight, volume, goods, the airline we booked. Today a forwarder still **retypes it into three more mails** after
the customer says yes. The data is there; nobody uses it.

## 1. What our agent already does, live (request 9869, Regensburg to Shanghai)

| Time | What happened | Who did it |
|---|---|---|
| +0 s | Customer: "fastest air freight to PVG, truck pickup from our site in 93721 Regensburg, 5 pieces, 540 kg, 1.33 cbm, ready 26 Nov" | customer |
| +8 s | Price requests to **4 truckers** and **5 airlines + the rate desk** by mail, plus the airline portal | agent |
| +41 to +73 s | 4 trucker prices and the airline answers come back and are read (1 price, 4 declined) | agent |
| +73 s | Quote: Meridian Freightways, **1,921.60 EUR all-in**, truck Neckarstrom Kurier, arrival around 29 Nov | agent |
| +97 s | Customer: "That works for us, please go ahead and book it." | customer |
| +97 s | **Booked** on the airline portal, customer told "booked, ref. BK-AW8CXJCM" | agent |
| +131 s | Airline confirms, customer told "confirmed, transit 3 days" | agent |

**2 minutes 11 seconds from request to confirmed booking, no human touched it.** On 21 Nov the agent got
53 bookings confirmed this way (snapshot 22:38).

## 2. What still lands on the forwarder's desk after the yes, and what the agent sends instead

The record of request 9869 already holds all of this:

```
customer   Anna Sonnberg, Sonnberg Kaffeeroesterei GmbH, 93721 Regensburg
goods      machine parts, 5 pieces, 540 kg, 1.33 cbm, ready 26 Nov
trucker    Neckarstrom Kurier (picked from 4 offers, 193.60 EUR)
airline    Meridian Freightways, MUC-PVG, booking BK-AW8CXJCM, our ref GOOGLE-9869, flight part 1,728.00 EUR
```

Three mails a forwarder writes by hand today. Our agent writes them from the record, the second the booking stands
(demo mock-ups, generated from the real data above):

**a) Pickup order to the trucker we picked** (today: never sent, the trucker only got our price request)

> To: Neckarstrom Kurier · Subject: Pickup order GOOGLE-9869, 93721 Regensburg to MUC, 26 Nov
>
> Hello, thank you for your offer of 193.60 EUR, we confirm the pickup:
> - Collect: Sonnberg Kaffeeroesterei GmbH, 93721 Regensburg, contact Anna Sonnberg, from 26 Nov
> - Goods: machine parts, 5 pieces, 540 kg, 1.33 cbm
> - Deliver to: Munich airport (MUC), Meridian Freightways cargo terminal, booking BK-AW8CXJCM
> - Please send us the delivery receipt once it is handed over. Reference GOOGLE-9869.

**b) Shipment details to the airline** (today: the portal booking carries only lane, weight and volume)

> To: Meridian Freightways · Subject: Booking BK-AW8CXJCM, shipment details (GOOGLE-9869)
>
> Shipper: Sonnberg Kaffeeroesterei GmbH, Regensburg, DE · Consignee city: Shanghai (PVG)
> Goods: machine parts, general cargo, not dangerous · 5 pieces, 540 kg gross, 1.33 cbm
> Delivery to your MUC terminal by truck (Neckarstrom Kurier) on 26 Nov. Please issue the air waybill to our reference.

**c) Document request to the customer** (today: the forwarder chases SLI, invoice and packing list by phone and mail)

> To: Anna Sonnberg · Subject: Re: Air freight quote request to PVG
>
> Hi Anna, to get the machine parts on the plane on time, could you send us the Shipper's Letter of Instruction,
> the commercial invoice and the packing list? Just attach them to a reply. If the goods are worth more than
> EUR 1,000 we also file the export declaration (ATLAS) for you with the invoice.

Then the agent keeps going on its own: it ticks off the documents as they arrive, sends one reminder if something
is missing, and passes airline updates ("departed", "delayed") straight on to the customer.

## 3. One line for the pitch

> "The customer writes **one** mail. Two minutes later the airline is booked, the truck is ordered, the airline has
> the shipment details and the customer knows which papers to send. The forwarder only steps in when something is red."

**Numbers to say:** 2:11 from request to confirmed booking · 53 bookings confirmed automatically on 21 Nov ·
1 customer mail feeds 4 parties (customer, trucker, airline, our own booking record) · no extra AI cost: these mails
are written from data we already have, not by the language model.

## 4. Found while preparing this demo (real, to fix)

When the agent books an airline **by mail** (airlines without portal booking), the booking mail names the
**customer's total incl. the truck** as the airline's rate: GOOGLE-11695 says "all-in 7384.60 EUR" to Juniper,
but the flight part is 6,957.54 EUR (the other 427.06 EUR is the truck); GOOGLE-12079 tells Borealis 1,731.20 EUR
instead of 1,528.39 EUR. The airline mail should carry the flight part only (`chosen["flight_total"]`),
in `booking/handlers.py` `request_by_mail`.
