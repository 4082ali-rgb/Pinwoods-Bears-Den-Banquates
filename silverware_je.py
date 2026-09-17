#!/usr/bin/env python3
"""
silverware_je.py  -  Silverware "Daily Totals" PDF -> QuickBooks Online journal entry CSV
                     + revenue-by-segment CSV.   Manning Park Resort.

One script for the three Silverware outlets:

    Pinewoods   (Cost Center: Pinewoods)   class 0020-PINEWOODS
    Bears Den   (Cost Center: Bears Den)   class 0092-BEARS DEN
    Banquets    (Cost Center: Banquets)    class 0101 - BANQUET- FOOD / 0102 - BANQUET LIQUOR

The outlet is read from the report's own "Cost Center:" line - never the filename.

USAGE
    python3 silverware_je.py <report.pdf> <JournalNo> [--out DIR] [--dry-run] [--outlet NAME]

    python3 silverware_je.py Bears_Den_Aug_28.pdf JJ3382
    python3 silverware_je.py Banquets_Aug_15.pdf JJ3431 --out ./csv
    python3 silverware_je.py PW_Aug_31.pdf JJ3417 --dry-run
    python3 silverware_je.py report.txt JJ3417            # pre-extracted / OCR'd text also accepted

For every run the script:
  1. Extracts text (pdftotext -layout -> pdfplumber -> OCR if available)
  2. Reads From Date + Cost Center from the report body and picks the outlet profile
  3. Pulls Sales, Discounts, Taxes, Non-Cash Tips, Auto Gratuity and every Payment tender
  4. Maps everything to GL accounts / classes per the outlet's rules
  5. Proves Debits == Credits - an unbalanced entry is NEVER written
  6. Writes the QBO journal CSV (CRLF line endings, no BOM)
  7. With --segments, also writes <JournalNo>_<Outlet>_<date>_segments.csv and upserts
     the rows into revenue_by_segment.csv (cumulative, all outlets)
  8. Appends to silverware_log.csv (JournalNo, Outlet, Date, file) and prints FLAGS

Anything unrecognised (new tender, new sales category, new tax line) STOPS the script
so nothing ever posts to the wrong account silently.  Add the mapping to the outlet
profile below and re-run.
"""

import argparse
import csv
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# SHARED ACCOUNT STRINGS - must match the QBO Chart of Accounts EXACTLY
# ---------------------------------------------------------------------------

A_CASH      = "1002 Petty Cash in safe"
A_CARDS     = "1007 Visa / Mstrcrd / Debit Receivable"
A_GIFTCERT  = "2005 Gift Certificates"
A_GST       = "2029 GST Charged on Sales"
A_PST       = "2035 PST 7% Charged on Sales"
A_PST_LIQ   = "2039 PST 10% Liquor Charged on Sales"
A_REVENUE   = "3001 Revenue"
A_FOOD      = "3002 Revenue - Food"
A_LIQUOR    = "3003 Revenue - Liquor"
A_WINE      = "3004 Revenue - Wine"
A_BEER      = "3005 Revenue - Beer"
A_NABEV     = "3006 Revenue - Non-Alcoholic"
A_GIFTCARD  = "3023 Revenue - Gift Cards"
A_BANQUETS  = "3031 Revenue - Banquets & Wedding"
A_DISCOUNT  = "3050 Discounts given"
A_ROOMCHG   = "3051 ROOM CHARGE R/C"
A_TIPS      = "6044 Tips & Gratuities"

C_PINEWOODS = "0020-PINEWOODS"
C_BEARSDEN  = "0092-BEARS DEN"
C_BQ_FOOD   = "0101 - BANQUET- FOOD"
C_BQ_LIQUOR = "0102 - BANQUET LIQUOR"

TAX_MAP = {"GST": A_GST, "PST": A_PST, "ALCOHOL": A_PST_LIQ}

