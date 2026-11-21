"""Attachment bytes -> plain text, so a DG declaration in a packing list / SLI can be found. Owner: Riky.

    text = dg.attachment_text(data, filename)          # xlsx, docx, pdf, csv, txt; "" when unreadable
    info = dg.scan_attachments([(filename, data), ...])  # {"un", "class", "name", "file"} or None

Standard library only. PDF needs macOS (PDFKit via `swift`, the runner is a Mac) or `pdftotext`; without either a PDF
gives "" (never an exception). Each reader is time-boxed so one odd file cannot hold up a quote.
"""
import io, os, re, shutil, subprocess, tempfile, threading, time, zipfile

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


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff", ".gif", ".bmp", ".webp")
OCR_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr.swift")
OCR_TIMEOUT_S = float(os.environ.get("DG_OCR_TIMEOUT_S", "5"))         # per page, once the worker is warm
OCR_WARMUP_S = float(os.environ.get("DG_OCR_WARMUP_S", "60"))          # first page: Vision loads its model
OCR_END = "<<<OCR-END>>>"
_OCR_OFF_UNTIL = [0.0]   # circuit breaker: after a failure, skip OCR for 10 minutes so no request waits again
_WORKER = {"proc": None, "warm": False}
_LOCK = threading.Lock()


def _ocr_bin_path():
    """data/ocr_bin_<hash of ocr.swift>: a changed source gets a fresh build, an old binary is never reused."""
    import hashlib
    with open(OCR_SRC, "rb") as f:
        tag = hashlib.sha1(f.read()).hexdigest()[:8]
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ocr_bin_" + tag)   # git-ignored


def ocr_binary(report=None):
    """The compiled macOS Vision OCR tool. Built once (~3 s); None when there is no swiftc (not a Mac) or it fails."""
    path = _ocr_bin_path()
    if os.path.exists(path):
        return path
    swiftc = shutil.which("swiftc")
    if not swiftc:
        if report is not None:
            report.append("swiftc not found: install Xcode Command Line Tools (xcode-select --install)")
        return None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".%d" % os.getpid()
        r = subprocess.run([swiftc, "-O", OCR_SRC, "-o", tmp], capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            os.replace(tmp, path)                              # atomic: two clerks never see half a binary
            return path
        if report is not None:
            report.append("swiftc failed: " + (r.stderr or r.stdout)[-600:])
    except Exception as e:
        if report is not None:
            report.append("swiftc error: %r" % e)
    return None


def _worker():
    """One long-lived OCR process (Vision model loaded once). Started lazily, restarted if it died."""
    p = _WORKER["proc"]
    if p is not None and p.poll() is None:
        return p
    binary = ocr_binary()
    if not binary:
        return None
    _WORKER["proc"] = subprocess.Popen([binary, "--serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, bufsize=0)   # raw bytes: select() sees every byte
    _WORKER["warm"] = False
    return _WORKER["proc"]


def _ask(path, timeout):
    """Send one path to the worker, read its text until the end marker. None on timeout / crash."""
    import select
    p = _worker()
    if p is None:
        return None
    p.stdin.write((path + "\n").encode())
    fd, buf, end = p.stdout.fileno(), b"", OCR_END.encode()
    deadline = time.time() + timeout
    while end not in buf:
        left = deadline - time.time()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            p.kill()                                           # stuck: drop it, the next call starts a new one
            _WORKER["proc"] = None
            return None
        chunk = os.read(fd, 65536)
        if not chunk:                                          # the worker died
            _WORKER["proc"] = None
            return None
        buf += chunk
    _WORKER["warm"] = True
    return buf.split(end)[0].decode("utf-8", "replace").strip()


def ocr(data, suffix):
    """Text in a photo / scan (macOS Vision). "" when not possible. Never raises."""
    if time.time() < _OCR_OFF_UNTIL[0]:
        return ""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        path = f.name
    try:
        with _LOCK:
            text = _ask(path, OCR_TIMEOUT_S if _WORKER["warm"] else OCR_WARMUP_S)
    except Exception:
        text = None
    finally:
        os.unlink(path)
    if text is None:
        _OCR_OFF_UNTIL[0] = time.time() + 600
        return ""
    return text


def warm_up():
    """Build + start the worker and read one tiny page, in the background, so the first real photo is fast."""
    def go():
        try:
            sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kit", "start-kit",
                                  "danube-wings-cargo-tariff-2026-11-p2.jpg")
            if os.path.exists(sample):
                with _LOCK:
                    _ask(os.path.abspath(sample), OCR_WARMUP_S)
        except Exception:
            pass
    if shutil.which("swiftc") or os.path.exists(_ocr_bin_path()):
        threading.Thread(target=go, daemon=True).start()


def doctor():
    """python3 -m dg.attach  -> why OCR does or does not work on this machine."""
    report = []
    print("swiftc:", shutil.which("swiftc"))
    t = time.time()
    b = ocr_binary(report)
    print("binary:", b, "(%.1f s)" % (time.time() - t))
    for line in report:
        print("  ", line)
    if not b:
        return 1
    sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kit", "start-kit",
                          "danube-wings-cargo-tariff-2026-11-p2.jpg")
    for label in ("first page (loads the Vision model)", "second page (warm)"):
        t = time.time()
        text = _ask(os.path.abspath(sample), OCR_WARMUP_S)
        print("%s: %.2f s, %s" % (label, time.time() - t, "OK" if text and "CGN-SYD" in text else "NO TEXT: %r" % text))
    return 0


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
            text = _pdf(data)
            return text if len(text.strip()) > 20 else (ocr(data, ".pdf") or text)   # a scanned PDF has no text layer
        if name.endswith(IMAGE_EXT) or data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n":
            return ocr(data, os.path.splitext(name)[1] or ".jpg")
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
        done = [f for f in mail.get("attachments_text") or [] if f.get("text")]   # core/attachments.py read them (Kai)
        if done:
            from .facts import remember
            remember(mail.get("id"), "\n".join(f["text"] for f in done))
            for f in done:
                info = read_declaration(f["text"])
                if info:
                    return dict(info, file=f.get("filename"))
            info = read_declaration(mail.get("body") or "")
            return dict(info, file="mail body") if info else None
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


if __name__ == "__main__":
    import sys
    sys.exit(doctor())
