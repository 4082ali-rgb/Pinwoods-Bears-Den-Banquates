#!/usr/bin/env python3
"""
run_batch.py  -  drag-and-drop batch runner for silverware_je.py

    inbox/   drop the day's PDFs here (any mix of Pinewoods, Bears Den, Banquets)
    output/  finished CSVs land here, and the PDFs you dropped get moved here too
             once their entry is built - this keeps inbox empty and ready for
             tomorrow

Double-click RUN.bat (Windows) or run `python3 run_batch.py` directly.

What it does, every run:
  1. Reads every PDF in inbox/ (falls back to the main folder if inbox is empty -
     still works if you drop PDFs the old way).
  2. For each one, reads the report's own Cost Center to tell Pinewoods, Bears Den
     and Banquets apart - never guesses from the filename.
  3. Sorts everything by the report's own date, then assigns journal numbers in
     order, starting from the number saved in journal_state.json (or asks you
     for a starting number the first time).
  4. Builds each entry with the exact same rules as silverware_je.py - unbalanced
     or unrecognised reports print STOP: and are left in inbox untouched; nothing
     is written and no journal number is used for them.
  5. Writes each QBO CSV into output/, moves the matching PDF into output/ too,
     and saves the next journal number for the next run.

Nothing here changes the accounting rules, GL mappings, balance checks or CSV
format - only where files live and how the journal number is tracked.
"""
import json
import re
import sys
from pathlib import Path

import silverware_je as sw

ROOT = Path(__file__).resolve().parent
INBOX = ROOT / "inbox"
OUTPUT = ROOT / "output"
STATE_FILE = ROOT / "journal_state.json"


def find_pdfs():
    INBOX.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    pdfs = sorted(INBOX.glob("*.pdf"))
    if pdfs:
        return pdfs
    # Fallback: PDFs dropped straight into the main folder, the old way.
    return sorted(p for p in ROOT.glob("*.pdf") if p.is_file())


def load_next_number():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))["next"]
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    print()
    print("First run - what journal number should the NEXT entry use?")
    while True:
        raw = input("  Journal number (e.g. JJ3528): ").strip().upper()
        if re.fullmatch(r"JJ\d+", raw):
            return raw
        print("  That doesn't look like a journal number (expected e.g. JJ3528). Try again.")


def bump(jn: str) -> str:
    m = re.match(r"([A-Za-z]+)(\d+)", jn)
    prefix, digits = m.group(1), m.group(2)
    return f"{prefix}{int(digits) + 1:0{len(digits)}d}"


def save_next_number(jn: str):
    STATE_FILE.write_text(json.dumps({"next": jn}, indent=2), encoding="utf-8")


def main():
    pdfs = find_pdfs()
    if not pdfs:
        print("Nothing to do - drop today's PDFs into the 'inbox' folder and run again.")
        return

    # Parse every report first (without a journal number yet) so a drop with
    # several outlets/dates gets processed in date order, not folder order.
    parsed = []
    for pdf in pdfs:
        try:
            text = sw.extract_text(pdf)
            key, cc = sw.detect_profile(text, None)
            profile = sw.PROFILES[key]
            d = sw.parse_report(text, profile)
        except SystemExit as e:
            print(f"STOP: {pdf.name}: {e}")
            print("      Left in place - nothing written, no journal number used.")
            print()
            continue
        parsed.append((d["date"], pdf, key, profile, d))

    if not parsed:
        print("Nothing was built - see the STOP messages above.")
        return

    parsed.sort(key=lambda t: t[0])

    journal_no = load_next_number()
    built = 0
    for date, pdf, key, profile, d in parsed:
        lines = sw.build_lines(d, profile, journal_no)
        dr, cr = sw.totals(lines)
        if abs(dr - cr) >= 0.005:
            sw.print_summary(d, profile, lines, journal_no, None, True)
            print(f"STOP: {pdf.name} does not balance (Dr {dr:.2f} vs Cr {cr:.2f}).")
            print("      Left in place - nothing written, this journal number was not used.")
            print()
            continue

        out_path = OUTPUT / sw.out_filename(profile, journal_no, d)
        if out_path.exists():
            print(f"STOP: {out_path.name} already exists in output.")
            print("      Not overwritten - move or rename it first if this is really a new entry.")
            print()
            continue

        sw.write_csv(lines, out_path)
        sw.print_summary(d, profile, lines, journal_no, out_path, False)
        pdf.rename(OUTPUT / pdf.name)
        print(f"Moved {pdf.name} -> output/")
        print()
        journal_no = bump(journal_no)
        built += 1

    save_next_number(journal_no)
    print("=" * 70)
    print(f"{built} of {len(pdfs)} PDF(s) built into CSVs in 'output'.")
    print(f"Next journal number: {journal_no}")


if __name__ == "__main__":
    main()