# ---------------------------------------------------------------------------
# OUTLET PROFILES  -  edit here when a mapping changes or a new line appears
#
#   sales:    printed label -> (account, description prefix or None, class override or None)
#   tenders:  printed label (upper, "(...)" stripped) -> (account, description prefix or None)
#   sales_basis: "gross" (credit gross + debit 3050 discount) or "net" (credit net Amount)
#   desc_prefix: "always" | "never" | "duplicates" (prefix only when the same account
#                appears more than once in the entry)
#   memo_date: strftime for the memo text - never a comma (QBO importer splits on it)
#   filename:  python format string; keys jn, outlet, date, mon, dd, yyyy, iso
# ---------------------------------------------------------------------------

PROFILES = {
    "pinewoods": {
        "name": "Pinewoods",
        "cost_center": "Pinewoods",
        "default_class": C_PINEWOODS,
        "sales_basis": "net",                # net Amount column (post-discount) - no 3050 line
        "sales": {
            "01 - FOOD":     (A_FOOD,     None,       None),
            "02 - LIQUOR":   (A_LIQUOR,   None,       None),
            "03 - WINE":     (A_WINE,     None,       None),
            "04 - BEER":     (A_BEER,     None,       None),
            "05 - N/A BEV":  (A_NABEV,    None,       None),
            "10- MODIFIERS": (A_REVENUE,  "Modifers", None),
            "11-BANQUETS":   (A_BANQUETS, "Banquets", C_BQ_FOOD),
        },
        "tenders": {
            "CASH":    (A_CASH,     None),
            "MC":      (A_CARDS,    "Mastercard"),
            "VISA":    (A_CARDS,    "Visa"),
            "DEBIT":   (A_CARDS,    "Debit"),
            "RMPOST":  (A_CARDS,    "RMPOST"),
            "RC":      (A_ROOMCHG,  None),
            "CORP GC": (A_GIFTCARD, "Corp GC"),
            "GIFT C":  (A_GIFTCERT, "Gift Certificate"),
        },
        "desc_prefix": "as_mapped",          # exactly what the original pinewoods_je.py did
        "desc_sep": "- ",
        "memo_date": "%B {d} %Y",            # August 28 2026
        "filename": "{jn}_{outlet}_{iso}.csv",
    },

    "bearsden": {
        "name": "Bears Den",
        "cost_center": "Bears Den",
        "default_class": C_BEARSDEN,
        "sales_basis": "net",
        "sales": {
            "01 - FOOD":      (A_FOOD,    None,         None),
            "02 - LIQUOR":    (A_LIQUOR,  None,         None),
            "03 - WINE":      (A_WINE,    None,         None),
            "04 - BEER":      (A_BEER,    None,         None),
            "05 - N/A BEV":   (A_NABEV,   None,         None),
            "10- MODIFIERS":  (A_REVENUE, "Modifiers",  None),
            "POOL TABLE":     (A_REVENUE, "Pool Table", None),   # printed as "Pool Table"
        },
        "tenders": {
            "CASH":    (A_CASH,     "Cash"),
            "MC":      (A_CARDS,    "MC"),
            "VISA":    (A_CARDS,    "Visa"),
            "DEBIT":   (A_CARDS,    "Debit"),
            "RMPOST":  (A_CARDS,    "RMPOST"),  # confirmed 2026-09-17: same as Pinewoods
            "CORP GC": (A_GIFTCARD, "Corp GC"),
            "RC":      (A_CARDS,    "RC"),     # spec: no confirmed dedicated account - flagged
        },
        "desc_prefix": "duplicates",
        "desc_sep": "-",
        "memo_date": "%B {d} %Y",            # August 28 2026
        "filename": "{jn}_BearsDen_{mon}{dd}.csv",
        "flag_tenders": {"RC": "RC tender posted to 1007 - no confirmed dedicated account yet; confirm."},
    },

    "banquets": {
        "name": "Banquets",
        "cost_center": "Banquets",
        "default_class": C_BQ_FOOD,
        "sales_basis": "net",
        "sales": {
            "01 - FOOD":     (A_FOOD,     "Food",      None),
            "02 - LIQUOR":   (A_LIQUOR,   "Liquor",    C_BQ_LIQUOR),
            "03 - WINE":     (A_WINE,     "Wine",      C_BQ_LIQUOR),
            "04 - BEER":     (A_BEER,     "Beer",      C_BQ_LIQUOR),
            "05 - N/A BEV":  (A_NABEV,    "N/A Bev",   None),
            "10- MODIFIERS": (A_REVENUE,  "Modifiers", None),
            "11-BANQUETS":   (A_BANQUETS, "Banquets",  None),
        },
        "tenders": {
            "CASH":    (A_CASH,     "Cash"),
            "MC":      (A_CARDS,    "MC"),
            "VISA":    (A_CARDS,    "Visa"),
            "DEBIT":   (A_CARDS,    "Debit"),
            "RC":      (A_ROOMCHG,  "RC"),
            "CORP GC": (A_GIFTCARD, "Corp GC"),
        },
        "desc_prefix": "always",
        "desc_sep": " - ",
        "memo_date": "{d} %B %Y",            # 15 August 2026
        "filename": "Banquets_JE_{mon}{dd}_{yyyy}.csv",
    },
}

