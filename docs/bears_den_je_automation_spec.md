# Bears Den Daily Revenue JE Automation — Build Spec

## Goal
Given a Bears Den (Silverware/Clover POS) daily revenue report PDF, produce a
balanced QuickBooks Online (QBO) journal-entry import CSV automatically —
no manual re-derivation of the math each day.

## Input
One PDF per day, e.g. `Bears_Den_Aug_28.pdf`. Structure varies slightly day
to day (some days have Corp GC, RC, Auto Gratuity, Pool Table, etc.) so the
parser must be tolerant of missing/extra sections rather than assuming a
fixed layout.

**Do not trust the filename for the date or the outlet.** Always parse the
actual "From Date"/"To Date" and "Cost Center" fields from the PDF body.
If the Cost Center in the PDF doesn't match "Bears Den", stop and flag it
rather than silently proceeding (this has happened — a file named
"Bears_Bite_Aug_30.pdf" turned out to be a Bears Den report).

### Sections to extract
- **From Date / To Date** (should be same day) → journal date, format DD-MM-YYYY
- **Payments** table → tender lines (Cash, MC, Visa, Debit, Corp GC, RC, and
  any other tender type that appears — do not hardcode an exhaustive list,
  extract whatever rows exist under "Payments")
- **Taxes** table → GST, PST (7%), ALCOHOL (= PST Liquor Tax 10%) amounts
- **Sales** table → category rows with **net Amount column** (post-refund,
  post-discount), not the Gross column. Category set varies (Food, Liquor,
  Wine, Beer, N/A Bev, Modifiers, Pool Table, and any other row that
  appears — treat the category list as dynamic, not fixed)
- **Net Cash Owing** section → "Non-Cash Tips" and, when present, "Auto
  Gratuity" (both usually shown as negative numbers meaning money owed out)
- **Voids** / **Cancellations** / **Discounts** tables → informational only,
  do not post

## GL mapping table (Bears Den, class 0092-BEARS DEN)

| Source line | QBO Account | Dr/Cr |
|---|---|---|
| Cash tender | 1002 Petty Cash in safe | Debit |
| MC tender | 1007 Visa / Mstrcrd / Debit Receivable | Debit |
| Visa tender | 1007 Visa / Mstrcrd / Debit Receivable | Debit |
| Debit tender | 1007 Visa / Mstrcrd / Debit Receivable | Debit |
| Corp GC tender | 3023 Revenue - Gift Cards | Debit |
| RC tender (Resort Credit) | 1007 Visa / Mstrcrd / Debit Receivable | Debit — **flag for confirmation**, no confirmed dedicated account seen yet |
| Any other/new tender type | — | **Do not guess. Flag and hold that line out of the CSV until confirmed** |
| Food sales (net) | 3002 Revenue - Food | Credit |
| Liquor sales (net) | 3003 Revenue - Liquor | Credit |
| Wine sales (net) | 3004 Revenue - Wine | Credit |
| Beer sales (net) | 3005 Revenue - Beer | Credit |
| N/A Bev sales (net) | 3006 Revenue - Non-Alcoholic | Credit |
| Modifiers sales (net) | 3001 Revenue | Credit |
| Pool Table / other misc sales categories (net) | 3001 Revenue | Credit |
| GST (Taxes table) | 2029 GST Charged on Sales | Credit |
| PST 7% (Taxes table, labeled "PST") | 2035 PST 7% Charged on Sales | Credit |
| ALCOHOL (Taxes table) | 2039 PST 10% Liquor Charged on Sales | Credit |
| Non-Cash Tips + Auto Gratuity (combined) | 6044 Tips & Gratuities | Credit — **known interim/incorrect treatment, kept intentionally per standing instruction until a batch correction is done; do not "fix" this on your own** |

Only post a sales category line if that category actually appears in the
report for that day (e.g., a day with no Liquor sales gets no 3003 line).

## Balancing logic (this is the core validation, not optional)

1. Sum all tender/payment amounts from the Payments table → **Total Tenders**
2. Sum all net sales category amounts → **Net Sales**
3. Sum GST + PST(7%) + ALCOHOL from Taxes table → **Total Tax**
4. Sum Non-Cash Tips + Auto Gratuity (absolute values) → **Total Tips**
5. Check: `Net Sales + Total Tax + Total Tips == Total Tenders` (within $0.01)
6. If it balances: tips post as a **credit** to 6044 (this is the pattern
   observed every day so far — tender totals include tip dollars collected
   via card, so crediting 6044 is what brings debits and credits to equal).
   Do not assume this sign is fixed forever — always derive it from whether
   debits or credits are short after building lines 1–5, and set the 6044
   entry to whichever side makes the JE balance. If neither a straight debit
   nor credit to 6044 alone closes the gap exactly, stop and flag rather
   than plug a rounding fudge.
