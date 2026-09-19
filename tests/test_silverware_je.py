"""Regression tests: each sample must parse, balance, and emit the expected QBO CSV shape."""
import csv
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import silverware_je as sw  # noqa: E402

S = ROOT / "samples"


def run(sample, jn, out, extra=()):
    return subprocess.run([sys.executable, str(ROOT / "silverware_je.py"), str(S / sample), jn,
                           "--out", str(out), *extra], capture_output=True, text=True)


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("sample,jn,fname,total,n", [
    ("Pinewoods_2026-08-31.txt", "JJ3417", "JJ3417_Pinewoods_2026-08-31.csv", "6946.10", 15),
    ("BearsDen_2026-08-28.txt",  "JJ3382", "JJ3382_BearsDen_Aug28.csv",       "4212.38", 14),
    ("Banquets_2026-08-15.txt",  "JJ3431", "Banquets_JE_Aug15_2026.csv",      "8048.12", 11),
])
def test_sample_balances_and_writes(tmp_path, sample, jn, fname, total, n):
    r = run(sample, jn, tmp_path, ["--segments"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Balanced: YES" in r.stdout
    raw = (tmp_path / fname).read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf" and b"\r\n" in raw
    rows = read(tmp_path / fname)
    assert list(rows[0].keys()) == sw.CSV_FIELDS
    assert len(rows) == n
    dr = sum(float(x["Debits"] or 0) for x in rows)
    cr = sum(float(x["Credits"] or 0) for x in rows)
    assert f"{dr:.2f}" == f"{cr:.2f}" == total
    for x in rows:
        assert x["*JournalNo"] == jn and x["Name"] == "" and x["Location"] == "" and x["Class"]
        assert bool(x["Debits"]) != bool(x["Credits"])          # exactly one side
        assert "," not in x["Description"] and "," not in x["Memo"]
    # segment file + cumulative ledger + log
    seg = read(tmp_path / (Path(fname).stem + "_segments.csv"))
    assert list(seg[0].keys()) == sw.SEGMENT_FIELDS
    assert all(s["JournalNo"] == jn for s in seg)
    assert any(s["Type"] == "Sales Total" for s in seg)
    assert (tmp_path / sw.SEGMENT_LEDGER).exists() and (tmp_path / sw.RUN_LOG).exists()


def test_banquets_classes_and_prefixes(tmp_path):
    run("Banquets_2026-08-15.txt", "JJ3431", tmp_path)
    rows = read(tmp_path / "Banquets_JE_Aug15_2026.csv")
    by = {r["*AccountName"]: r for r in rows}
    for a in (sw.A_LIQUOR, sw.A_WINE, sw.A_BEER):
        assert by[a]["Class"] == sw.C_BQ_LIQUOR
    for a in (sw.A_PST_LIQ, sw.A_TIPS, sw.A_ROOMCHG, sw.A_BANQUETS, sw.A_GST):
        assert by[a]["Class"] == sw.C_BQ_FOOD
    assert by[sw.A_ROOMCHG]["Description"] == "RC - Banquets Daily Revenue 15 August 2026"
    assert by[sw.A_ROOMCHG]["*JournalDate"] == "15-08-2026"
    assert by[sw.A_TIPS]["Credits"] == "1312.16"       # non-cash tips + auto gratuity, one line


def test_bearsden_duplicate_prefix_rule(tmp_path):
    run("BearsDen_2026-08-28.txt", "JJ3382", tmp_path)
    rows = read(tmp_path / "JJ3382_BearsDen_Aug28.csv")
    descs = [r["Description"] for r in rows if r["*AccountName"] == sw.A_REVENUE]
    assert sorted(descs) == ["Modifiers-Bears Den Daily Revenue August 28 2026",
                             "Pool Table-Bears Den Daily Revenue August 28 2026"]
    food = next(r for r in rows if r["*AccountName"] == sw.A_FOOD)
    assert food["Description"] == "Bears Den Daily Revenue August 28 2026"
    assert food["Credits"] == "2400.00"                # net, not gross
    assert all(r["Class"] == sw.C_BEARSDEN for r in rows)
    assert not any(r["*AccountName"] == sw.A_DISCOUNT for r in rows)


def test_pinewoods_net_no_discount_line(tmp_path):
    run("Pinewoods_2026-08-31.txt", "JJ3417", tmp_path)
    rows = read(tmp_path / "JJ3417_Pinewoods_2026-08-31.csv")
    by = {r["*AccountName"]: r for r in rows}
    assert by[sw.A_FOOD]["Credits"] == "4060.00" and sw.A_DISCOUNT not in by
    assert by[sw.A_GST]["Description"] == "Pinewoods Daily Revenue August 31 2026"


def test_indented_real_layout(tmp_path):
    """Real pdfplumber output is indented ~5 spaces; the parser must not depend on column 0."""
    txt = "\n".join("     " + l for l in (S / "BearsDen_2026-08-28.txt").read_text().splitlines())
    p = tmp_path / "x.txt"; p.write_text(txt)
    r = subprocess.run([sys.executable, str(ROOT / "silverware_je.py"), str(p), "JJ1", "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "Balanced: YES" in r.stdout


def test_nonsales_discount_gets_3050_on_net_basis(tmp_path):
    txt = (S / "Pinewoods_2026-08-31.txt").read_text()
    txt = txt.replace("$1,296.10", "$1,293.10")   # tenders drop by the $3 open-dollar discount
    txt = txt.replace("Net Cash Owing", "Non-Sales             Qnty     Gross Amount      Refunds     Discounts        Amount\n"
                      "09- DISCOUNT             1            $0.00        $0.00         $3.00        -$3.00\n"
                      "   Total:                1            $0.00        $0.00         $3.00        -$3.00\n\nNet Cash Owing")
    p = tmp_path / "x.txt"; p.write_text(txt)
    r = subprocess.run([sys.executable, str(ROOT / "silverware_je.py"), str(p), "JJ1", "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "Balanced: YES" in r.stdout, r.stdout + r.stderr
    rows = read(tmp_path / "JJ1_Pinewoods_2026-08-31.csv")
    by = {r["*AccountName"]: r for r in rows}
    assert by[sw.A_DISCOUNT]["Debits"] == "3.00" and by[sw.A_FOOD]["Credits"] == "4060.00"


def test_extra_accounts_json_merges_into_profiles(tmp_path):
    (tmp_path / "extra_accounts.json").write_text(
        '{"pinewoods": {"sales": {"12- CATERING": ["3001 Revenue", "Catering", null]}}}',
        encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(ROOT)!r}); import os; os.chdir({str(tmp_path)!r}); "
         "import silverware_je as sw; print(sw.PROFILES['pinewoods']['sales']['12- CATERING'])"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "('3001 Revenue', 'Catering', None)" in r.stdout


def test_wrong_outlet_refused(tmp_path):
    r = run("BearsDen_2026-08-28.txt", "JJ1", tmp_path, ["--outlet", "banquets"])
    assert r.returncode != 0 and "Cost Center" in (r.stdout + r.stderr)


def test_unknown_tender_stops(tmp_path):
    txt = (S / "BearsDen_2026-08-28.txt").read_text().replace("Corp GC                  1", "AMEX                     1")
    p = tmp_path / "x.txt"; p.write_text(txt)
    r = subprocess.run([sys.executable, str(ROOT / "silverware_je.py"), str(p), "JJ1", "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "unknown payment tender 'AMEX'" in r.stderr
    assert not list(tmp_path.glob("*.csv"))


def test_unbalanced_not_written(tmp_path):
    txt = (S / "BearsDen_2026-08-28.txt").read_text().replace("$600.28", "$602.28")
    p = tmp_path / "x.txt"; p.write_text(txt)
    r = subprocess.run([sys.executable, str(ROOT / "silverware_je.py"), str(p), "JJ1", "--out", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "does not balance" in r.stderr and "GAP +2.00" in r.stdout
    assert not list(tmp_path.glob("*.csv"))


def test_default_writes_only_qbo_csv(tmp_path):
    assert run("Banquets_2026-08-15.txt", "JJ3431", tmp_path).returncode == 0
    assert [p.name for p in sorted(tmp_path.glob("*.csv"))] == ["Banquets_JE_Aug15_2026.csv", sw.RUN_LOG]


def test_no_silent_overwrite(tmp_path):
    assert run("Banquets_2026-08-15.txt", "JJ3431", tmp_path).returncode == 0
    r = run("Banquets_2026-08-15.txt", "JJ3431", tmp_path)
    assert r.returncode != 0 and "already exists" in r.stderr
    assert run("Banquets_2026-08-15.txt", "JJ3431", tmp_path, ["--force"]).returncode == 0


def test_ledger_upserts_same_day(tmp_path):
    run("Banquets_2026-08-15.txt", "JJ3431", tmp_path, ["--segments"])
    run("Banquets_2026-08-15.txt", "JJ3499", tmp_path, ["--force", "--segments"])
    run("BearsDen_2026-08-28.txt", "JJ3382", tmp_path, ["--segments"])
    led = read(tmp_path / sw.SEGMENT_LEDGER)
    bq = [r for r in led if r["Outlet"] == "Banquets"]
    assert bq and all(r["JournalNo"] == "JJ3499" for r in bq)      # replaced, not duplicated
    assert {r["Outlet"] for r in led} == {"Banquets", "Bears Den"}
