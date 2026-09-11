# Banquets Daily Revenue — Journal Entry Rules

Spec for building a semi-automated tool that converts a Banquets "Daily Totals" PDF
report (from the POS/Clover system) into a QuickBooks Online (QBO) journal entry
CSV import file. Manning Park Resort, Cost Center: Banquets.

---

## 1. Input

A PDF report titled "Manning Park Resort — Daily Totals", with `Cost Center: Banquets`.
It may be text-based or a raster/scanned PDF (no text layer) — the tool must handle
both. For raster PDFs, extract via OCR or rasterize + vision, since `pdftotext` will
return empty output.

Relevant sections to parse, by heading:

- **Sales** — rows like `02 - LIQUOR`, `03 - WINE`, `04 - BEER`, `10- MODIFIERS`,
  `11-BANQUETS`, occasionally `01 - FOOD` or `05 - N/A BEV`. Use the **Amount**
  column (net of discounts), not Gross Amount, unless a Discounts value is present
  (see §4).
- **Taxes** — `GST`, `PST` (7%), `ALCOHOL` (this is PST 10% Liquor tax).
- **Payments** — `RC` (Room Charge), `CASH (0.00CAD)`, `MC`, `VISA`, `DEBIT`,
  `Corp GC`. Use exact dollar amounts.
- **Net Cash Owing** — `Non-Cash Tips` and/or `Auto Gratuity` (both negative
  numbers on the report; use absolute value).
- **Total On-Hand** — this is the balance-check target: it should equal
  `sales (net) + taxes`, and separately equal `tenders total − tips − auto gratuity`.
- **Auto Gratuity** section (separate from Net Cash Owing) — may show the same
  gratuity figure broken out by %, e.g. `18%` or `16%`. Use this to corroborate
  the Net Cash Owing figure, they should match.

## 2. Balance validation (always run before emitting a CSV)

Compute both of the following and confirm they're equal to the cent:

```
sales_total = sum(all Sales "Amount" column values present)
tax_total   = sum(GST + PST + ALCOHOL, whichever are present)
credit_side = sales_total + tax_total

tenders_total = sum(RC + CASH + MC + VISA + DEBIT + Corp GC, whichever present)
tips_total    = Non-Cash Tips + Auto Gratuity (whichever present, abs value)
debit_side    = tenders_total  # (tips are NOT part of debit_side separately —
                                #  they're already inside tenders/RC as collected
                                #  cash, then carved OUT as a credit line)

debit_side should equal: credit_side + tips_total
```

Equivalently: `tenders_total − tips_total == sales_total + tax_total == Total On-Hand`
(Total On-Hand as printed should match this; if it's off by exactly the Auto
Gratuity amount, that's expected — Total On-Hand sometimes includes gratuity as
physical cash in-hand. Trust the sales+tax = tenders−tips identity over the
printed Total On-Hand line if they disagree by exactly the gratuity amount.)

If debit total ≠ credit total after building all lines: **stop, do not emit the
CSV**, and report the discrepancy with all extracted figures shown, so the user
can check the source PDF for a misread digit or a genuine reporting anomaly
(this has happened at least once — a $2.00 unexplained gap on a report where
all individually-verified figures were correct; in that case, flag it rather
than force a fictitious balancing line).

## 3. GL account mapping (CONFIRMED against real posted QBO entries)

| POS category / report line       | QBO Account                                   | Dr/Cr side |
|-----------------------------------|------------------------------------------------|------------|
| RC (Room Charge)                  | `3051 ROOM CHARGE R/C`                         | Debit      |
| CASH                               | `1002 Petty Cash in safe`                      | Debit      |
| MC (Mastercard)                    | `1007 Visa / Mstrcrd / Debit Receivable`       | Debit      |
| VISA                                | `1007 Visa / Mstrcrd / Debit Receivable`       | Debit      |
| DEBIT                               | `1007 Visa / Mstrcrd / Debit Receivable`       | Debit      |
| Corp GC                            | `3023 Revenue - Gift Cards`                    | Debit      |
| 01 - FOOD                          | `3002 Revenue - Food`                          | Credit     |
| 02 - LIQUOR                        | `3003 Revenue - Liquor`                        | Credit     |
| 03 - WINE                          | `3004 Revenue - Wine`                          | Credit     |
| 04 - BEER                          | `3005 Revenue - Beer`                          | Credit     |
| 05 - N/A BEV                       | `3006 Revenue - Non-Alcoholic`                 | Credit     |
| 10 - MODIFIERS                     | `3001 Revenue`                                 | Credit     |
| 11 - BANQUETS                      | `3031 Revenue - Banquets & Wedding`            | Credit     |
| GST                                 | `2029 GST Charged on Sales`                    | Credit     |
| PST (7%)                           | `2035 PST 7% Charged on Sales`                 | Credit     |
| ALCOHOL (PST 10% Liquor)           | `2039 PST 10% Liquor Charged on Sales`         | Credit     |
| Discounts (single combined line)   | `3050 Discounts given`                         | Debit      |
| Non-Cash Tips + Auto Gratuity      | `6044 Tips & Gratuities` (combined into ONE line) | Credit  |

