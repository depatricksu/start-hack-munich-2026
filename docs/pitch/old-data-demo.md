# Demo: switching to our agent takes one command, old paperwork included

*Pitch section (Patrick). Run it live: `python3 -m history.demo` (about 15 s on a Mac, nothing is sent anywhere).*

## The problem in one sentence

A forwarder will not switch software if 2025 stays behind in Outlook, a filing cabinet and an Excel list: when a
customer calls about "our shipment from March", someone has to find it.

## What the demo shows

The folder `examples/legacy-demo/` is what a small forwarder really has (made up for the demo):

| Source | What is in it |
|---|---|
| `mailbox/outlook-export-2025.mbox` | 15 mails: requests, our quotes, bookings, airline confirmations; PDFs attached; one request exists **only as a PDF**, another **only as a photo of a packing list** |
| `mailbox/anna-request-saved-again.eml` | the same mail saved a second time by a colleague |
| `scans/scan_0001.jpg` | a **paper forwarding order** taken by phone, scanned crooked |
| `scans/scan_0002.pdf` | an **airline invoice, image-only PDF** (no text layer at all) |
| `scans/scan_0003.jpg` | a **proof of delivery** |
| `scans/scan_0004.jpg` | a phone note nobody filed |
| `registers/sendungen_2025.csv` | the team's Excel list, German headers and numbers, one row typed twice |

One command, and the agent:
1. reads every mail, PDF and scan (text layer where there is one, **macOS Vision OCR** for paper, on the machine)
2. drops the duplicate mail and the duplicate Excel row
3. sorts 15 mails into 8 conversations and turns them into **8 shipments**: route, weight, price, airline, booking
   number, outcome (confirmed / lost / open), including the two requests whose facts were only in a PDF or a photo
4. puts things together that belong together: the paper order + the Excel row + the scanned airline invoice of
   Alpen Pharma become **one** case; the delivery receipt finds the Lindqvist shipment by its booking number
5. spots that Jonas Brandt sent the same request twice
6. says honestly what it could not place: "scan_0004.jpg, a phone note: for a person to file"
7. finds anything: `python3 -m history.find laborgeraete` (a word only on the scanned paper) -> the Alpen Pharma case
8. answers a customer about a 2025 shipment from the archive, in seconds

## On real data

Imported today's live database as if it were an old system: **179 of 179 requests** found, outcome right on all
confirmed, lost and cancelled ones, in 3.4 s.

## One line for the pitch

> "Switching to us takes one command. Your old mails, PDFs, even the scanned paper from the filing cabinet: the agent
> reads it, sorts it into shipments, and when a customer asks about March, it answers."
