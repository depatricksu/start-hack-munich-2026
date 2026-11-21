#!/usr/bin/env python3
"""Parse the 10 airline tariff files of the start kit into one table.

Output: pricing/tariffs.json  (one record per airline + origin + destination)

Price rule (identical in every sheet header):
  chargeable = max(weight_kg, volume_cbm * 167)
  freight    = max(minimum, rate_for_bracket(chargeable) * chargeable)
  total      = freight + (fuel + security) * chargeable
The minimum applies to the freight before surcharges. Run: python pricing/parse_tariffs.py
"""
import glob, json, os, re, shutil, subprocess, sys
# openpyxl / docx / pdftotext are imported where used: a missing one must not crash the runner.

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "..", "kit", "start-kit")
OUT = os.path.join(HERE, "tariffs.json")

# Danube Wings is a photo (2 JPG pages). Transcribed by eye from the images; re-check against the JPGs.
DANUBE_BREAKS = [0, 45, 100, 300, 500, 1000]
DANUBE = [  # lane, transit, minimum, rates x6, fuel, security
    ("CGN-SYD", 4, 134.00, [6.28, 5.34, 4.28, 3.89, 3.27, 2.84], 1.13, 0.23),
    ("DUS-MEX", 5, 101.00, [3.02, 2.36, 1.89, 1.57, 1.32, 1.00], 0.74, 0.24),
    ("DUS-SYD", 5, 110.00, [5.78, 4.45, 3.92, 2.90, 2.20, 1.89], 0.69, 0.16),
    ("DUS-YYZ", 4, 62.00, [3.08, 2.62, 2.07, 1.61, 1.22, 0.96], 0.88, 0.21),
    ("FRA-DXB", 2, 138.86, [2.90, 2.23, 2.05, 1.66, 1.45, 1.33], 1.12, 0.22),
    ("FRA-EZE", 2, 126.00, [4.57, 3.34, 2.74, 2.52, 1.92, 1.48], 1.06, 0.21),
    ("MUC-JNB", 7, 105.00, [3.74, 2.81, 2.19, 1.62, 1.39, 1.22], 0.85, 0.24),
    ("MUC-TPE", 5, 69.00, [4.10, 3.73, 3.21, 2.57, 2.36, 2.03], 1.15, 0.21),
    ("STR-SGN", 5, 83.00, [4.63, 4.21, 3.45, 2.93, 2.40, 2.18], 1.09, 0.11),
]

CODE = re.compile(r"\b([A-Z]{3})\b")
SUR = re.compile(r"fuel\s*(?:EUR\s*)?([\d.,]+)\s*per kg,?\s*security\s*(?:EUR\s*)?([\d.,]+)", re.I)
BREAK_CELL = re.compile(r"^(?:from\s+)?[-+]?\d+(?:\s*kg\+?)?$", re.I)


def num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = re.sub(r"(EUR|USD|€|\$)", "", str(x)).strip()
    if re.fullmatch(r"-?\d+(?:[.,]\d+)?", s):
        return float(s.replace(",", "."))
    return None


def transit(x):
    m = re.search(r"\d+", str(x))
    return int(m.group()) if m else None


def lane_of(text, origin=None):
    codes = CODE.findall(text)
    if len(codes) >= 2:
        return codes[0], codes[-1]
    if len(codes) == 1 and origin:
        return origin, codes[0]
    return None


BRK_TOKEN = re.compile(r"from\s+(\d+)\s*kg|(\d+)\s*kg\+|(?<![\w.,])([-+]\d+)(?![\w.,])", re.I)


def breaks_from(cells):
    """Weight breaks from a header row. Handles 'from 45 kg', '45 kg+', '-45 +45 +100'.
    Tokens are searched in the joined row because some PDFs squeeze two headers into one cell."""
    text = " ".join(str(c) for c in cells if c != "")
    if re.search(r"\d+[.,]\d{2}", text):  # a data row, not a header
        return None
    toks = BRK_TOKEN.findall(text)
    if len(toks) < 3:
        return None
    nums = [int(next(g for g in t if g).lstrip("+-")) for t in toks]
    return [0] + nums[1:] if toks[0][2].startswith("-") else nums


def _pdf_text(path):
    """pdftotext (poppler) if installed, else pypdf in layout mode."""
    if shutil.which("pdftotext"):
        return subprocess.check_output(["pdftotext", "-layout", path, "-"]).decode()
    import pypdf
    return "\n".join(pg.extract_text(extraction_mode="layout") for pg in pypdf.PdfReader(path).pages)


def load_rows(path):
    """Return list of rows (each a list of cell strings or floats) for any format."""
    ext = path.rsplit(".", 1)[1].lower()
    rows = []
    if ext == "xlsx":
        import openpyxl
        for ws in openpyxl.load_workbook(path, data_only=True):
            for r in ws.iter_rows(values_only=True):
                rows.append(["" if c is None else (c if isinstance(c, (int, float)) else str(c).strip()) for c in r])
    elif ext == "docx":
        import docx
        d = docx.Document(path)
        for p in d.paragraphs:
            if p.text.strip():
                rows.append([p.text.strip()])
        for t in d.tables:
            for tr in t.rows:
                rows.append([c.text.strip() for c in tr.cells])
    elif ext == "pdf":
        txt = _pdf_text(path)
        for ln in txt.splitlines():
            if ln.strip():
                rows.append([c.strip() for c in re.split(r"\s{2,}", ln.strip())])
    elif ext == "txt":
        for ln in open(path, encoding="utf-8").read().splitlines():
            if ln.strip():
                rows.append([c.strip() for c in re.split(r"\s{2,}", ln.strip())])
    return rows