Notes:
- Card tenders (MC/VISA/DEBIT) always post as **separate lines**, never combined,
  even though they share account 1007.
- Tips and Auto Gratuity, when both present on the same day, are **summed into
  a single 6044 credit line** — do not post them separately.
- **IMPORTANT — account name spacing must exactly match QBO's Chart of
  Accounts.** All "Revenue - X" accounts use a dash with a space on both sides
  (e.g. `3002 Revenue - Food`, `3006 Revenue - Non-Alcoholic`). QBO's CSV
  import rejects a Line Account that doesn't match the Chart of Accounts
  string exactly (this has caused real import failures — see §7).
- Omit a line entirely if that category has $0 or doesn't appear on the report.
  **Never post a $0.00 line.**

## 4. Discounts handling

- If a Discounts column shows non-zero values in the Sales table, post ONE
  combined debit line to `3050 Discounts given` for the total discount amount
  across all categories — do not split by category.
- Use the **Amount** (post-discount / net) column for each sales category line
  when discounts are present, and separately book the combined discount as its
  own line, so that gross sales = net sales + discounts on the credit side,
  which zeroes out with the discount debit.
- If no Discounts column values, just use Amount directly (it will equal Gross
  Amount).

## 5. Class (Location/Department) rules — CONFIRMED, do not deviate

**This was the source of a real production error corrected mid-project. Follow
exactly:**

- Default class for **every line** is **`0101 - BANQUET- FOOD`**.
- The ONLY exception: sales lines for **Liquor (3003), Wine (3004), and Beer
  (3005)** go to **`0102 - BANQUET LIQUOR`**.
- Everything else — RC, Cash, all card tenders, Corp GC, Food/N-A Bev/Modifiers/
  Banquets sales, GST, PST, Alcohol tax (2039), Discounts, and Tips (6044) —
  stays on `0101 - BANQUET- FOOD`.
- There is NO `0081-WEDDINGS & BANQUETS` class used in Banquets entries. (An
  earlier version of this workflow incorrectly split RC/tenders/tips onto
  0081 — this was flagged as wrong by the site manager and confirmed wrong
  against real posted QBO entries. Do not reintroduce it.)

## 6. Description / Memo conventions

- `Memo` field (repeated on every row): `"Banquets Daily Revenue DD Month YYYY"`
  e.g. `"Banquets Daily Revenue 15 August 2026"`.
- `Description` field: **every line gets a category prefix**, formatted as
  `"{Category} - Banquets Daily Revenue DD Month YYYY"`, e.g.:
  - `"RC - Banquets Daily Revenue 15 August 2026"`
  - `"MC - Banquets Daily Revenue 15 August 2026"` (or `Mastercard -`)
  - `"Visa - Banquets Daily Revenue 15 August 2026"`
  - `"Debit - Banquets Daily Revenue 15 August 2026"`
  - `"Liquor - Banquets Daily Revenue 15 August 2026"`
  - `"Wine - Banquets Daily Revenue 15 August 2026"`
  - `"Beer - Banquets Daily Revenue 15 August 2026"`
  - The 3031 Banquets sales line, GST line, and Tips line may use the plain
    memo with **no prefix** (confirmed from real export) — but prefixing them
    too is not wrong, just check against the most recent real example if in
    doubt.
- Date format inside the memo/description text: `DD Month YYYY` (e.g.
  `23 May 2026`, `15 August 2026`) — NOT `Month DD, YYYY`.
- **Never put an unquoted/unescaped comma inside a Memo or Description field**
  — see §7 for why this breaks QBO's importer.

