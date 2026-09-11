#!/usr/bin/env python3
"""
pinewoods_je.py  -  Pinewoods Daily Revenue -> QuickBooks Online Journal Entry CSV

Parses a Silverware "Daily Totals" PDF for the Pinewoods cost centre at
Manning Park Resort and writes a QBO-importable journal entry CSV using the
GL mapping conventions established in Aug 2026.

USAGE
    python3 pinewoods_je.py <report.pdf> <JournalNo> [--out DIR] [--dry-run]

    python3 pinewoods_je.py PW_Aug_31.pdf JJ3417
    python3 pinewoods_je.py PW_Aug_31.pdf JJ3417 --out ./csv
    python3 pinewoods_je.py PW_Aug_31.pdf JJ3417 --dry-run     # print only, no file

The script:
  1. Extracts the report text (pdftotext -layout, falls back to pdfplumber)
  2. Reads the report's own From Date (never trusts the filename)
  3. Pulls Sales (gross), Discounts (Sales table + Non-Sales 09-DISCOUNT),
     Taxes, Non-Cash Tips, Auto Gratuity, and every Payment tender
  4. Maps everything to GL accounts / classes
  5. Proves Debits == Credits before writing anything
  6. Writes  <JournalNo>_Pinewoods_<YYYY-MM-DD>.csv
  7. Prints a summary plus a FLAGS section for anything unusual

Anything unrecognised (a new tender type, a new sales category) STOPS the
script with a clear message so a wrong account never silently gets posted.

REQUIREMENTS
    pdftotext  (poppler-utils)   - preferred
    pdfplumber (pip)             - fallback
"""

import argparse
import csv
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIGURATION  -  edit here if a mapping ever changes
# ---------------------------------------------------------------------------

OUTLET_NAME = "Pinewoods"
COST_CENTER_EXPECTED = "Pinewoods"          # script refuses other outlets
DEFAULT_CLASS = "0020-PINEWOODS"
BANQUET_CLASS = "0101 - BANQUET- FOOD"      # exact QBO spacing

# Sales category (as printed on report)  ->  (GL account, description prefix, class override)
SALES_MAP = {
    "01 - FOOD":     ("3002 Revenue - Food",              None,        None),
    "02 - LIQUOR":   ("3003 Revenue - Liquor",            None,        None),
    "03 - WINE":     ("3004 Revenue - Wine",              None,        None),
    "04 - BEER":     ("3005 Revenue - Beer",              None,        None),
    "05 - N/A BEV":  ("3006 Revenue - Non-Alcoholic",     None,        None),
    "10- MODIFIERS": ("3001 Revenue",                     "Modifers",  None),
    "11-BANQUETS":   ("3031 Revenue - Banquets & Wedding","Banquets",  BANQUET_CLASS),
}

# Tax line (as printed)  ->  GL account
TAX_MAP = {
    "GST":     "2029 GST Charged on Sales",
    "PST":     "2035 PST 7% Charged on Sales",
    "ALCOHOL": "2039 PST 10% Liquor Charged on Sales",
}

# Payment tender (as printed, before any "(...)" suffix)  ->  (GL account, description prefix)
# Debits. RC and Corp GC / GIFT C go to non-bank accounts by design.
TENDER_MAP = {
    "CASH":    ("1002 Petty Cash in safe",                None),
    "MC":      ("1007 Visa / Mstrcrd / Debit Receivable", "Mastercard"),
    "VISA":    ("1007 Visa / Mstrcrd / Debit Receivable", "Visa"),
    "DEBIT":   ("1007 Visa / Mstrcrd / Debit Receivable", "Debit"),
    "RMPOST":  ("1007 Visa / Mstrcrd / Debit Receivable", "RMPOST"),
    "RC":      ("3051 ROOM CHARGE R/C",                   None),
    "CORP GC": ("3023 Revenue - Gift Cards",              "Corp GC"),
    "GIFT C":  ("2005 Gift Certificates",                 "Gift Certificate"),
}

TIPS_ACCOUNT      = "6044 Tips & Gratuities"
DISCOUNT_ACCOUNT  = "3050 Discounts given"

CSV_FIELDS = ["*JournalNo", "*JournalDate", "Memo", "*AccountName",
              "Debits", "Credits", "Description", "Name", "Location", "Class"]

# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------

