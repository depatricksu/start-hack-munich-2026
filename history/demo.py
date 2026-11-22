"""Demo: a forwarder switches to our agent and brings 2025's paperwork along. Owner: Patrick.

    python3 -m history.demo                 # build the old archive in examples/legacy-demo/, import it, tell the story
    python3 -m history.demo --keep-db       # also keep the demo database (examples/legacy-demo/demo.db) to search it

The archive is what a small forwarder really has (all made up, nothing is sent anywhere):
  mailbox/   an Outlook export: requests, our quotes, bookings, airline confirmations, with PDF attachments and a
             PHOTO of a packing list; one mail exported twice
  scans/     paper from the filing cabinet, scanned: a forwarding order taken by phone, an airline invoice (an
             image-only PDF), a delivery receipt, a phone note nobody filed
  registers/ the Excel list the team kept (German headers, German numbers), with a row typed twice
The agent reads it all (text layer where there is one, macOS Vision OCR where there is not), sorts it into cases,
merges what belongs together, flags what it cannot place, and answers a customer about a 2025 shipment.
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "examples", "legacy-demo")
KEEP = "--keep-db" in sys.argv
os.environ["DB_PATH"] = os.path.join(OUT, "demo.db") if KEEP else os.path.join(tempfile.mkdtemp(), "demo.db")
os.environ.setdefault("DRY_RUN", "1")
os.environ.setdefault("FIVEU_API_KEY", "")
if KEEP and os.path.exists(os.environ["DB_PATH"]):
    os.remove(os.environ["DB_PATH"])

import json, shutil, subprocess, time  # noqa: E402
from email.mime.application import MIMEApplication  # noqa: E402
from email.mime.image import MIMEImage  # noqa: E402
from email.mime.multipart import MIMEMultipart  # noqa: E402
from email.mime.text import MIMEText  # noqa: E402
from email.utils import format_datetime  # noqa: E402
import datetime as dt  # noqa: E402

US = "Lena Hofmann <export@hofmann-spedition.de>"


def _pdf(lines):
    from core import offer_file
    return offer_file.pdf(lines)


def scan(lines, path, rotate=1.2, pdf=False):
    """Typed paper -> a scan: printed (PDF), photographed (PNG), a little crooked, JPEG-compressed like a copier."""
    tmp = tempfile.mkdtemp()
    src, png, rot = os.path.join(tmp, "p.pdf"), os.path.join(tmp, "p.png"), os.path.join(tmp, "r.png")
    with open(src, "wb") as f:
        f.write(_pdf(lines))
    run = lambda *a: subprocess.run(["sips", *a], capture_output=True, check=True)
    run("-s", "format", "png", "-Z", "1400", src, "--out", png)
    run("-r", str(rotate % 360), png, "--out", rot)          # sips only takes 0-360
    if pdf:                                                       # an image-only PDF: no text layer at all
        jpg = os.path.join(tmp, "s.jpg")
        run("-s", "format", "jpeg", "-s", "formatOptions", "45", rot, "--out", jpg)
        run("-s", "format", "pdf", jpg, "--out", path)
    else:
        run("-s", "format", "jpeg", "-s", "formatOptions", "45", rot, "--out", path)
    shutil.rmtree(tmp)
    return path


def mail(frm, to, subject, body, when, mid, reply_to=None, files=(), html=False):
    m = MIMEMultipart()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Date"] = format_datetime(when)
    m["Message-ID"] = "<%s>" % mid
    if reply_to:
        m["In-Reply-To"] = m["References"] = "<%s>" % reply_to
    m.attach(MIMEText(body, "html" if html else "plain", "utf-8"))
    for name, data in files:
        part = MIMEImage(data, _subtype="jpeg") if name.endswith(".jpg") else MIMEApplication(data, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=name)
        m.attach(part)
    return m


def build():
    """Write the old archive to examples/legacy-demo/ (overwrites the generated files)."""
    for sub in ("mailbox", "scans", "registers"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    tz = dt.timezone(dt.timedelta(hours=1))
    d = lambda *a: dt.datetime(*a, tzinfo=tz)
    tmp = tempfile.mkdtemp()
    packing_scan = open(scan(["PACKING LIST", "", "Shipper: Lindqvist Medtech AB, Frankfurt lab", "Route: FRA - ORD (Chicago)",
                              "4 pallets, medical devices, not dangerous", "Gross weight: 610 kg   Volume: 3.1 cbm",
                              "Pallet 1-4: 120 x 80 x 80 cm"], os.path.join(tmp, "pl.jpg"), rotate=-1.6), "rb").read()
    msgs = [
        # 1 Sonnberg: request, quote, yes, airline confirmation (PDF), customer's papers (2 PDFs)
        mail("Anna Sonnberg <anna.sonnberg@sonnberg-kaffee.de>", US, "Air freight quote to PVG",
             "Hello,\n\ncheapest air freight MUC to PVG please, 5 pieces, 540 kg, 1.33 cbm, machine parts, ready 26 March.\n\n"
             "Anna Sonnberg", d(2025, 3, 3, 9, 2), "a1@sonnberg"),
        mail(US, "anna.sonnberg@sonnberg-kaffee.de", "Re: Air freight quote to PVG",
             "Hi Anna,\n\nMUC to PVG with Meridian Freightways: 1,921.60 EUR all-in, about 3 days.\n\nLena", d(2025, 3, 3, 10, 15),
             "a2@hofmann", "a1@sonnberg"),
        mail("Anna Sonnberg <anna.sonnberg@sonnberg-kaffee.de>", US, "Re: Air freight quote to PVG", "Great, please book it.\n\nAnna",
             d(2025, 3, 3, 11, 0), "a3@sonnberg", "a2@hofmann"),
        mail("Meridian Freightways <meridian-freightways@hackloop.mail>", "export@hofmann-spedition.de",
             "Booking BK-AW8CXJCM confirmed", "Dear partner,\n\nplease find the booking confirmation attached.",
             d(2025, 3, 3, 11, 40), "a4@meridian",
             files=[("BK-AW8CXJCM_confirmation.pdf", _pdf(["MERIDIAN FREIGHTWAYS - BOOKING CONFIRMATION", "",
                                                          "Booking BK-AW8CXJCM is confirmed.", "Route: MUC - PVG, flight MD 731",
                                                          "5 pieces, 540 kg gross, 1.33 cbm", "Rate: 1,728.00 EUR all-in"]))]),
        mail("Anna Sonnberg <anna.sonnberg@sonnberg-kaffee.de>", US, "Re: Air freight quote to PVG",
             "Hi Lena, the commercial invoice and the packing list for the shipment are attached.\n\nAnna",
             d(2025, 3, 5, 8, 30), "a5@sonnberg", "a3@sonnberg",
             files=[("Commercial_Invoice_2025-118.pdf", _pdf(["COMMERCIAL INVOICE 2025-118", "Sonnberg Kaffeeroesterei GmbH",
                                                             "Goods: machine parts (roaster spare parts)", "Value: 14,250.00 EUR",
                                                             "Shipment: MUC - PVG, booking BK-AW8CXJCM"])),
                    ("Packing_List_2025-118.pdf", _pdf(["PACKING LIST 2025-118", "5 pieces, 540 kg gross, 1.33 cbm",
                                                       "booking BK-AW8CXJCM"]))]),
        # 2 Weber: the request is only in the attached PDF; our quote is HTML; he declines
        mail("Thomas Weber <t.weber@weber-bau.de>", US, "Anfrage Luftfracht",
             "Guten Morgen,\n\nanbei unsere Anfrage, alle Details stehen im PDF.\n\nThomas Weber", d(2025, 3, 11, 8, 15), "b1@weber",
             files=[("Anfrage_JFK.pdf", _pdf(["ANFRAGE LUFTFRACHT", "Weber Bau GmbH, Einkauf",
                                             "Von FRA nach JFK (New York)", "3 Kisten Baumaschinenteile", "Gewicht: 820 kg",
                                             "Volumen: 3,9 cbm", "Anlieferung durch uns am Flughafen"]))]),
        mail(US, "t.weber@weber-bau.de", "AW: Anfrage Luftfracht",
             "<p>Hallo Herr Weber,</p><p>FRA nach JFK mit Wayzata Air Cargo: <b>2.156,60 EUR</b> all-in.</p>",
             d(2025, 3, 11, 9, 0), "b2@hofmann", html=True),
        mail("Thomas Weber <t.weber@weber-bau.de>", US, "AW: AW: Anfrage Luftfracht",
             "Danke, wir haben uns anders entschieden und buchen nicht.\n\nGruß Weber", d(2025, 3, 12, 14, 0), "b3@weber"),
        # 3 Lindqvist: the facts are only in a PHOTO of the packing list
        mail("Sara Lindqvist <sara@lindqvist-medtech.se>", US, "Chicago shipment",
             "Hi Lena,\n\ncheapest to Chicago please, all details are on the scanned packing list attached. We deliver to FRA.\n\nSara",
             d(2025, 4, 2, 10, 0), "c1@lindqvist", files=[("packing_list_scan.jpg", packing_scan)]),
        mail(US, "sara@lindqvist-medtech.se", "Re: Chicago shipment",
             "Hi Sara,\n\nFRA to ORD with Fjordline Air Cargo: 1,683.30 EUR all-in, about 4 days.\n\nLena", d(2025, 4, 2, 11, 0),
             "c2@hofmann", "c1@lindqvist"),
        mail("Sara Lindqvist <sara@lindqvist-medtech.se>", US, "Re: Chicago shipment", "Perfect, go ahead.\n\nSara",
             d(2025, 4, 2, 12, 0), "c3@lindqvist", "c2@hofmann"),
        mail("Fjordline Air Cargo <fjordline-air-cargo@hackloop.mail>", "export@hofmann-spedition.de",
             "Booking BK-LQ7731AA confirmed", "Booking BK-LQ7731AA is confirmed, FRA - ORD, 610 kg.", d(2025, 4, 2, 12, 40), "c4@fjordline"),
        # 4 Brandt sends the same request twice (no answer in between); 5 Kessler never got an answer
        mail("Jonas Brandt <jonas@brandt-optik.de>", US, "Quote ORD", "Hello, cheapest FRA to ORD, 300 kg, 1.5 cbm. Jonas Brandt",
             d(2025, 4, 7, 10, 0), "d1@brandt"),
        mail("Jonas Brandt <jonas@brandt-optik.de>", US, "Quote ORD - urgent",
             "Hello again, did you get my request? Cheapest FRA to ORD, 300 kg, 1.5 cbm. Jonas Brandt", d(2025, 4, 8, 9, 0), "d2@brandt"),
        mail("Kessler Feinmechanik <info@kessler-feinmechanik.de>", US, "Air freight HAM to BOG",
             "Dear Sir or Madam, please quote HAM to BOG, 630 kg, 3.96 cbm.", d(2025, 5, 15, 16, 0), "e1@kessler"),
    ]
    with open(os.path.join(OUT, "mailbox", "outlook-export-2025.mbox"), "wb") as f:
        for m in msgs:
            f.write(b"From - Mon Jan  1 00:00:00 2025\n" + m.as_bytes().replace(b"\nFrom ", b"\n>From ") + b"\n\n")
    with open(os.path.join(OUT, "mailbox", "anna-request-saved-again.eml"), "wb") as f:   # a colleague saved it again
        f.write(msgs[0].as_bytes())
    scan(["SPEDITIONSAUFTRAG / FORWARDING ORDER    Nr. 2025-0417", "", "Versender: Alpen Pharma GmbH, Einkauf, 70173 Stuttgart",
          "Kontakt: einkauf@alpen-pharma.de", "", "Von: STR   Nach: SIN   Luftfracht", "Colli: 2   Gewicht: 95 kg   Volumen: 0,42 cbm",
          "Ware: Laborgeraete, kein Gefahrgut", "Abholung: 20.01.2025", "", "Airline: Solace Air Cargo    Buchung: BK-OLD00042",
          "Preis all-in: 1.240,00 EUR", "", "Unterschrift: ______________   Datum: 17.01.2025"],
         os.path.join(OUT, "scans", "scan_0001.jpg"))
    scan(["SOLACE AIR CARGO", "RECHNUNG / INVOICE  SA-25-00981", "", "An: Hofmann Spedition, Export", "Buchung: BK-OLD00042",
          "STR - SIN, 2 Colli, 95 kg", "Luftfracht inkl. Zuschlaege: 1.012,00 EUR", "Zahlbar bis 28.02.2025"],
         os.path.join(OUT, "scans", "scan_0002.pdf"), rotate=-0.8, pdf=True)
    scan(["PROOF OF DELIVERY", "", "Booking BK-LQ7731AA   AWB 176-44219874", "Consignee: Lindqvist Medtech Inc., Chicago IL",
          "4 pallets received in good order", "Date: 07.04.2025   Signature: J. Miller"],
         os.path.join(OUT, "scans", "scan_0003.jpg"), rotate=2.0)
    scan(["Telefonnotiz 14.05.", "Herr Maier ruft zurueck wegen Luftfracht nach Dubai", "Gewicht folgt, bitte Angebot vorbereiten"],
         os.path.join(OUT, "scans", "scan_0004.jpg"), rotate=-2.2)
    with open(os.path.join(OUT, "registers", "sendungen_2025.csv"), "w", encoding="utf-8") as f:
        f.write("Datum;Kunde;Von;Nach;Gewicht;Preis;Währung;Airline;Buchungsnummer;Status\n"
                "03.03.2025;anna.sonnberg@sonnberg-kaffee.de;MUC;PVG;540;1.921,60;EUR;Meridian Freightways;BK-AW8CXJCM;geflogen\n"
                "20.01.2025;einkauf@alpen-pharma.de;STR;SIN;95;1.240,00;EUR;Solace Air Cargo;BK-OLD00042;geflogen\n"
                "20.01.2025;einkauf@alpen-pharma.de;STR;SIN;95;1.240,00;EUR;Solace Air Cargo;BK-OLD00042;geflogen\n"
                "10.02.2025;sales@nordlicht-audio.de;CGN;LIM;1745;4.760,00;EUR;Xenon Cargo Airlines;BK-NA552019;geflogen\n")
    shutil.rmtree(tmp)


def say(title):
    print("\n" + "=" * 100 + "\n" + title + "\n" + "=" * 100)


def main():
    build()
    t0 = time.time()                                              # the import alone, not the making of the demo files
    from history import importer, find
    from core import db, mailbox
    say("1. THE OLD ARCHIVE (examples/legacy-demo/)")
    for root, _, files in sorted(os.walk(OUT)):
        for f in sorted(files):
            if f != "demo.db" and not f.startswith("."):
                p = os.path.join(root, f)
                print("  %-12s %-36s %8s bytes" % (os.path.relpath(root, OUT), f, os.path.getsize(p)))

    say("2. IMPORT: python3 -m history.importer examples/legacy-demo --ours export@hofmann-spedition.de")
    r = importer.run([OUT], ours=["export@hofmann-spedition.de"], quiet=True)
    for k in ("mails_read", "duplicate_mails", "conversations", "attachments_read", "documents_read", "read_by_ocr",
              "documents_linked", "cases_from_paper", "register_rows", "register_duplicate_rows", "rows_merged_into_mail_cases",
              "requests_sent_twice", "cases"):
        print("  %-30s %s" % (k.replace("_", " "), r[k]))
    print("  %-30s %s" % ("outcome", ", ".join("%s %d" % (s, n) for s, n in r["by_status"].items() if n)))
    print("  %-30s %.1f s (OCR: the first page loads the Vision model, then about 1 s a page)" % ("time", time.time() - t0))

    c = importer.con()
    say("3. READ FROM PAPER AND FILES (the text the agent got, first lines)")
    for d in c.execute("SELECT * FROM archive_docs ORDER BY how DESC, filename"):
        lines = [l.strip() for l in (d["text"] or "").splitlines() if l.strip()]
        print("  %-30s %-5s -> %-20s | %s" % (d["filename"][:30], d["how"] or "-", d["kind"], " / ".join(lines[:3])[:95]))

    say("4. THE CASES (one line per shipment, old data sorted the agent's way)")
    for k in c.execute("SELECT * FROM archive_cases ORDER BY first_at"):
        n_docs = c.execute("SELECT count(*) FROM archive_docs WHERE case_key=?", (k["key"],)).fetchone()[0]
        when = dt.datetime.fromtimestamp(k["first_at"]).strftime("%Y-%m-%d") if k["first_at"] else "?"
        print("  %s %-10s %-34s %s-%s %6s kg %10s %-22s %-12s mails %-2s docs %s%s" % (
            when, k["status"], (k["customer"] or k["company"] or "?")[:34], k["origin"] or "?", k["destination"] or "?",
            "%g" % k["weight_kg"] if k["weight_kg"] else "?", k["price"] or "-", (k["airline"] or "-")[:22],
            k["booking_reference"] or "-", k["n_mails"], n_docs,
            "   <- request sent twice, linked to the first" if k["duplicate_of"] else ""))
    loose = c.execute("SELECT filename, kind, text FROM archive_docs WHERE case_key IS NULL AND mail_mid IS NULL").fetchall()
    for d in loose:
        print("  NOT PLACED: %s (%s): '%s' -> for a person to file" % (d["filename"], d["kind"],
                                                                   " ".join((d["text"] or "").split())[:80]))

    say("5. ONE CASE, EVERYTHING TOGETHER: python3 -m history.find --case <Alpen Pharma>")
    key = c.execute("SELECT key FROM archive_cases WHERE booking_reference='BK-OLD00042'").fetchone()[0]
    find.show_case(key)

    say("6. FINDING OLD CASES")
    for q in (["pharma", "SIN"], ["BK-LQ7731AA"], ["laborgeraete"], ["610kg"], ["weber", "2025-03"], ["lost"]):
        hits = [h for h in find.search(q) if h["where"] == "archive"]
        print("  find %-22s -> %s" % (" ".join(q), "; ".join("%s %s-%s %s" % ((h["customer"] or h["company"] or "?").split("@")[0],
                                                                         h["origin"], h["destination"], h["status"]) for h in hits) or "-"))

    say("7. A CUSTOMER ASKS ABOUT A 2025 SHIPMENT: the agent answers from the archive")
    m = mailbox.normalize({"id": 9990001, "from": "tracking@hackloop.mail", "subject": "Status of booking BK-LQ7731AA",
                           "body": "Hello, what is the status of booking BK-LQ7731AA from April?"})
    db.save_mail(m)
    from booking import tracking
    tracking.handle(m)
    out = db.con().execute("SELECT data FROM events WHERE thread_id=9990001 AND kind LIKE 'mail_out%' ORDER BY id DESC").fetchone()
    print("  question: " + m["body"])
    print("  answer (nothing sent, demo):\n    " + json.loads(out[0])["body"].replace("\n", "\n    "))
    if KEEP:
        print("\nDemo database kept: %s  (DB_PATH=%s python3 -m history.find ...)" % (os.environ["DB_PATH"], os.environ["DB_PATH"]))


if __name__ == "__main__":
    main()
