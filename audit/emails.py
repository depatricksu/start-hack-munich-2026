"""Does our quote mail read like a person wrote it? Owner: Riky.

The board pays +10 per round for the most human accepted mail (field `human`): START Milan 4, AEIOU 4, us 0 at 17:55.
This lints every reply we actually sent (runner snapshot) for the things a reader spots as "robot":

    python3 -m audit.emails                               # examples/real/snapshot.db (python3 -m core.share --get)
    DB_PATH=other.db python3 -m audit.emails
    from audit.emails import lint; lint(reply, customer_mail)   # [(code, detail)] for one mail

Read-only. A finding is a hint for the owner of the reply text (llm/), not an automatic change.
"""
import os, re, sqlite3, sys

DB = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "examples", "real", "snapshot.db")


def _first_name(customer_mail):
    """The name the customer signed with (last short line that looks like a person), or None."""
    lines = [l.strip() for l in (customer_mail or "").strip().splitlines() if l.strip()]
    for l in lines[-4:]:                                 # top-down: "Sara" comes before "Lindqvist Medtech"
        if re.fullmatch(r"[A-ZÄÖÜ][a-zäöüß]+(?: [A-ZÄÖÜ][a-zäöüß]+)?", l) and l.lower() not in (
                "thanks", "cheers", "regards", "best", "best regards", "kind regards", "thank you", "many thanks"):
            return l.split()[0]
    return None


def lint(reply, customer_mail=""):
    out = []
    text = reply or ""
    first = text.strip().splitlines()[0] if text.strip() else ""
    m = re.match(r"(?:hi|hello|dear|hallo|guten tag|ciao)\s+([^,\n]+),", first, re.I)
    name = _first_name(customer_mail)
    if m and name and m.group(1).strip().split()[0] != name:
        out.append(("greeting_name", f"greets '{m.group(1).strip()}', customer signed '{name}'"))
    if re.search(r"\b(kg|cbm|EUR|USD)\s+\1\b", text):
        out.append(("doubled_unit", re.search(r"\b(kg|cbm|EUR|USD)\s+\1\b", text).group(0)))
    if re.search(r"\bimport\b", text, re.I) and not re.search(r"\bimport\b", customer_mail or "", re.I):
        out.append(("says_import", "we only do air EXPORT; the customer did not say import"))
    for amount in re.findall(r"\b(\d{4,}\.\d{2})\b", text):
        out.append(("raw_amount", f"{amount} has no thousands separator (EUR {float(amount):,.2f})"))
        break
    if re.search(r"\{[A-Z_]+\}", text):
        out.append(("placeholder", "an unfilled {PLACEHOLDER} went out"))
    asks = re.findall(r"[^.?!\n]*\b(?:confirm|let me know|could you also|please (?:also )?(?:tell|advise|state|include))\b[^.?!\n]*[.?]",
                      customer_mail or "", re.I)
    for ask in asks:
        key = [w for w in re.findall(r"[a-z]{5,}", ask.lower()) if w not in ("please", "confirm", "could", "would", "include", "price")]
        if key and not any(k in text.lower() for k in key[:3]):
            out.append(("unanswered_ask", ask.strip()[:120]))
    if re.match(r"(?:hi|hello)[^,\n]*,\s*\n\s*\n\s*for your", text, re.I):
        out.append(("template_opening", "starts with the usual 'for your shipment…'"))
    if len(text.split()) > 110:
        out.append(("long", f"{len(text.split())} words"))
    return out


def run(path=DB):
    if not os.path.exists(path):
        print("no snapshot: python3 -m core.share --get")
        return 1
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT s.thread_id, s.reply, m.body FROM sessions s JOIN mails m ON m.id = s.thread_id "
                     "WHERE s.reply IS NOT NULL ORDER BY s.thread_id").fetchall()
    counts = {}
    for r in rows:
        found = lint(r["reply"], r["body"])
        for code, detail in found:
            counts[code] = counts.get(code, 0) + 1
            print(f"{r['thread_id']:>6}  {code:<16} {detail}")
    print(f"\n{len(rows)} replies checked. " + (", ".join(f"{k} x{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
                                              or "no findings"))
    return 0


if __name__ == "__main__":
    sys.exit(run())