def extract_text(pdf_path: Path) -> str:
    """pdftotext -layout is the most faithful; fall back to pdfplumber."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, check=True
        )
        if out.stdout.strip():
            return out.stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    try:
        import pdfplumber
    except ImportError:
        sys.exit("ERROR: neither pdftotext nor pdfplumber is available. "
                 "Install poppler-utils or `pip install pdfplumber`.")
    with pdfplumber.open(str(pdf_path)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

MONEY = r"-?\$-?[\d,]+\.\d{2}"   # $ required so the Qnty column is never matched

def money(s: str) -> float:
    """'$1,148.10' / '-$8.00' / '$-8.00' -> float"""
    neg = "-" in s
    val = float(re.sub(r"[^\d.]", "", s))
    return -val if neg else val

def section(text: str, header_regex: str) -> str:
    """
    Return the block of text starting at the line matching header_regex and
    ending just before the next section header (a line that begins at column 0
    with a capitalised word and contains 'Qnty', or 'Total On-Hand', or a page
    break).  Returns '' if header not found.
    """
    m = re.search(header_regex, text, re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    rest = text[start:]
    # next header: a line starting at col 0 (no leading spaces) that has 'Qnty'
    # OR 'Total On-Hand' OR form-feed
    stop = re.search(r"^(?=\S)[A-Za-z][^\n]*\bQnty\b|^\s*Total On-Hand|\f", rest, re.MULTILINE)
    return rest[:stop.start()] if stop else rest

def rows(block: str):
    """Yield (label, [money values]) for each non-blank, non-Total line."""
    for line in block.splitlines():
        if not line.strip():
            continue
        if re.match(r"^\s*Total:", line):
            continue
        amounts = re.findall(MONEY, line)
        # label = everything before the first number-ish token
        label = re.split(r"\s{2,}", line.strip())[0].strip()
        yield label, amounts

# ---------------------------------------------------------------------------
# Core parse
# ---------------------------------------------------------------------------

def parse_report(text: str) -> dict:
    d = {"flags": []}

    # --- date & cost centre --------------------------------------------------
    m = re.search(r"From Date:\s*(\d{4}-\d{2}-\d{2})", text)
    if not m:
        sys.exit("ERROR: could not find 'From Date' in report.")
    d["date"] = datetime.strptime(m.group(1), "%Y-%m-%d").date()

    m2 = re.search(r"To Date:\s*(\d{4}-\d{2}-\d{2})", text)
    if m2 and m2.group(1) != m.group(1):
        d["flags"].append(f"Report spans {m.group(1)} to {m2.group(1)} - "
                          f"multi-day report; JE dated to From Date only.")

    m = re.search(r"Cost Center:\s*(.+)", text)
    cc = m.group(1).strip() if m else "?"
    if cc != COST_CENTER_EXPECTED:
        sys.exit(f"ERROR: this script is for '{COST_CENTER_EXPECTED}' but the "
                 f"report's Cost Center is '{cc}'. Refusing to continue.")

    # --- Sales ---------------------------------------------------------------
    sales_block = section(text, r"^Sales\s+Qnty\s+Gross Amount")
    if not sales_block:
        sys.exit("ERROR: Sales section not found.")
    d["sales"] = {}
    d["sales_discount"] = 0.0
    for label, amts in rows(sales_block):
        if len(amts) < 4:
            continue
        gross, refund, disc, net = (money(a) for a in amts[:4])
        if label not in SALES_MAP:
            sys.exit(f"ERROR: unknown Sales category '{label}' (${gross:.2f}). "
                     f"Add it to SALES_MAP before posting.")
        if refund:
            d["flags"].append(f"Refunds ${refund:.2f} on '{label}' - refunds are "
                              f"not part of the standard mapping; verify treatment.")
        if gross:                       # zero-gross lines are never posted
            d["sales"][label] = gross
        d["sales_discount"] += disc

    # Sales Total line gives the authoritative discount column
    m = re.search(r"^\s*Total:\s+[\d.]+\s+(" + MONEY + r")\s+(" + MONEY + r")\s+(" + MONEY + r")\s+(" + MONEY + r")",
                  sales_block, re.MULTILINE)
    if m:
        d["sales_discount"] = money(m.group(3))

    # --- Non-Sales (09- DISCOUNT) -------------------------------------------
    d["nonsales_discount"] = 0.0
    ns_block = section(text, r"^Non-Sales\s+Qnty")
    if ns_block:
        for label, amts in rows(ns_block):
            if len(amts) >= 4:
                d["nonsales_discount"] += money(amts[2])   # Discounts column
        if d["nonsales_discount"]:
            d["flags"].append(f"Non-Sales discount ${d['nonsales_discount']:.2f} "
                              f"added to Sales-table discount "
                              f"${d['sales_discount']:.2f} -> combined "
                              f"${d['sales_discount']+d['nonsales_discount']:.2f}.")

    d["discount_total"] = round(d["sales_discount"] + d["nonsales_discount"], 2)

    # --- Taxes ---------------------------------------------------------------
    d["taxes"] = {}
    tax_block = section(text, r"^Taxes\s+Qnty")
    for label, amts in rows(tax_block):
        if not amts:
            continue
        key = label.upper()
        if key in TAX_MAP:
            d["taxes"][key] = money(amts[-1])
        else:
            sys.exit(f"ERROR: unknown tax line '{label}'. Add to TAX_MAP.")

    # --- Tips: Non-Cash Tips + Auto Gratuity total --------------------------
    m = re.search(r"Non-Cash Tips\s+[\d.]+\s+(" + MONEY + r")", text)
    d["noncash_tips"] = abs(money(m.group(1))) if m else 0.0

    d["auto_grat"] = 0.0
    ag_block = section(text, r"^Auto Gratuity\s+Qnty")
    if ag_block:
        m = re.search(r"Total:\s+[\d.]+\s+(" + MONEY + r")", ag_block)
        if m:
            d["auto_grat"] = money(m.group(1))
    d["tips_total"] = round(d["noncash_tips"] + d["auto_grat"], 2)

    # --- Payments ------------------------------------------------------------
    d["tenders"] = {}
    pay_block = section(text, r"^Payments\s+Qnty")
    if not pay_block:
        sys.exit("ERROR: Payments section not found.")
    for label, amts in rows(pay_block):
        if not amts or label.lower().startswith("cad foreign") or label.lower().startswith("foreign"):
            continue
        key = re.sub(r"\s*\(.*?\)\s*", "", label).strip().upper()   # 'CASH (0.00CAD)' -> 'CASH'
        if key not in TENDER_MAP:
            sys.exit(f"ERROR: unknown payment tender '{label}' (${money(amts[-1]):.2f}). "
                     f"Confirm the GL account and add it to TENDER_MAP before posting.")
        d["tenders"][key] = money(amts[-1])

    # --- Reconciliation checks (report-internal) ----------------------------
    m = re.search(r"Total On-Hand:\s+(" + MONEY + ")", text)
    d["on_hand"] = money(m.group(1)) if m else None
    m = re.search(r"^Payments.*?Total:\s+[\d.]+\s+(" + MONEY + ")", text, re.S | re.M)
    d["payments_total"] = money(m.group(1)) if m else None

    return d

# ---------------------------------------------------------------------------
# Build journal entry
# ---------------------------------------------------------------------------

def build_lines(d: dict, journal_no: str) -> list[dict]:
    date = d["date"]
    jd = date.strftime("%d-%m-%Y")
    memo = f"{OUTLET_NAME} Daily Revenue {date.strftime('%B')} {date.day} {date.year}"

    def line(account, debit, credit, desc_prefix=None, cls=None):
        return {
            "*JournalNo": journal_no,
            "*JournalDate": jd,
            "Memo": memo,
            "*AccountName": account,
            "Debits": f"{debit:.2f}" if debit else "",
            "Credits": f"{credit:.2f}" if credit else "",
            "Description": f"{desc_prefix}- {memo}" if desc_prefix else memo,
            "Name": "",
            "Location": "",
            "Class": cls or DEFAULT_CLASS,
        }

    L = []
    # Credits - revenue, in report order
    for label, gross in d["sales"].items():
        acct, prefix, cls = SALES_MAP[label]
        L.append(line(acct, 0, gross, prefix, cls))
    # Credits - taxes  (GST, PST, ALCOHOL order)
    for key in ("GST", "PST", "ALCOHOL"):
        if d["taxes"].get(key):
            L.append(line(TAX_MAP[key], 0, d["taxes"][key]))
    # Credit - tips
    if d["tips_total"]:
        L.append(line(TIPS_ACCOUNT, 0, d["tips_total"]))
    # Debit - discounts
    if d["discount_total"]:
        L.append(line(DISCOUNT_ACCOUNT, d["discount_total"], 0))
    # Debits - tenders, in a fixed sensible order
    order = ["CASH", "MC", "RMPOST", "VISA", "DEBIT", "RC", "GIFT C", "CORP GC"]
    for key in order:
        if d["tenders"].get(key):
            acct, prefix = TENDER_MAP[key]
            L.append(line(acct, d["tenders"][key], 0, prefix))
    return L

def totals(lines):
    dr = round(sum(float(x["Debits"]) for x in lines if x["Debits"]), 2)
    cr = round(sum(float(x["Credits"]) for x in lines if x["Credits"]), 2)
    return dr, cr

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_csv(lines, path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:   # no BOM
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\r\n")
        w.writeheader()
        for row in lines:
            w.writerow(row)
    # sanity: every row exactly 10 fields, no internal commas
    with open(path, "rb") as f:
        raw = f.read()
    assert raw[:3] != b"\xef\xbb\xbf", "BOM present"
    for ln in raw.decode("utf-8").split("\r\n"):
        if ln:
            assert len(ln.split(",")) == len(CSV_FIELDS), f"bad field count: {ln}"

def print_summary(d, lines, journal_no, out_path, dry):
    dr, cr = totals(lines)
    date = d["date"]
    print("=" * 66)
    print(f"{journal_no}  -  {OUTLET_NAME}, {date.strftime('%B %d, %Y')}")
    print("=" * 66)
    print(f"{'Account':45s} {'Debit':>10s} {'Credit':>10s}")
    print("-" * 66)
    for x in lines:
        cls = "" if x["Class"] == DEFAULT_CLASS else f"  [{x['Class']}]"
        print(f"{x['*AccountName'][:45]:45s} {x['Debits']:>10s} {x['Credits']:>10s}{cls}")
    print("-" * 66)
    print(f"{'TOTAL':45s} {dr:>10.2f} {cr:>10.2f}")
    print(f"Balanced: {'YES' if abs(dr-cr) < 0.005 else 'NO  <<<<<<<<<<'}")
    print(f"Lines: {len(lines)}")
    if not dry:
        print(f"Written: {out_path}")
    print()
    print("FLAGS / things to look out for:")
    flags = list(d["flags"])
    # standard observations
    if "11-BANQUETS" in d["sales"]:
        flags.append(f"Banquets ${d['sales']['11-BANQUETS']:.2f} posted to 3031 with class "
                     f"'{BANQUET_CLASS}' - reclass manually if QBO rejects that class.")
    for k in ("RMPOST", "CORP GC", "GIFT C"):
        if d["tenders"].get(k):
            flags.append(f"{k} tender ${d['tenders'][k]:.2f} present -> {TENDER_MAP[k][0]}.")
    if d["tenders"].get("RMPOST", 0) > 2000:
        flags.append("RMPOST is large - likely a banquet/event billed to a master account; "
                     "spot-check against the folio.")
    missing = [k for k in ("02 - LIQUOR", "03 - WINE", "05 - N/A BEV") if k not in d["sales"]]
    if missing:
        flags.append(f"No line for {', '.join(missing)} on this report (omitted, not an error).")
    if not d["taxes"].get("PST"):
        flags.append("No PST on this report (omitted).")
    if not d["auto_grat"]:
        flags.append("No Auto Gratuity on this report - 6044 is Non-Cash Tips only.")
    if d["on_hand"] is not None and d["payments_total"] is not None:
        # Total On-Hand already includes Auto Gratuity; add Non-Cash tips only
        expected = round(d["on_hand"] + d["noncash_tips"] - d["nonsales_discount"], 2)
        if abs(expected - d["payments_total"]) > 0.01:
            flags.append(f"Report-internal check: On-Hand + NonCashTips - NonSalesDisc = {expected:.2f} "
                         f"but Payments Total = {d['payments_total']:.2f}. Investigate.")
    if not flags:
        flags.append("None - clean day.")
    for f_ in flags:
        print(f"  - {f_}")
    print()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="Silverware Daily Totals PDF (Pinewoods)")
    ap.add_argument("journal_no", help="QBO journal number, e.g. JJ3417")
    ap.add_argument("--out", type=Path, default=Path("."), help="output folder (default: current)")
    ap.add_argument("--dry-run", action="store_true", help="print the entry but do not write the CSV")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"ERROR: file not found: {args.pdf}")
    if not re.fullmatch(r"JJ\d+", args.journal_no):
        sys.exit(f"ERROR: journal number should look like JJ3417, got '{args.journal_no}'")

    text = extract_text(args.pdf)
    d = parse_report(text)
    lines = build_lines(d, args.journal_no)
    dr, cr = totals(lines)
    if abs(dr - cr) >= 0.005:
        print_summary(d, lines, args.journal_no, None, True)
        sys.exit(f"ERROR: entry does not balance (Dr {dr:.2f} vs Cr {cr:.2f}). Nothing written.")

    out_path = args.out / f"{args.journal_no}_{OUTLET_NAME}_{d['date'].isoformat()}.csv"
    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        write_csv(lines, out_path)
    print_summary(d, lines, args.journal_no, out_path, args.dry_run)

if __name__ == "__main__":
    main()