def parse_file(path):
    airline = None
    rows = load_rows(path)
    airline = rows[0][0].split("|")[0].strip()
    origin = None
    breaks = None
    inline_sur = False
    lanes = {}      # (o,d) -> record
    sur = {}        # (o,d) -> (fuel, sec)
    block = None    # block style (one lane per block of lines)

    def flush():
        nonlocal block
        if block and block.get("rates"):
            lanes[block["lane"]] = block
        block = None

    for r in rows[1:]:
        cells = [c for c in r]
        text = " ".join(str(c) for c in cells if c != "")
        # surcharge line (any layout)
        ms = SUR.search(text)
        if ms:
            ln = lane_of(text.split(":")[0])
            if ln:
                sur[ln] = (num(ms.group(1)), num(ms.group(2)))
            continue
        first = str(cells[0]).strip() if cells else ""
        if first.lower().startswith("origin"):
            flush()
            codes = CODE.findall(first)
            origin = codes[-1] if codes else origin
            breaks = None
            continue
        b = breaks_from([str(c) for c in cells])
        if b:
            breaks = b
            inline_sur = any(str(c).strip().lower() == "fuel" for c in cells)
            continue
        low = first.lower()
        # block layout (label in col 0, value in col 1)
        if len(cells) == 1 and lane_of(first, origin) and re.fullmatch(r"[A-Z]{3}[\s-].*", first) and not low.startswith(("lane", "destination")):
            flush()
            o, d = lane_of(first, origin)
            block = {"lane": (o, d), "rates": [], "breaks": []}
            continue
        if block is not None and len(cells) >= 2:
            val = num(cells[1])
            if low == "transit":
                block["transit"] = transit(cells[1])
            elif low == "minimum":
                block["min"] = val
            elif low == "fuel":
                block["fuel"] = val
            elif low == "security":
                block["security"] = val
            else:
                m = re.match(r"from (\d+) kg", low)
                if m and val is not None:
                    block["breaks"].append(int(m.group(1)))
                    block["rates"].append(val)
            continue
        # table row layout
        if breaks and len(cells) >= 3 + len(breaks):
            ln = lane_of(first, origin)
            vals = [num(c) for c in cells[2:2 + len(breaks) + 1]]
            extra = [c for c in cells[3 + len(breaks):] if c != ""]
            if ln and num(cells[2]) is not None and all(v is not None for v in vals[1:]) and len(extra) in ((0, 2) if inline_sur else (0,)):
                rec = {"lane": ln, "transit": transit(cells[1]), "min": num(cells[2]),
                       "rates": [num(c) for c in cells[3:3 + len(breaks)]], "breaks": list(breaks)}
                if inline_sur:
                    rest = [num(c) for c in cells[3 + len(breaks):] if c != ""]
                    if len(rest) >= 2:
                        rec["fuel"], rec["security"] = rest[0], rest[1]
                lanes[ln] = rec
    flush()
    out = []
    for (o, d), rec in lanes.items():
        f, s = (rec.get("fuel"), rec.get("security"))
        if f is None and (o, d) in sur:
            f, s = sur[(o, d)]
        out.append({"airline": airline, "origin": o, "destination": d, "transit_days": rec.get("transit"),
                    "min_charge": rec.get("min"), "breaks_kg": rec["breaks"] or breaks, "rates_per_kg": rec["rates"],
                    "fuel_per_kg": f, "security_per_kg": s, "currency": "EUR",
                    "source": os.path.basename(path)})
    return out


def parse_danube():
    return [{"airline": "Danube Wings Cargo", "origin": l[:3], "destination": l[4:], "transit_days": t, "min_charge": m,
             "breaks_kg": DANUBE_BREAKS, "rates_per_kg": r, "fuel_per_kg": f, "security_per_kg": s, "currency": "EUR",
             "source": "danube-wings-cargo-tariff-2026-11-p1.jpg+p2.jpg (manual transcription)"}
            for l, t, m, r, f, s in DANUBE]


def check(recs):
    problems = []
    for r in recs:
        k = f'{r["airline"]} {r["origin"]}-{r["destination"]}'
        for f in ("transit_days", "min_charge", "fuel_per_kg", "security_per_kg"):
            if r[f] is None:
                problems.append(f"{k}: missing {f}")
        if len(r["rates_per_kg"]) != len(r["breaks_kg"]):
            problems.append(f"{k}: {len(r['rates_per_kg'])} rates vs {len(r['breaks_kg'])} breaks")
        if any(a < b for a, b in zip(r["rates_per_kg"], r["rates_per_kg"][1:])):
            problems.append(f"{k}: rates not descending {r['rates_per_kg']}")
    return problems


def main():
    recs = []
    for p in sorted(glob.glob(os.path.join(KIT, "*"))):
        if re.search(r"tariff.*\.(xlsx|pdf|docx|txt)$", p):
            got = parse_file(p)
            print(f"{os.path.basename(p):55s} {len(got):3d} lanes")
            recs += got
    d = parse_danube()
    print(f"{'danube (manual)':55s} {len(d):3d} lanes")
    recs += d
    recs.sort(key=lambda r: (r["airline"], r["origin"], r["destination"]))
    json.dump(recs, open(OUT, "w"), indent=1)
    pr = check(recs)
    print(f"\n{len(recs)} lanes, {len(set(r['airline'] for r in recs))} airlines -> {OUT}")
    print("PROBLEMS:" if pr else "no problems", *pr, sep="\n  ")
    return 1 if pr else 0


if __name__ == "__main__":
    sys.exit(main())
