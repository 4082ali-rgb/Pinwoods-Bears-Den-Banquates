#!/usr/bin/env python3
"""
run_batch.py  -  drag-and-drop batch runner for silverware_je.py

    inbox/   drop the day's PDFs here (any mix of Pinewoods, Bears Den, Banquets)
    output/  finished CSVs land here, and the PDFs you dropped get moved here too
             once their entry is built - this keeps inbox empty and ready for
             tomorrow

Double-click RUN.bat (Windows) or run `python3 run_batch.py` directly.

What it does, every run:
  1. Reads every PDF (and .txt - a pre-extracted or OCR'd-elsewhere report) in
     inbox/ (falls back to the main folder if inbox is empty - still works if
     you drop reports the old way).
  2. For each one, reads the report's own Cost Center to tell Pinewoods, Bears Den
     and Banquets apart - never guesses from the filename.
  3. Sorts everything by the report's own date, then assigns journal numbers in
     order, starting from the number saved in journal_state.json (or asks you
     for a starting number the first time).
  4. Builds each entry with the exact same rules as silverware_je.py - unbalanced
     or unrecognised reports print STOP: and are left in inbox untouched; nothing
     is written and no journal number is used for them.
  5. Writes each QBO CSV into output/, moves the matching report into output/ too,
     and saves the next journal number after every single entry - so if something
     goes wrong partway through a big drop, everything already built keeps its
     number and nothing gets reused or skipped on the next run.

A problem with one file (a crash while parsing, a full output folder, anything
unexpected) prints STOP: and moves on to the next file rather than losing the
whole run - the file that failed is left in inbox for you to check.

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

JOURNAL_NO_RE = re.compile(r"JJ\d+")


def find_reports():
    INBOX.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    reports = sorted(INBOX.glob("*.pdf")) + sorted(INBOX.glob("*.txt"))
    if reports:
        return reports
    # Fallback: reports dropped straight into the main folder, the old way.
    return sorted(p for p in ROOT.glob("*.pdf") if p.is_file())


def load_next_number():
    if STATE_FILE.exists():
        try:
            saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))["next"]
        except (json.JSONDecodeError, KeyError, OSError) as e:
            print(f"WARNING: could not read {STATE_FILE.name} ({e}) - asking for the number again.")
            saved = None
        if saved and JOURNAL_NO_RE.fullmatch(saved):
            return saved
        elif saved:
            print(f"WARNING: {STATE_FILE.name} has an invalid saved number ('{saved}') - asking again.")

    print()
    print("What journal number should the NEXT entry use?")
    while True:
        raw = input("  Journal number (e.g. JJ3528): ").strip().upper()
        if JOURNAL_NO_RE.fullmatch(raw):
            return raw
        print("  That doesn't look like a journal number (expected e.g. JJ3528). Try again.")


def bump(jn: str) -> str:
    m = re.match(r"([A-Za-z]+)(\d+)", jn)
    prefix, digits = m.group(1), m.group(2)
    return f"{prefix}{int(digits) + 1:0{len(digits)}d}"


def save_next_number(jn: str):
    STATE_FILE.write_text(json.dumps({"next": jn}, indent=2), encoding="utf-8")


def move_to_output(src: Path) -> Path:
    """Move src into output/, adding a numeric suffix if that name is already there
    (e.g. the same report dropped and processed twice) instead of crashing."""
    dest = OUTPUT / src.name
    if dest.exists():
        n = 2
        while (OUTPUT / f"{src.stem}_{n}{src.suffix}").exists():
            n += 1
        dest = OUTPUT / f"{src.stem}_{n}{src.suffix}"
    src.rename(dest)
    return dest


def main():
    reports = find_reports()
    if not reports:
        print("Nothing to do - drop today's PDFs into the 'inbox' folder and run again.")
        return

    # Parse every report first (without a journal number yet) so a drop with
    # several outlets/dates gets processed in date order, not folder order.
    parsed = []
    for report in reports:
        try:
            text = sw.extract_text(report)
            key, cc = sw.detect_profile(text, None)
            profile = sw.PROFILES[key]
            d = sw.parse_report(text, profile)
        except SystemExit as e:
            print(f"STOP: {report.name}: {e}")
            print("      Left in place - nothing written, no journal number used.")
            print()
            continue
        except Exception as e:
            print(f"STOP: {report.name}: unexpected error while reading it - {type(e).__name__}: {e}")
            print("      Left in place - nothing written, no journal number used.")
            print()
            continue
        parsed.append((d["date"], report, key, profile, d))

    if not parsed:
        print("Nothing was built - see the STOP messages above.")
        return

    parsed.sort(key=lambda t: t[0])

    journal_no = load_next_number()
    built = 0
    for date, report, key, profile, d in parsed:
        try:
            lines = sw.build_lines(d, profile, journal_no)
            dr, cr = sw.totals(lines)
            if abs(dr - cr) >= 0.005:
                sw.print_summary(d, profile, lines, journal_no, None, True)
                print(f"STOP: {report.name} does not balance (Dr {dr:.2f} vs Cr {cr:.2f}).")
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
        except Exception as e:
            print(f"STOP: {report.name}: unexpected error while building the entry - "
                 f"{type(e).__name__}: {e}")
            print("      Left in place - nothing written, this journal number was not used.")
            print()
            continue

        sw.print_summary(d, profile, lines, journal_no, out_path, False)
        try:
            moved_to = move_to_output(report)
            print(f"Moved {report.name} -> output/{moved_to.name}")
        except OSError as e:
            print(f"NOTE: entry was written to {out_path.name}, but couldn't move {report.name} "
                 f"into output/ ({e}). Move it there by hand so inbox stays clear.")
        print()

        journal_no = bump(journal_no)
        save_next_number(journal_no)  # save after every entry, not just at the end
        built += 1

    print("=" * 70)
    print(f"{built} of {len(reports)} report(s) built into CSVs in 'output'.")
    print(f"Next journal number: {journal_no}")


if __name__ == "__main__":
    main()
