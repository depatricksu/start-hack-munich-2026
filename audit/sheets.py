"""Second pair of eyes on the rate sheets. Owner: Riky.

Re-reads the 10 airline tariff files in kit/start-kit/ with its OWN parser (independent of pricing/parse_tariffs.py)
and compares every number with pricing/tariffs.json: transit, minimum, the rate of every weight bracket, fuel, security.

    python3 -m audit.sheets            # report, exit code 1 if any lane differs
    python3 -m audit.sheets --verbose  # also list every lane that matches

Read-only, standard library only. Never imported by the clerk and has no test file, so it cannot block core.restart.
PDF text needs macOS (PDFKit via `swift`) or `pdftotext`; without either the two PDF sheets are skipped, not failed.
Danube Wings is two photos: its values in pricing/parse_tariffs.py were checked by eye, cell by cell (21 Nov, 17:00);
this tool cannot read the JPGs and says so.
"""
import json, os, re, shutil, subprocess, sys, zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
KIT = os.path.join(ROOT, "kit", "start-kit")
TARIFFS = os.path.join(ROOT, "pricing", "tariffs.json")
NUM = r"(\d+(?:[.,]\d+)?)"
SWIFT_PDF = ('import PDFKit; let d = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1]))!; '
             'for i in 0..<d.pageCount { print(d.page(at: i)?.string ?? "") }')


def f(s):
    return float(s.replace(",", "."))


# ---------- reading the files ----------