7. If step 5 does not balance even after correctly assigning tips, **do not
   output a CSV**. Print the itemized math (each subtotal) so the user can
   see exactly where the gap is, and ask for the missing report section or
   confirmation, per the existing "never deliver an unbalanced CSV" rule.

## CSV output requirements (QBO import format)

- Columns exactly: `*JournalNo,*JournalDate,Memo,*AccountName,Debits,Credits,Description,Name,Location,Class`
- `*JournalNo`, `*JournalDate`, and `Memo` repeat on every row
- `*JournalDate` format: `DD-MM-YYYY`
- `Memo` format: `Bears Den Daily Revenue [Month] [DD] [YYYY]` (e.g. `Bears Den Daily Revenue August 28 2026`)
- `Description` per line:
  - Plain memo text on lines with a unique account number that day
  - Add a short prefix (tender name, sales category name) only when the
    same account number appears on more than one line that day (e.g. two
    3001 Revenue lines for "Modifiers" and "Pool Table" both need prefixes
    to stay distinguishable — `Modifiers-Bears Den Daily Revenue...` /
    `Pool Table-Bears Den Daily Revenue...`)
  - No commas anywhere in Description — reword instead of relying on CSV
    quoting
- `Class` = `0092-BEARS DEN` on every line, no exceptions, never blank
- `Name`, `Location` = blank
- Account names must exactly match QBO's Chart of Accounts spacing (see
  mapping table above for exact strings to use)
- **Line endings must be CRLF (`\r\n`)**, not LF — this is a hard QBO import
  requirement, verify explicitly before writing the file, don't rely on the
  OS default
- Filename convention: `[JournalNo]_BearsDen_[Month][DD].csv` (e.g.
  `JJ3382_BearsDen_Aug28.csv`)

## Journal number handling

- Bears Den does not strictly auto-increment — it shares a numeric pool
  across all outlets, so gaps are normal and expected.
- Default behavior: if the user supplies the journal number for this run
  (as they have been doing), use it as given — don't second-guess it.
- If no journal number is supplied: do not guess one. Ask the user for it.
- Track the last-used Bears Den journal number and date processed in a
  simple local log file (e.g. `bears_den_log.csv` with columns
  JournalNo, Date, Processed) so gaps and sequence are visible across runs,
  but this log is informational only — it never substitutes for the user
  providing/confirming the number.

## Output to the user, every run

After generating (or failing to generate) a CSV, always print:
1. The balancing check — each subtotal (Net Sales, Total Tax, Total Tips,
   Total Tenders) and confirmation they match, or the exact mismatch amount
2. A "Flags" section listing anything that required a judgment call:
   - New/unrecognized tender type encountered
   - New/unrecognized sales category encountered (and what it was mapped to)
   - Cost Center in the PDF not matching "Bears Den"
   - Any account line held out of the CSV due to inability to map it
   - Journal number used, and whether it was user-supplied or inferred

## Explicit non-goals / do not do

- Do not silently invent a GL account for something new — flag and exclude
  it from the CSV, never guess silently
- Do not "fix" the 6044 tips treatment to the theoretically correct Tips
  Payable liability treatment — that's a planned separate batch correction,
  not something to change per-entry
- Do not batch multiple days into one CSV — one report in, one CSV out
- Do not regenerate/overwrite a CSV that's already been delivered for
  corrections — those get fixed manually in QBO; only regenerate for a new
  report or on explicit request
- Do not assume PDF layout is fixed — extract sections by label matching,
  not by fixed row/column position, since new sales categories and tender
  types have already appeared partway through the month

## Suggested implementation approach

- Python script, one file per invocation: `bears_den_je.py <path_to_pdf> [journal_number]`
- Use `pdftotext -layout` or a PDF text-extraction library (e.g. `pdfplumber`)
  to pull raw text, then parse section-by-section using the table headers
  ("Payments", "Taxes", "Sales", "Net Cash Owing") as anchors
- Keep the GL mapping table above as a Python dict at the top of the script
  so it's easy for the user to edit/extend when new categories appear,
  rather than buried in parsing logic
- Emit the balancing check and flags to stdout before writing the CSV so
  the user sees it in the terminal even if they don't open the file
