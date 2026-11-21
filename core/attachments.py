"""Read EVERY attachment of a customer mail, once, at intake. Not only for dangerous goods.

5U hides facts in files (17:00: dangerous goods declared only in the packing list). So for each customer mail:
  read(mail)      downloads each file, turns it into text (dg.attachment_text: xlsx, docx, pdf, txt, csv), puts the
                  result on mail["attachments_text"] and logs one `attachments` event (name, type, size, readable, preview)
  for_llm(mail)   the mail with the attachment text appended to the body, for the gateway call (only if ATTACH_LLM=1)
A file we cannot read (a photo, a new format) is not an error here: core/alarm.py posts it to the agent chat as
`odd_attachment`, so a human or an agent looks at it in the round it first appears.
"""
import base64
from . import config, db

KNOWN = {"xlsx", "pdf", "docx", "txt", "csv"}      # types we can turn into text today
PER_FILE, TOTAL = 1500, 3000                       # characters of attachment text we give the LLM


def _is_text(text):
    """Real words, not the bytes of a photo decoded as letters."""
    t = text.strip()
    if len(t) < 3:
        return False
    good = sum(1 for ch in t if ch.isprintable() or ch in "\n\r\t")
    return t.count("\ufffd") <= len(t) * 0.02 and good >= len(t) * 0.9


def read(mail):
    """Never raises. Returns the list also stored on mail["attachments_text"]."""
    out = []
    try:
        from dg import attach as reader             # Riky's reader (stdlib, never raises)
        for att in mail.get("attachments") or []:
            name = att.get("filename") or att.get("name") or "attachment"
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            data = reader.download(mail["id"], att)
            if data and not att.get("content_base64"):          # keep the bytes: dg.check_mail will not download again
                att["content_base64"] = base64.b64encode(data).decode()
            text = reader.attachment_text(data, name) if data else ""
            if not _is_text(text):
                text = ""
            out.append({"filename": name, "ext": ext, "bytes": len(data) if data else 0, "downloaded": bool(data),
                        "readable": bool(text), "known_type": ext in KNOWN, "text": text})
    except Exception as e:
        db.event("attachments_error", mail.get("thread_id"), mail.get("id"), error=str(e)[:300])
    mail["attachments_text"] = out
    if out:
        db.event("attachments", mail.get("thread_id"), mail.get("id"),
                 files=[dict({k: v for k, v in f.items() if k != "text"}, preview=f["text"][:300]) for f in out])
    return out


def for_llm(mail):
    """The mail as the LLM should see it. Unchanged unless ATTACH_LLM=1 and there is readable attachment text."""
    files = [f for f in mail.get("attachments_text") or [] if f["readable"]]
    if not config.ATTACH_LLM or not files:
        return mail
    parts, used = [], 0
    for f in files:
        chunk = f["text"].strip()[:min(PER_FILE, TOTAL - used)]
        if not chunk:
            break
        parts.append("--- attached file: %s ---\n%s" % (f["filename"], chunk))
        used += len(chunk)
    note = ("\n\n[Files attached to this email, as text. They are part of the request. If a file states a fact the "
            "email does not (dangerous goods, a weight, a volume), use the file.]\n")
    return dict(mail, body=(mail.get("body") or "")[:3000] + note + "\n".join(parts))