# tax / tip / discount description prefixes (used only when the profile prefixes those lines)
TAX_PREFIX = {"GST": "GST", "PST": "PST", "ALCOHOL": "Alcohol Tax"}
TIPS_PREFIX = "Tips"
DISC_PREFIX = "Discounts"

CSV_FIELDS = ["*JournalNo", "*JournalDate", "Memo", "*AccountName",
              "Debits", "Credits", "Description", "Name", "Location", "Class"]

SEGMENT_FIELDS = ["Date", "Outlet", "JournalNo", "Type", "Segment", "Account", "Class",
                  "Gross", "Discount", "Net"]
SEGMENT_LEDGER = "revenue_by_segment.csv"
RUN_LOG = "silverware_log.csv"

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def extract_text(path: Path) -> str:
    """pdftotext -layout is the most faithful; fall back to pdfplumber, then OCR."""
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")

    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                             capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout

    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join((p.extract_text(layout=True) or "") for p in pdf.pages)
        if text.strip():
            return text
    except ImportError:
        pass

    text = ocr_text(path)
    if text and text.strip():
        return text

    sys.exit("ERROR: no text could be extracted from the PDF. It is probably a scanned/"
             "raster report. Install tesseract + pytesseract (or rapidocr_onnxruntime), or "
             "OCR it elsewhere and pass the resulting .txt file instead of the PDF.")