def pdf_text(path):
    """PDF -> text in the line layout this parser expects (PDFKit). pdftotext is a fallback."""
    if shutil.which("swift"):
        r = subprocess.run(["swift", "-e", SWIFT_PDF, path], capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return r.stdout
    return None


def docx_text(path):
    x = zipfile.ZipFile(path).read("word/document.xml").decode()
    x = re.sub(r"</w:p>", "\n", x)
    x = re.sub(r"</w:tc>", " | ", x)
    return re.sub(r"<[^>]+>", "", x)


def xlsx_rows(path):
    """Every row of every sheet as a list of cell strings (shared strings resolved)."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        s = z.read("xl/sharedStrings.xml").decode()
        shared = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<si>(.*?)</si>", s, re.S)]
    rows = []
    for name in sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet")):
        sheet = z.read(name).decode()
        for row in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
            cells = []
            for attrs, body in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
                v = re.search(r"<v>(.*?)</v>", body or "")
                kind = re.search(r't="(\w+)"', attrs)
                val = v.group(1) if v else re.sub(r"<[^>]+>", "", body or "")
                if kind and kind.group(1) == "s" and v:
                    val = shared[int(val)]
                cells.append(val.replace("&gt;", ">").strip())
            rows.append(cells)
    return rows


# ---------- one parser per layout ----------

def lane(transit, minimum, rates, fuel=None, security=None):
    return {"transit": transit, "min": minimum, "rates": rates, "fuel": fuel, "sec": security}


def surcharges(lanes, text):
    """'<anything with ORIGIN and DEST>: fuel [EUR] x per kg, security [EUR] y per kg' lines."""
    for line in text.splitlines():
        m = re.search(r"fuel (?:EUR )?" + NUM + r" per kg, security (?:EUR )?" + NUM, line)
        if not m:
            continue
        codes = re.findall(r"\b([A-Z]{3})\b", line.split(":")[0])
        if len(codes) >= 2 and (codes[0], codes[-1]) in lanes:
            lanes[(codes[0], codes[-1])].update(fuel=f(m.group(1)), sec=f(m.group(2)))


def parse_blocks(text):
    """Cobalt (PDF) and Orion (PDF): one block per lane, 'from N kg rate' lines."""
    lanes = {}
    starts = list(re.finditer(r"^([A-Z]{3})(?: [^\n>]*> |-)([A-Z]{3})\b.*$", text, re.M))
    for i, m in enumerate(starts):
        block = text[m.start(): starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        block = block.split("Surcharges per kg")[0]
        if "Transit" not in block:                      # a 'ORG-DST: fuel ...' surcharge line, not a lane
            continue
        fuel = re.search(r"^Fuel " + NUM, block, re.M)
        sec = re.search(r"^Security " + NUM, block, re.M)
        lanes[(m.group(1), m.group(2))] = lane(
            int(re.search(r"Transit (\d+)", block).group(1)), f(re.search("Minimum " + NUM, block).group(1)),
            [f(x) for x in re.findall(r"from \d+ kg " + NUM, block)],
            f(fuel.group(1)) if fuel else None, f(sec.group(1)) if sec else None)
    surcharges(lanes, text)
    return lanes


def parse_lines(text):
    """Helix (PDF) and Yellowtail (txt): one line per lane with 'EUR x' cells."""
    lanes = {}
    body = text.split("Surcharges per kg")[0]
    for line in body.splitlines():
        codes = re.findall(r"\b([A-Z]{3})\b", line.split("EUR")[0])
        tr = re.search(r"(?:D\+|\s)(\d+)\s+EUR", line)
        vals = [f(x) for x in re.findall(r"EUR " + NUM, line)]
        if len(codes) >= 2 and tr and len(vals) >= 3:
            lanes[(codes[0], codes[1])] = lane(int(tr.group(1)), vals[0], vals[1:])
    surcharges(lanes, text)
    return lanes


def parse_docx(text):
    """Quetzal (docx): table cells, lane 'ORG-DST' then transit, minimum, 7 rates."""
    lanes = {}
    body = text.split("Surcharges per kg")[0]
    cells = [c.strip() for c in body.replace("\n", "|").split("|") if c.strip()]
    i = 0
    while i < len(cells):
        if re.fullmatch(r"[A-Z]{3}-[A-Z]{3}", cells[i]):
            n = 3
            while i + n < len(cells) and re.fullmatch(r"\d+(?:[.,]\d+)?", cells[i + n]):
                n += 1
            lanes[(cells[i][:3], cells[i][4:])] = lane(int(re.search(r"\d+", cells[i + 1]).group()), f(cells[i + 2]),
                                                       [f(x) for x in cells[i + 3: i + n]])
            i += n
        else:
            i += 1
    surcharges(lanes, text)
    return lanes


def parse_xlsx(rows, surcharge_columns=False):
    """Elbflug, Kestrel, Vega, Wayzata (xlsx): 'Origin: X' sections or 'ORG City > DST City' lane cells."""
    lanes, origin = {}, None
    for c in rows:
        if not c:
            continue
        m = re.match(r"Origin: .*?([A-Z]{3})\)?$", c[0])
        if m:
            origin = m.group(1)
            continue
        if len(c) < 5:
            continue
        m = re.match(r"([A-Z]{3}) [^>]*> ([A-Z]{3})", c[0])
        if m:
            key = m.groups()
        else:
            m = re.search(r"\(?([A-Z]{3})\)?$", c[0])
            if not (m and origin):
                continue
            key = (origin, m.group(1))
        try:
            vals = [f(x) for x in c[2:]]
            transit = int(re.search(r"\d+", c[1]).group())
        except (ValueError, AttributeError):
            continue
        if surcharge_columns:
            lanes[key] = lane(transit, vals[0], vals[1:-2], vals[-2], vals[-1])
        else:
            lanes[key] = lane(transit, vals[0], vals[1:])
    surcharges(lanes, "\n".join(" ".join(r) for r in rows))
    return lanes


SHEETS = {  # airline -> (file, how to read it)
    "Cobalt Skylift": ("cobalt-skylift-tariff-2026-11.pdf", "pdf-blocks"),
    "Orion Cargo Air": ("orion-cargo-air-tariff-2026-11.pdf", "pdf-blocks"),
    "Helix Air Freight": ("helix-air-freight-tariff-2026-11.pdf", "pdf-lines"),
    "Yellowtail Air Freight": ("yellowtail-air-freight-tariff-2026-11.txt", "txt-lines"),
    "Quetzal Air Freight": ("quetzal-air-freight-tariff-2026-11.docx", "docx"),
    "Elbflug Air Freight": ("elbflug-air-freight-tariff-2026-11.xlsx", "xlsx"),
    "Kestrel Airways": ("kestrel-airways-tariff-2026-11.xlsx", "xlsx-surcharge-columns"),
    "Vega Skyfreight": ("vega-skyfreight-tariff-2026-11.xlsx", "xlsx"),
    "Wayzata Air Cargo": ("wayzata-air-cargo-tariff-2026-11.xlsx", "xlsx"),
}


def read_sheet(airline):
    name, how = SHEETS[airline]
    path = os.path.join(KIT, name)
    if how.startswith("pdf"):
        text = pdf_text(path)
        if text is None:
            return None
        return parse_blocks(text) if how == "pdf-blocks" else parse_lines(text)
    if how == "txt-lines":
        return parse_lines(open(path, encoding="utf-8").read())
    if how == "docx":
        return parse_docx(docx_text(path))
    return parse_xlsx(xlsx_rows(path), surcharge_columns=how == "xlsx-surcharge-columns")


# ---------- the comparison ----------

def differences(mine, rec):
    out = []
    if mine["transit"] != rec["transit_days"]:
        out.append(("transit", mine["transit"], rec["transit_days"]))
    if abs(mine["min"] - rec["min_charge"]) > 0.001:
        out.append(("minimum", mine["min"], rec["min_charge"]))
    if [round(x, 2) for x in mine["rates"]] != [round(x, 2) for x in rec["rates_per_kg"]]:
        out.append(("rates", mine["rates"], rec["rates_per_kg"]))
    for key, field in (("fuel", "fuel_per_kg"), ("sec", "security_per_kg")):
        if mine[key] is None or abs(mine[key] - rec[field]) > 0.001:
            out.append((key, mine[key], rec[field]))
    return out


def audit(verbose=False):
    records = json.load(open(TARIFFS))
    by_airline = {}
    for r in records:
        by_airline.setdefault(r["airline"], []).append(r)
    checked = problems = 0
    for airline, recs in sorted(by_airline.items()):
        if airline not in SHEETS:
            print(f"SKIP  {airline}: {len(recs)} lanes, not machine-readable (checked by eye against the photos)")
            continue
        sheet = read_sheet(airline)
        if sheet is None:
            print(f"SKIP  {airline}: no PDF reader on this machine (needs macOS swift or pdftotext)")
            continue
        for r in recs:
            key = (r["origin"], r["destination"])
            checked += 1
            if key not in sheet:
                problems += 1
                print(f"DIFF  {airline} {key[0]}-{key[1]}: in tariffs.json but not found in the sheet")
                continue
            diff = differences(sheet[key], r)
            if diff:
                problems += 1
                print(f"DIFF  {airline} {key[0]}-{key[1]}: " + "; ".join(f"{k} sheet={a} ours={b}" for k, a, b in diff))
            elif verbose:
                print(f"ok    {airline} {key[0]}-{key[1]}")
        for key in sorted(set(sheet) - {(r["origin"], r["destination"]) for r in recs}):
            problems += 1
            print(f"DIFF  {airline} {key[0]}-{key[1]}: in the sheet but missing from tariffs.json")
    print(f"\n{checked} lanes checked against the sheets, {problems} problems.")
    return problems


if __name__ == "__main__":
    sys.exit(1 if audit("--verbose" in sys.argv) else 0)