## 7. QBO CSV import format — hard requirements

- Header row exactly:
  `*JournalNo,*JournalDate,Memo,*AccountName,Debits,Credits,Description,Name,Location,Class`
- `*JournalNo`, `*JournalDate`, and `Memo` should repeat on every line of the
  entry (safe/consistent, even though QBO only strictly needs JournalNo on
  each row).
- `*JournalDate` format: `DD-MM-YYYY` (e.g. `15-08-2026`).
- **Do not put a bare comma inside any field** (e.g. "August 15, 2026") without
  quoting — and don't rely on CSV quoting alone, because QBO's importer has
  been observed doing naive comma-splitting that ignores quote characters.
  Safest approach: reword dates/text to avoid the comma entirely
  (`"15 August 2026"` not `"August 15, 2026"`), even inside quoted fields.
- `*AccountName` must be spelled and spaced **exactly** as it appears in the
  live QBO Chart of Accounts. Mismatches (e.g. `3002 Revenue-Food` vs.
  `3002 Revenue - Food`) cause a "Line Account invalid" import error. When in
  doubt, pull the authoritative list from the Chart of Accounts export rather
  than assuming.
- Only ONE of Debits or Credits should be populated per line, never both
  ("Credits and debits present" is a hard import error).
- Every line needs a valid numeric amount in Debits or Credits — never leave
  the amount blank on a line that has an account.
- `Name` and `Location` columns: leave blank for Banquets entries (no QBO
  contact/location match needed) — do not put text there or QBO will reject it
  as "Name invalid" / "Location invalid".
- Debits total must exactly equal Credits total, to the cent, before the file
  is considered done.

## 8. Journal numbering

- Banquets and Bears Den (and other outlets) share one global QBO journal
  number sequence — gaps between Banquets entries are normal and expected,
  because other outlets' entries fall between them.
- Default behavior: increment from the last known Banquets journal number by 1.
- BUT: always confirm with the user before assuming the number, especially if:
  - there's any gap or ambiguity from a prior entry not being confirmed as
    posted successfully, or
  - the user has recently provided an explicit override number (e.g. "Use
    JJ3431 instead") — a manually-supplied number resets the auto-increment
    baseline going forward from that number.
- If the user says "change the journal number", ask what number to use,
  then do a straight find-and-replace of the old number for the new one
  across every row of that entry's CSV — do not touch anything else in the
  file (dates, memos, amounts, classes should be untouched by a renumber).

## 9. Output conventions

- One CSV file per day/entry. Never batch multiple days into one file.
- Filename convention: `Banquets_JE_[Month][DD]_[YYYY].csv` (e.g.
  `Banquets_JE_Aug15_2026.csv`).
- After building a file, run an automated balance check (sum Debits column,
  sum Credits column, confirm equal) before presenting it — never hand over
  an unbalanced file.
- Once a CSV has been delivered to the user, do NOT regenerate/overwrite it
  silently for corrections — the user makes adjustments manually in QBO, or
  explicitly asks for a new corrected file. Only rebuild if:
  - the user explicitly asks for a fix/correction, or
  - it's a genuinely new entry (different date).
- Always end with a short **Flags** section noting anything unusual: missing
  categories, unexplained rounding gaps, first-time-seen tender types (e.g.
  Corp GC appearing for the first time), or any assumption made where the
  source data was ambiguous.

## 10. Known edge cases encountered so far

- Some days have **only Banquets sales + GST + RC + Tips/Auto-Gratuity** with
  no liquor breakout at all — in that case there's nothing to move to 0102,
  everything sits on 0101.
- Some days have Alcohol tax (2039) present even though there's no separate
  Liquor/Wine/Beer sales line (alcohol sales bundled into the single Banquets
  line) — in that case, 2039 still stays on 0101 (there's no alcohol *sales*
  line to move to 0102; only the sales lines change class, never the tax
  line, regardless of whether alcohol sales are broken out separately or not).
- A source report can occasionally have a small (~$2) unexplained rounding gap
  between sales+tax and tenders where every individual figure re-verifies
  correctly against the PDF — this appears to be a genuine POS-side rounding
  or void artifact, not a transcription error. Flag it; don't silently force
  balance.
- Raster/scanned PDFs with no text layer are common — always be ready to
  rasterize + read visually rather than assuming `pdftotext` will work.