def ocr_text(path: Path) -> str:
    """Best-effort OCR for raster PDFs. Returns '' if no OCR engine is available."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        return ""
    if not shutil.which("tesseract"):
        return ""
    pages = convert_from_path(str(path), dpi=300)
    return "\n\f".join(pytesseract.image_to_string(p, config="--psm 6") for p in pages)

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

MONEY = r"-?\$-?[\d,]+\.\d{2}"   # "$" required so the Qnty column never matches

def money(s: str) -> float:
    neg = "-" in s
    val = float(re.sub(r"[^\d.]", "", s))
    return -val if neg else val

def r2(x: float) -> float:
    return round(x + 0.0, 2)

def section(text: str, header_regex: str) -> str:
    """Block from the header line to the next section header / Total On-Hand / page break."""
    m = re.search(header_regex, text, re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end():]
    stop = re.search(r"^(?=\S)[A-Za-z][^\n]*\bQnty\b|^\s*Total On-Hand|\f", rest, re.MULTILINE)
    return rest[:stop.start()] if stop else rest

def rows(block: str):
    for line in block.splitlines():
        if not line.strip() or re.match(r"^\s*Total:", line):
            continue
        amounts = re.findall(MONEY, line)
        label = re.split(r"\s{2,}", line.strip())[0].strip()
        yield label, amounts

def norm_label(label: str) -> str:
    """'02 - LIQUOR', '02-LIQUOR', '02 -LIQUOR' all compare equal."""
    return re.sub(r"\s*-\s*", "-", label.strip().upper())

def lookup(mapping: dict, label: str):
    """Find a mapping key that matches the printed label, tolerant of dash spacing."""
    if label in mapping:
        return label
    n = norm_label(label)
    for k in mapping:
        if norm_label(k) == n:
            return k
    return None

# ---------------------------------------------------------------------------
# Core parse
# ---------------------------------------------------------------------------

def detect_profile(text: str, forced: str | None):
    m = re.search(r"Cost Center:\s*(.+)", normalise(text))
    cc = m.group(1).strip() if m else "?"
    match = None
    for key, p in PROFILES.items():
        if cc.lower().replace(" ", "") == p["cost_center"].lower().replace(" ", ""):
            match = key
    if forced:
        if match and match != forced:
            sys.exit(f"ERROR: --outlet {forced} but the report's Cost Center is '{cc}' "
                     f"({PROFILES[match]['name']}). Refusing to continue.")
        return forced, cc
    if not match:
        sys.exit(f"ERROR: Cost Center '{cc}' is not a known Silverware outlet "
                 f"({', '.join(p['cost_center'] for p in PROFILES.values())}). "
                 f"Use --outlet to force one only if you are sure.")
    return match, cc


def normalise(text: str) -> str:
    """Real pdfplumber/pdftotext output is indented; anchor every line at column 0."""
    return "\n".join(l.strip() for l in text.splitlines())


def parse_report(text: str, profile: dict) -> dict:
    text = normalise(text)
    d = {"flags": []}

    m = re.search(r"From Date:\s*(\d{4}-\d{2}-\d{2})", text)
    if not m:
        sys.exit("ERROR: could not find 'From Date' in report.")
    d["date"] = datetime.strptime(m.group(1), "%Y-%m-%d").date()
    m2 = re.search(r"To Date:\s*(\d{4}-\d{2}-\d{2})", text)
    if m2 and m2.group(1) != m.group(1):
        d["flags"].append(f"Report spans {m.group(1)} to {m2.group(1)} - multi-day report; "
                          f"JE dated to From Date only.")

    # --- Sales -------------------------------------------------------------
    sales_block = section(text, r"^Sales\s+Qnty\s+Gross Amount")
    if not sales_block:
        sys.exit("ERROR: Sales section not found.")
    d["sales"] = {}          # mapping key -> {"gross","refund","disc","net"}
    sales_disc = 0.0
    for label, amts in rows(sales_block):
        if len(amts) < 4:
            continue
        gross, refund, disc, net = (money(a) for a in amts[:4])
        key = lookup(profile["sales"], label)
        if key is None:
            sys.exit(f"ERROR: unknown Sales category '{label}' (${gross:.2f}) for "
                     f"{profile['name']}. Add it to the profile's 'sales' map before posting.")
        if refund:
            d["flags"].append(f"Refunds ${refund:.2f} on '{label}' - verify treatment.")
        if gross or net:
            d["sales"][key] = {"label": label, "gross": gross, "refund": refund,
                               "disc": disc, "net": net}
        sales_disc += disc
    m = re.search(r"^\s*Total:\s+[\d.]+\s+(" + MONEY + r")\s+(" + MONEY + r")\s+("
                  + MONEY + r")\s+(" + MONEY + r")", sales_block, re.MULTILINE)
    if m:
        sales_disc = money(m.group(3))
    d["sales_discount"] = r2(sales_disc)

    # --- Non-Sales (09- DISCOUNT) ----------------------------------------
    d["nonsales_discount"] = 0.0
    ns_block = section(text, r"^Non-Sales\s+Qnty")
    if ns_block:
        for label, amts in rows(ns_block):
            if len(amts) >= 4:
                d["nonsales_discount"] += money(amts[2])
        if d["nonsales_discount"]:
            d["flags"].append(f"Non-Sales 09-DISCOUNT ${d['nonsales_discount']:.2f} is outside the "
                              f"sales net Amount - posted as a 3050 Discounts given debit.")
    d["discount_total"] = r2(d["sales_discount"] + d["nonsales_discount"])

    # --- Taxes -------------------------------------------------------------
    d["taxes"] = {}
    for label, amts in rows(section(text, r"^Taxes\s+Qnty")):
        if not amts:
            continue
        key = label.upper()
        if key not in TAX_MAP:
            sys.exit(f"ERROR: unknown tax line '{label}'. Add to TAX_MAP.")
        d["taxes"][key] = money(amts[-1])

    # --- Tips --------------------------------------------------------------
    m = re.search(r"Non-Cash Tips\s+[\d.]+\s+(" + MONEY + r")", text)
    d["noncash_tips"] = abs(money(m.group(1))) if m else 0.0
    d["auto_grat"] = 0.0
    ag_block = section(text, r"^Auto Gratuity\s+Qnty")
    if ag_block:
        m = re.search(r"Total:\s+[\d.]+\s+(" + MONEY + r")", ag_block)
        if m:
            d["auto_grat"] = abs(money(m.group(1)))
    else:
        m = re.search(r"Auto Gratuity\s+[\d.]+\s+(" + MONEY + r")", text)
        if m:
            d["auto_grat"] = abs(money(m.group(1)))
    d["tips_total"] = r2(d["noncash_tips"] + d["auto_grat"])

    # --- Payments ----------------------------------------------------------
    d["tenders"] = {}
    pay_block = section(text, r"^Payments\s+Qnty")
    if not pay_block:
        sys.exit("ERROR: Payments section not found.")
    for label, amts in rows(pay_block):
        low = label.lower()
        if not amts or low.startswith("cad foreign") or low.startswith("foreign"):
            continue
        key = re.sub(r"\s*\(.*?\)\s*", "", label).strip().upper()
        if key not in profile["tenders"]:
            sys.exit(f"ERROR: unknown payment tender '{label}' (${money(amts[-1]):.2f}) for "
                     f"{profile['name']}. Confirm the GL account and add it to the profile's "
                     f"'tenders' map before posting.")
        amt = money(amts[-1])
        if amt:
            d["tenders"][key] = amt

    # --- report-internal figures ------------------------------------------
    m = re.search(r"Total On-Hand:\s+(" + MONEY + ")", text)
    d["on_hand"] = money(m.group(1)) if m else None
    m = re.search(r"^Payments.*?Total:\s+[\d.]+\s+(" + MONEY + ")", text, re.S | re.M)
    d["payments_total"] = money(m.group(1)) if m else None
    return d

# ---------------------------------------------------------------------------
# Build journal entry
# ---------------------------------------------------------------------------

def memo_text(profile: dict, date) -> str:
    fmt = profile["memo_date"].replace("{d}", str(date.day))
    return f"{profile['name']} Daily Revenue {date.strftime(fmt)}"


def build_lines(d: dict, profile: dict, journal_no: str) -> list[dict]:
    date = d["date"]
    jd = date.strftime("%d-%m-%Y")
    memo = memo_text(profile, date)
    basis = profile["sales_basis"]
    mode = profile["desc_prefix"]
    sep = profile["desc_sep"]

    raw = []   # (account, debit, credit, prefix, class)

    # tax / tips / discount prefixes are only used by profiles that prefix every line;
    # "as_mapped" (Pinewoods) and "duplicates" (Bears Den) leave them as the plain memo
    def generic(prefix):
        return prefix if mode == "always" else None

    for key, s in d["sales"].items():
        acct, prefix, cls = profile["sales"][key]
        amt = s["gross"] if basis == "gross" else s["net"]
        if amt:
            raw.append((acct, 0, amt, prefix, cls))

    for key in ("GST", "PST", "ALCOHOL"):
        if d["taxes"].get(key):
            raw.append((TAX_MAP[key], 0, d["taxes"][key], generic(TAX_PREFIX[key]), None))

    tips_idx = None
    if d["tips_total"]:
        tips_idx = len(raw)
        raw.append((A_TIPS, 0, d["tips_total"], generic(TIPS_PREFIX), None))

    # Sales-table discounts are already inside the net Amount; Non-Sales "09- DISCOUNT"
    # (whole-check open $ discounts) are not, so they still need a 3050 debit on net basis.
    if basis == "gross" and d["discount_total"]:
        raw.append((A_DISCOUNT, d["discount_total"], 0, generic(DISC_PREFIX), None))
    elif basis == "net" and d["nonsales_discount"]:
        raw.append((A_DISCOUNT, r2(d["nonsales_discount"]), 0, generic(DISC_PREFIX), None))

    order = ["CASH", "MC", "RMPOST", "VISA", "DEBIT", "RC", "GIFT C", "CORP GC"]
    for key in order + [k for k in d["tenders"] if k not in order]:
        if d["tenders"].get(key):
            acct, prefix = profile["tenders"][key]
            raw.append((acct, d["tenders"][key], 0, prefix, None))

    # Tips side is derived, not assumed: put 6044 on whichever side closes the gap.
    if tips_idx is not None:
        dr = r2(sum(x[1] for x in raw)); cr = r2(sum(x[2] for x in raw))
        if abs(dr - cr) > 0.005:
            acct, _, amt, pre, cls = raw[tips_idx]
            if abs(r2((dr + amt) - (cr - amt))) < 0.005:
                raw[tips_idx] = (acct, amt, 0, pre, cls)
                d["flags"].append("6044 Tips posted as a DEBIT this day - that is the side "
                                  "that balances; double-check the tips figure.")

    # description prefixes
    from collections import Counter
    acct_count = Counter(x[0] for x in raw)

    def desc(acct, prefix):
        if mode == "never" or not prefix:
            return memo
        if mode == "duplicates" and acct_count[acct] < 2:
            return memo
        return f"{prefix}{sep}{memo}"

    lines = []
    for acct, debit, credit, prefix, cls in raw:
        lines.append({
            "*JournalNo": journal_no,
            "*JournalDate": jd,
            "Memo": memo,
            "*AccountName": acct,
            "Debits": f"{debit:.2f}" if debit else "",
            "Credits": f"{credit:.2f}" if credit else "",
            "Description": desc(acct, prefix),
            "Name": "",
            "Location": "",
            "Class": cls or profile["default_class"],
        })
    return lines


def totals(lines):
    dr = r2(sum(float(x["Debits"]) for x in lines if x["Debits"]))
    cr = r2(sum(float(x["Credits"]) for x in lines if x["Credits"]))
    return dr, cr

# ---------------------------------------------------------------------------
# Revenue-by-segment rows
# ---------------------------------------------------------------------------

def segment_rows(d: dict, profile: dict, journal_no: str) -> list[dict]:
    iso = d["date"].isoformat()
    out = []

    def row(typ, seg, acct, cls, gross, disc, net):
        out.append({"Date": iso, "Outlet": profile["name"], "JournalNo": journal_no,
                    "Type": typ, "Segment": seg, "Account": acct,
                    "Class": cls or profile["default_class"],
                    "Gross": f"{gross:.2f}", "Discount": f"{disc:.2f}", "Net": f"{net:.2f}"})

    for key, s in d["sales"].items():
        acct, _, cls = profile["sales"][key]
        row("Sales", s["label"], acct, cls, s["gross"], s["disc"], s["net"])
    g = sum(s["gross"] for s in d["sales"].values())
    n = sum(s["net"] for s in d["sales"].values())
    row("Sales Total", "ALL SEGMENTS", "", "", g, d["sales_discount"], n)
    for key in ("GST", "PST", "ALCOHOL"):
        if d["taxes"].get(key):
            row("Tax", key, TAX_MAP[key], None, d["taxes"][key], 0, d["taxes"][key])
    if d["tips_total"]:
        row("Tips", "Non-Cash Tips + Auto Gratuity", A_TIPS, None, d["tips_total"], 0, d["tips_total"])
    for key, amt in d["tenders"].items():
        row("Tender", key, profile["tenders"][key][0], None, amt, 0, amt)
    return out

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(lines, path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\r\n")
        w.writeheader()
        for row in lines:
            w.writerow(row)
    raw = path.read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf", "BOM present"
    assert b"\r\n" in raw, "CRLF line endings missing"
    for ln in raw.decode("utf-8").split("\r\n"):
        if ln:
            assert len(ln.split(",")) == len(CSV_FIELDS), f"bad field count (comma in a field?): {ln}"


def write_segments(seg_rows, per_run_path: Path, ledger_path: Path):
    with open(per_run_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SEGMENT_FIELDS, lineterminator="\r\n")
        w.writeheader(); w.writerows(seg_rows)

    # cumulative ledger: replace any earlier rows for the same Date + Outlet, keep the rest
    existing = []
    if ledger_path.exists():
        with open(ledger_path, newline="", encoding="utf-8") as f:
            existing = [r for r in csv.DictReader(f)
                        if not (r["Date"] == seg_rows[0]["Date"] and r["Outlet"] == seg_rows[0]["Outlet"])]
    merged = sorted(existing + seg_rows, key=lambda r: (r["Date"], r["Outlet"]))
    with open(ledger_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SEGMENT_FIELDS, lineterminator="\r\n")
        w.writeheader(); w.writerows(merged)


def append_log(log_path: Path, journal_no, profile, d, out_file):
    new = not log_path.exists()
    with open(log_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\r\n")
        if new:
            w.writerow(["JournalNo", "Outlet", "Date", "Processed", "File"])
        w.writerow([journal_no, profile["name"], d["date"].isoformat(),
                    datetime.now().strftime("%Y-%m-%d %H:%M"), out_file.name])


def print_summary(d, profile, lines, journal_no, out_path, dry):
    dr, cr = totals(lines)
    date = d["date"]
    net_sales = r2(sum(s["net"] for s in d["sales"].values()))
    gross_sales = r2(sum(s["gross"] for s in d["sales"].values()))
    tax = r2(sum(d["taxes"].values()))
    tenders = r2(sum(d["tenders"].values()))

    print("=" * 70)
    print(f"{journal_no}  -  {profile['name']}  -  {date.strftime('%d %B %Y')}")
    print("=" * 70)
    print("Revenue by segment (net):")
    for key, s in d["sales"].items():
        print(f"   {s['label']:16s} {s['net']:>10.2f}   -> {profile['sales'][key][0]}")
    print(f"   {'Net Sales':16s} {net_sales:>10.2f}   (gross {gross_sales:.2f}, discounts {d['discount_total']:.2f})")
    print(f"   {'Total Tax':16s} {tax:>10.2f}")
    print(f"   {'Total Tips':16s} {d['tips_total']:>10.2f}   (non-cash {d['noncash_tips']:.2f} + auto grat {d['auto_grat']:.2f})")
    print(f"   {'Total Tenders':16s} {tenders:>10.2f}")
    chk = r2(net_sales + tax + d["tips_total"] - (d["nonsales_discount"] if profile["sales_basis"] == "net" else 0))
    print(f"   Check: Net Sales + Tax + Tips = {chk:.2f}  vs  Tenders = {tenders:.2f}  "
          f"-> {'OK' if abs(chk - tenders) < 0.005 else f'GAP {r2(tenders - chk):+.2f}'}")
    print("-" * 70)
    print(f"{'Account':42s} {'Debit':>10s} {'Credit':>10s}  Class")
    print("-" * 70)
    for x in lines:
        print(f"{x['*AccountName'][:42]:42s} {x['Debits']:>10s} {x['Credits']:>10s}  {x['Class']}")
    print("-" * 70)
    print(f"{'TOTAL':42s} {dr:>10.2f} {cr:>10.2f}")
    print(f"Balanced: {'YES' if abs(dr - cr) < 0.005 else 'NO  <<<<<<<<<<'}   Lines: {len(lines)}")
    if out_path and not dry:
        print(f"Written: {out_path}")
    print()
    print("FLAGS / things to look out for:")
    flags = list(d["flags"])
    flags.append(f"Journal number {journal_no} was user-supplied.")
    for k, msg in profile.get("flag_tenders", {}).items():
        if d["tenders"].get(k):
            flags.append(f"{k} ${d['tenders'][k]:.2f}: {msg}")
    for k in ("RMPOST", "CORP GC", "GIFT C"):
        if d["tenders"].get(k):
            flags.append(f"{k} tender ${d['tenders'][k]:.2f} present -> {profile['tenders'][k][0]}.")
    if d["tenders"].get("RMPOST", 0) > 2000:
        flags.append("RMPOST is large - likely an event billed to a master account; check the folio.")
    if profile["sales_basis"] == "net" and d["discount_total"]:
        flags.append(f"Discounts ${d['discount_total']:.2f} on this report - sales posted NET "
                     f"(post-discount); no 3050 line is written for {profile['name']}.")
    if d["taxes"].get("ALCOHOL") and not any(k in d["sales"] for k in ("02 - LIQUOR", "03 - WINE", "04 - BEER")):
        flags.append("Alcohol tax present but no separate liquor/wine/beer sales line - "
                     "alcohol sales are bundled; tax line stays on the default class.")
    if not d["taxes"].get("PST"):
        flags.append("No PST on this report (omitted).")
    if not d["auto_grat"]:
        flags.append("No Auto Gratuity - 6044 is Non-Cash Tips only.")
    if d["on_hand"] is not None:
        if abs(d["on_hand"] - (net_sales + tax)) > 0.005 and \
           abs(d["on_hand"] - (net_sales + tax + d["auto_grat"])) > 0.005:
            flags.append(f"Printed Total On-Hand {d['on_hand']:.2f} != net sales + tax "
                         f"{r2(net_sales + tax):.2f} (nor +auto gratuity). Investigate.")
    for f_ in flags:
        print(f"  - {f_}")
    print()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def out_filename(profile, journal_no, d) -> str:
    date = d["date"]
    return profile["filename"].format(jn=journal_no, outlet=profile["name"].replace(" ", ""),
                                      date=date, iso=date.isoformat(), mon=date.strftime("%b"),
                                      dd=f"{date.day:02d}", yyyy=date.year)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", type=Path, help="Silverware Daily Totals PDF (or pre-extracted .txt)")
    ap.add_argument("journal_no", help="QBO journal number, e.g. JJ3417")
    ap.add_argument("--out", type=Path, default=Path("."), help="output folder (default: current)")
    ap.add_argument("--outlet", choices=sorted(PROFILES), help="force an outlet (must still match Cost Center)")
    ap.add_argument("--dry-run", action="store_true", help="print the entry but write nothing")
    ap.add_argument("--force", action="store_true", help="overwrite an already-delivered CSV")
    ap.add_argument("--segments", action="store_true",
                    help="also write the revenue-by-segment CSV and update revenue_by_segment.csv")
    args = ap.parse_args()

    if not args.report.exists():
        sys.exit(f"ERROR: file not found: {args.report}")
    if not re.fullmatch(r"JJ\d+", args.journal_no):
        sys.exit(f"ERROR: journal number should look like JJ3417, got '{args.journal_no}'")

    text = extract_text(args.report)
    key, cc = detect_profile(text, args.outlet)
    profile = PROFILES[key]
    d = parse_report(text, profile)
    lines = build_lines(d, profile, args.journal_no)
    dr, cr = totals(lines)

    if abs(dr - cr) >= 0.005:
        print_summary(d, profile, lines, args.journal_no, None, True)
        sys.exit(f"ERROR: entry does not balance (Dr {dr:.2f} vs Cr {cr:.2f}). Nothing written. "
                 f"Check the report for a misread figure or a POS rounding/void artifact.")

    out_path = args.out / out_filename(profile, args.journal_no, d)
    seg_path = out_path.with_name(out_path.stem + "_segments.csv")
    if out_path.exists() and not args.dry_run and not args.force:
        sys.exit(f"ERROR: {out_path} already exists. Delivered CSVs are not overwritten silently - "
                 f"fix in QBO, or re-run with --force if you really want a new file.")

    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        write_csv(lines, out_path)
        if args.segments:
            write_segments(segment_rows(d, profile, args.journal_no), seg_path, args.out / SEGMENT_LEDGER)
        append_log(args.out / RUN_LOG, args.journal_no, profile, d, out_path)
    print_summary(d, profile, lines, args.journal_no, out_path, args.dry_run)
    if not args.dry_run and args.segments:
        print(f"Segments: {seg_path}")
        print(f"Ledger:   {args.out / SEGMENT_LEDGER}  (cumulative, all outlets)")


if __name__ == "__main__":
    main()
