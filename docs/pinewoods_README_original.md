# Pinewoods Daily Revenue -> QBO Journal Entry

One script, one PDF in, one QBO-ready CSV out.

## Setup (once)

```bash
sudo apt install poppler-utils      # gives you pdftotext (Mac: brew install poppler)
pip install pdfplumber              # optional fallback, only needed if pdftotext is missing
```

## Daily use

```bash
python3 pinewoods_je.py <report.pdf> <JournalNo>
```

Examples:

```bash
python3 pinewoods_je.py PW_Aug_31.pdf JJ3417
python3 pinewoods_je.py PW_Aug_31.pdf JJ3417 --out ./csv     # save into a folder
python3 pinewoods_je.py PW_Aug_31.pdf JJ3417 --dry-run       # preview only, no file written
```

Output file: `JJ3417_Pinewoods_2026-08-31.csv` (date comes from the report itself, never the filename).

## Batch a whole folder

```bash
n=3417
for f in ./pdfs/*.pdf; do
  python3 pinewoods_je.py "$f" "JJ$n" --out ./csv && n=$((n+1))
done
```
Only use this if the journal numbers are truly sequential for that batch.

## What it does

1. Reads the report's own **From Date** and **Cost Center** (refuses anything that isn't Pinewoods).
2. Pulls Sales (gross), Taxes, Non-Cash Tips, Auto Gratuity, all Payment tenders.
3. Discounts = Sales-table discount + Non-Sales "09- DISCOUNT" (when present).
4. Maps to GL accounts per the rules below, builds the entry, **proves Dr = Cr**, and only then writes the CSV.
5. Prints a summary and a **FLAGS** list of anything worth a second look.

If it meets a sales category or tender it has never seen, it **stops** and tells you, so nothing ever posts to the wrong account silently. Add the new mapping to the config block at the top of the script and re-run.

## GL mapping (edit at top of script)

| Report line        | Account                                | Dr/Cr | Class                  |
|--------------------|----------------------------------------|-------|------------------------|
| 01 - FOOD          | 3002 Revenue - Food                    | Cr    | 0020-PINEWOODS         |
| 02 - LIQUOR        | 3003 Revenue - Liquor                  | Cr    | 0020-PINEWOODS         |
| 03 - WINE          | 3004 Revenue - Wine                    | Cr    | 0020-PINEWOODS         |
| 04 - BEER          | 3005 Revenue - Beer                    | Cr    | 0020-PINEWOODS         |
| 05 - N/A BEV       | 3006 Revenue - Non-Alcoholic           | Cr    | 0020-PINEWOODS         |
| 10- MODIFIERS      | 3001 Revenue                           | Cr    | 0020-PINEWOODS         |
| 11-BANQUETS        | 3031 Revenue - Banquets & Wedding      | Cr    | **0101 - BANQUET- FOOD** |
| GST                | 2029 GST Charged on Sales              | Cr    |                        |
| PST                | 2035 PST 7% Charged on Sales           | Cr    |                        |
| ALCOHOL            | 2039 PST 10% Liquor Charged on Sales   | Cr    |                        |
| Non-Cash Tips + Auto Gratuity | 6044 Tips & Gratuities      | Cr    |                        |
| Discounts (combined) | 3050 Discounts given                 | Dr    |                        |
| CASH               | 1002 Petty Cash in safe                | Dr    |                        |
| MC / VISA / DEBIT / RMPOST | 1007 Visa / Mstrcrd / Debit Receivable | Dr (one line each) |         |
| RC                 | 3051 ROOM CHARGE R/C                   | Dr    |                        |
| Corp GC            | 3023 Revenue - Gift Cards              | Dr    |                        |
| GIFT C             | 2005 Gift Certificates                 | Dr    |                        |

Zero-amount lines are never written.

## Tested

Regression-tested against all 33 Pinewoods reports from 29 Jul - 30 Aug 2026; every entry
reproduced the hand-verified balanced total exactly.
