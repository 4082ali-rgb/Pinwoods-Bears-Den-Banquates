# Silverware Daily Revenue -> QBO Journal Entry

One script for all three Silverware (Clover POS) outlets at Manning Park Resort:
**Pinewoods**, **Bears Den** and **Banquets**. One "Daily Totals" PDF in, a balanced
QuickBooks Online journal CSV out, plus a revenue-by-segment CSV so you can see, per
date, which segment (Food / Liquor / Wine / Beer / Banquets / ...) the money came from.

The outlet is detected from the report's own `Cost Center:` line. The date comes from
the report's `From Date`. The filename is never trusted.

## Setup (once)

**Windows**: install [Python](https://www.python.org/downloads/) - on the first setup screen,
tick "Add python.exe to PATH" before clicking Install. Then double-click **SETUP.bat** in this
folder. It installs everything this needs, creates the `inbox`/`output` folders, and tells you
plainly whether OCR (only needed for scanned PDFs) is ready or needs one more step. Safe to
run again any time.

**Mac/Linux**:

```bash
sudo apt install poppler-utils          # pdftotext (Mac: brew install poppler)
python3 setup.py                        # installs requirements.txt, creates inbox/output
```

### If a report is a scanned/raster PDF (no text layer)

Most Silverware exports have a real text layer and just work. A minority - usually a photo or
a scan of a printed report - don't, and `pdftotext`/`pdfplumber` come back empty. Two ways to
handle that one file:

1. **Install OCR once, and it's automatic from then on.** `pip install pytesseract pdf2image`
   (already listed in `requirements.txt`), plus the Tesseract OCR engine itself:
   - Windows: install from the [UB-Mannheim Tesseract build](https://github.com/UB-Mannheim/tesseract/wiki)
     and [poppler for Windows](https://github.com/oschwartz10612/poppler-windows/releases/)
     (pdf2image needs poppler too), then add both install folders to your PATH and restart
     the Command Prompt / re-run RUN.bat.
   - Mac: `brew install tesseract poppler`
   - Linux: `sudo apt install tesseract-ocr poppler-utils`

   Once installed, RUN.bat and `silverware_je.py` OCR scanned PDFs automatically - nothing
   else changes.

2. **No install, one-off.** Drop a pre-extracted `.txt` file into `inbox` instead of the PDF
   (the batch runner and `silverware_je.py` both accept plain text with the same layout as the
   report). If you don't have a way to OCR it yourself, share the PDF and it can be extracted
   for you and handed back as a `.txt` to drop in.

## Daily use

### Offline, no typing - drop and double-click (Windows)

For running this without typing commands each day:

- **inbox** - where you drop the day's PDFs.
- **output** - where the finished CSV shows up, and where the PDFs you dropped get moved
  to automatically once the entry is built. This keeps `inbox` empty and ready for tomorrow.

The routine:

1. Download the PDFs into the `inbox` folder.
2. Double-click **RUN.bat**.
3. First time, it asks for the journal number. After that it counts up by itself.
4. Open `output` and import the CSV(s) into QuickBooks.

A drop can mix Pinewoods, Bears Den and Banquets PDFs and any dates - each one is matched
to its outlet by the report's own Cost Center, sorted into date order, and given consecutive
journal numbers. Nothing is typed.

If a report is unbalanced, has an unrecognised category, or is the wrong outlet, RUN.bat
prints `STOP:` for that file, leaves it in `inbox` untouched, and does not use up a journal
number for it - fix the report or the mapping and run again.

If you ever drop PDFs straight into the main folder instead of `inbox`, that still works too
- it's a fallback, not a requirement.

#### RESET JOURNAL NUMBER.bat

If the journal number sequence needs to start fresh (you skipped days, or the count got out
of sync with QuickBooks), double-click **RESET JOURNAL NUMBER.bat**. It asks you to type the
word `YES` before it clears anything, so an accidental double-click can't wipe the journal
number by mistake. After a reset, the next RUN asks you for a number again instead of guessing.

#### SET JOURNAL NUMBER.bat

Type a number, press Enter - RUN will use that number next.

#### ADD ACCOUNT.bat

When a report shows a sales category or payment tender that's never appeared before, double-
click **ADD ACCOUNT.bat** instead of editing `silverware_je.py`. It asks which outlet, the
label as printed on the report, the QBO account, and an optional description prefix and class
override, then saves it to `extra_accounts.json`. Both `RUN.bat` and running
`silverware_je.py` directly pick it up automatically on the next run.

None of this changes the accounting rules, GL mappings, balance checks, or CSV format - it's
only about where files live and how the journal number is tracked. An unbalanced or
unrecognised report still stops with `STOP:` and nothing is written, same as always.

On Mac/Linux, run `python3 run_batch.py`, `python3 reset_journal_number.py`,
`python3 set_journal_number.py`, or `python3 add_account.py` directly instead of the `.bat`
files.

```bash
python3 silverware_je.py <report.pdf> <JournalNo> [--out DIR] [--dry-run]
```

```bash
python3 silverware_je.py Bears_Den_Aug_28.pdf JJ3382 --out ./csv
python3 silverware_je.py Banquets_Aug_15.pdf  JJ3431 --out ./csv
python3 silverware_je.py PW_Aug_31.pdf        JJ3417 --out ./csv --dry-run   # preview only
python3 silverware_je.py scanned_report.txt   JJ3440 --out ./csv             # OCR'd text works too
python3 silverware_je.py PW_Sep_02.pdf        JJ3494 --out ./csv --segments  # also write segment CSVs
```

The journal number is always supplied by you (the outlets share one QBO sequence, so
the script never guesses). `--outlet pinewoods|bearsden|banquets` only double-checks
the detected outlet; it will not override a mismatching Cost Center.

### What you get in `--out`

| File | What it is |
|---|---|
| `JJ3417_Pinewoods_2026-08-31.csv` / `JJ3382_BearsDen_Aug28.csv` / `Banquets_JE_Aug15_2026.csv` | The QBO import file (one per day, CRLF, no BOM, no commas in text) |
| `..._segments.csv` (only with `--segments`) | That day's revenue by segment: Date, Outlet, JournalNo, Type, Segment, Account, Class, Gross, Discount, Net |
| `revenue_by_segment.csv` (only with `--segments`) | Cumulative version of the above across every run and outlet. Open in Excel and pivot on Date x Segment. Re-running a day replaces that day's rows, never duplicates them |
| `silverware_log.csv` | JournalNo, Outlet, Date, when it was processed, file written |

Segment rows have `Type` = `Sales` (one per category), `Sales Total`, `Tax`, `Tips`, `Tender`.
Filter `Type = Sales` to see where revenue comes from.

### What the terminal shows every run

1. Revenue by segment and the balancing check (Net Sales + Tax + Tips vs Tenders)
2. The full entry, account by account, with its class, and `Balanced: YES/NO`
3. A **FLAGS** list: first-time tenders, missing categories, bundled alcohol tax,
   discounts, RC on Bears Den, anything worth a second look

## Safety rails

- **Unbalanced = nothing written.** The math is printed so you can find the misread digit
  or the POS rounding artifact. No fictitious plug line is ever added.
- **Unknown sales category / tender / tax line = stop.** Add it to the outlet's profile at
  the top of `silverware_je.py` and re-run.
- **Wrong Cost Center = stop.** A file called `Bears_Bite` that is really a Bears Den report
  is handled correctly; a report for an unknown outlet is refused.
- **No silent overwrite.** A CSV that already exists is not regenerated unless you pass
  `--force` (delivered files get corrected in QBO, per the standing rule).
- **A problem with one file never loses the rest of the batch.** RUN.bat isolates every
  report: an unbalanced entry, an unrecognised category, or an unexpected error prints `STOP:`
  and leaves that one file in `inbox`, and moves on to the next. The journal number is saved
  after every successful entry, not just at the end, so a crash partway through never causes
  a number to be reused or skipped on the next run.
- `$0.00` lines are never written. Each card tender is its own line even though they
  share account 1007.

## Outlet rules (from the specs in `docs/`)

| | Pinewoods | Bears Den | Banquets |
|---|---|---|---|
| Class | `0020-PINEWOODS` on every line (11-BANQUETS included) | `0092-BEARS DEN` on every line (11-BANQUETS included) | `0101 - BANQUET- FOOD`; Liquor/Wine/Beer sales -> `0102 - BANQUET LIQUOR` (tax lines stay on 0101) |
| Sales basis | Net Amount (discounts informational, flagged) | Net Amount (discounts informational) | Net Amount |
| RC tender | `3051 ROOM CHARGE R/C` | `1007 ...` and flagged (no confirmed account yet) | `3051 ROOM CHARGE R/C` |
| Memo | `Pinewoods Daily Revenue August 31 2026` | `Bears Den Daily Revenue August 28 2026` | `Banquets Daily Revenue 15 August 2026` |
| Description prefix | Mapped lines only (Mastercard-, Visa-, Debit-, Modifers-) | Only when an account repeats that day (Modifiers-/Pool Table-, MC-/Visa-/Debit-) | Every line (`RC - `, `Liquor - `, `GST - ` ...) |
| Tips | Non-Cash Tips + Auto Gratuity in ONE `6044` line, side derived from the balance | same | same |

All outlets post the net **Amount** column (post-discount), never Gross, so no
`3050 Discounts given` line is written. Discounts are still shown in the segment CSV and
flagged in the terminal. To go back to gross + 3050 for an outlet, set its `sales_basis`
to `"gross"` in the profile.

## Scanned / raster PDFs

`pdftotext` and `pdfplumber` return nothing for scanned reports. The script then tries
OCR if `tesseract` + `pytesseract` + `pdf2image` are installed; otherwise OCR the
report elsewhere and pass the resulting `.txt` file instead of the PDF.

## Batch a folder

```bash
n=3417
for f in ./pdfs/*.pdf; do
  python3 silverware_je.py "$f" "JJ$n" --out ./csv && n=$((n+1))
done
```
Only when the journal numbers are truly sequential for that batch.

## Tests

```bash
python3 -m pytest -q tests
```
Runs every sample in `samples/` (text fixtures in pdftotext layout) and checks balance,
classes, prefixes, the unknown-tender / unbalanced / wrong-outlet stops, and the ledger upsert.

## Files

- `silverware_je.py` - the tool. Outlet profiles (account + class maps) are at the top.
- `setup.py` / `SETUP.bat` - one-time (or run-anytime) setup: installs requirements, creates
  `inbox`/`output`, reports whether OCR is ready.
- `run_batch.py` / `RUN.bat` - drag-and-drop batch runner: processes everything in `inbox`,
  auto-increments the journal number, moves finished reports into `output`. A problem with one
  file (unbalanced, unrecognised, a crash) prints `STOP:` and leaves that file in `inbox` -
  it does not stop the rest of the batch, and the journal number is saved after every entry
  so nothing gets lost or reused if something goes wrong partway through.
- `reset_journal_number.py` / `RESET JOURNAL NUMBER.bat` - clears the saved journal number.
- `set_journal_number.py` / `SET JOURNAL NUMBER.bat` - sets the next journal number directly.
- `add_account.py` / `ADD ACCOUNT.bat` - adds a new sales category or tender to
  `extra_accounts.json` without editing `silverware_je.py`.
- `journal_state.json` - saved next journal number (not committed - personal/local).
- `extra_accounts.json` - categories/tenders added via ADD ACCOUNT, merged into the outlet
  profiles automatically on every run.
- `legacy_pinewoods_je.py` - the original Pinewoods-only script, kept for reference.
- `docs/` - the Banquets rules, the Bears Den spec, and the original Pinewoods README.
- `samples/`, `tests/` - fixtures and regression tests.
