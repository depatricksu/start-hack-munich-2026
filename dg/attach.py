"""Attachment bytes -> plain text, so a DG declaration in a packing list / SLI can be found. Owner: Riky.

    text = dg.attachment_text(data, filename)          # xlsx, docx, pdf, csv, txt; "" when unreadable
    info = dg.scan_attachments([(filename, data), ...])  # {"un", "class", "name", "file"} or None

Standard library only. PDF needs macOS (PDFKit via `swift`, the runner is a Mac) or `pdftotext`; without either a PDF
gives "" (never an exception). Each reader is time-boxed so one odd file cannot hold up a quote.
"""
import io, os, re, shutil, subprocess, tempfile, zipfile

from .quote import read_declaration

SWIFT_PDF = ('import PDFKit; let d = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1]))!; '
             'for i in 0..<d.pageCount { print(d.page(at: i)?.string ?? "") }')
PDF_TIMEOUT_S = float(os.environ.get("DG_PDF_TIMEOUT_S", "8"))


def _xml_text(xml):
    xml = re.sub(r"</(?:w:p|a:p|row|si)>", "\n", xml)
    xml = re.sub(r"</(?:w:tc|c)>", " | ", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&").replace("&apos;", "'").replace("&quot;", '"')


def _xlsx(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        s = z.read("xl/sharedStrings.xml").decode("utf-8", "replace")
        shared = [_xml_text(m).strip() for m in re.findall(r"<si>(.*?)</si>", s, re.S)]
    out = []
    for name in sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet")):
        sheet = z.read(name).decode("utf-8", "replace")
        for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
            cells = []
            for attrs, body in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
                v = re.search(r"<v>(.*?)</v>", body or "")
                kind = re.search(r't="(\w+)"', attrs)
                val = v.group(1) if v else _xml_text(body or "")
                if kind and kind.group(1) == "s" and v and val.isdigit() and int(val) < len(shared):
                    val = shared[int(val)]
                cells.append(val.strip())
            out.append(" | ".join(c for c in cells if c))
    return "\n".join(out)


def _docx(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    return "\n".join(_xml_text(z.read(n).decode("utf-8", "replace"))
                     for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*)\.xml$", n))


def _pdf(data):
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        for cmd in (["swift", "-e", SWIFT_PDF, path] if shutil.which("swift") else None,
                    ["pdftotext", "-layout", path, "-"] if shutil.which("pdftotext") else None):
            if not cmd:
                continue
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=PDF_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                continue
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        # last resort: text that sits uncompressed in the file
        return " ".join(re.findall(r"\(([^()]{2,200})\)", data.decode("latin-1", "replace")))
    finally:
        os.unlink(path)


def attachment_text(data, filename=""):
    """Best-effort text of one attachment. Never raises."""
    if not data:
        return ""
    name = (filename or "").lower()
    try:
        if name.endswith((".xlsx", ".xlsm")) or (data[:2] == b"PK" and b"xl/" in data[:4000]):
            return _xlsx(data)
        if name.endswith(".docx") or (data[:2] == b"PK" and b"word/" in data[:4000]):
            return _docx(data)
        if name.endswith(".pdf") or data[:5] == b"%PDF-":
            return _pdf(data)
        return data.decode("utf-8", "replace")                 # csv, txt, eml body
    except Exception:
        return ""


def download(mail_id, att, timeout=10):
    """Raw bytes of one mailbox attachment (inline base64 or the mailbox API). None on any error."""
    import base64, urllib.parse, urllib.request
    try:
        if att.get("content_base64"):
            return base64.b64decode(att["content_base64"])
        from core import config
        att_id = att.get("id") or att.get("attachment_id")
        if att_id is None or not config.API_KEY:
            return None
        url ="%s/v1/mailbox/messages/%s/attachments/%s" % (config.BASE_URL, mail_id, urllib.parse.quote(str(att_id)))
        req = urllib.request.Request(url, headers={"X-API-Key": config.API_KEY})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def check_mail(mail):
    """The one call for an RFQ: DG declared in any attachment (or, with a UN number, in the mail itself)?
    Returns {"un", "class", "name", "file"} or None. Never raises."""
    try:
        files = []
        for att in mail.get("attachments") or []:
            name = att.get("filename") or att.get("name") or "attachment"
            data = download(mail["id"], att)
            if data:
                files.append((name, data))
        from .facts import remember
        remember(mail.get("id"), "\n".join(attachment_text(data, name) for name, data in files))
        found = scan_attachments(files)
        if found:
            return found
        info = read_declaration(mail.get("body") or "")       # a denial ("no dangerous goods") is not DG
        return dict(info, file="mail body") if info else None
    except Exception:
        return None


def scan_attachments(files):
    """files: [(filename, bytes)]. Returns the first DG declaration found, with the file it came from, or None."""
    for name, data in files or []:
        info = read_declaration(attachment_text(data, name))
        if info:
            return dict(info, file=name)
    return None
