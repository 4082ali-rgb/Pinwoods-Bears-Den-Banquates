# Silverware Daily Revenue -> QBO Journal Entry

One script for all three Silverware (Clover POS) outlets at Manning Park Resort:
**Pinewoods**, **Bears Den** and **Banquets**. One "Daily Totals" PDF in, a balanced
QuickBooks Online journal CSV out, plus a revenue-by-segment CSV so you can see, per
date, which segment (Food / Liquor / Wine / Beer / Banquets / ...) the money came from.

The outlet is detected from the report's own `Cost Center:` line. The date comes from
the report's `From Date`. The filename is never trusted.

## Setup (once)

```bash
sudo apt install poppler-utils          # pdftotext (Mac: brew install poppler)
pip install -r requirements.txt         # pdfplumber fallback + pytest
```

## Daily use

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
- `legacy_pinewoods_je.py` - the original Pinewoods-only script, kept for reference.
- `docs/` - the Banquets rules, the Bears Den spec, and the original Pinewoods README.
- `samples/`, `tests/` - fixtures and regression tests.
