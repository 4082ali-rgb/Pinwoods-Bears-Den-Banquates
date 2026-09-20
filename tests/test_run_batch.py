"""Tests for run_batch.py - the inbox/output batch runner."""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "samples"


def make_repo(tmp_path):
    """A throwaway copy of just what run_batch.py needs, isolated from the real repo state."""
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(ROOT / "run_batch.py", repo / "run_batch.py")
    shutil.copy(ROOT / "silverware_je.py", repo / "silverware_je.py")
    (repo / "inbox").mkdir()
    (repo / "output").mkdir()
    return repo


def run(repo, stdin_text=""):
    return subprocess.run([sys.executable, "run_batch.py"], cwd=repo,
                          input=stdin_text, capture_output=True, text=True)


def test_mixed_drop_orders_by_date_and_increments(tmp_path):
    repo = make_repo(tmp_path)
    shutil.copy(S / "Pinewoods_2026-08-31.txt", repo / "inbox" / "later.txt")
    shutil.copy(S / "BearsDen_2026-08-28.txt", repo / "inbox" / "earlier.txt")
    r = run(repo, stdin_text="JJ7000\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not list((repo / "inbox").iterdir())  # both moved out
    csvs = sorted((repo / "output").glob("*.csv"))
    assert any("JJ7000" in c.name and "BearsDen" in c.name for c in csvs)   # 28 Aug processed first
    assert any("JJ7001" in c.name and "Pinewoods" in c.name for c in csvs)  # 31 Aug processed second
    state = json.loads((repo / "journal_state.json").read_text())
    assert state["next"] == "JJ7002"


def test_bad_file_does_not_kill_the_batch(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "inbox" / "garbage.txt").write_text("not a Silverware report at all", encoding="utf-8")
    shutil.copy(S / "BearsDen_2026-08-28.txt", repo / "inbox" / "good.txt")
    r = run(repo, stdin_text="JJ7100\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STOP: garbage.txt" in r.stdout
    assert (repo / "inbox" / "garbage.txt").exists()          # left in place
    assert not (repo / "inbox" / "good.txt").exists()          # good one still processed
    csvs = list((repo / "output").glob("*.csv"))
    assert len(csvs) == 1 and "JJ7100" in csvs[0].name          # bad file didn't consume a number
    state = json.loads((repo / "journal_state.json").read_text())
    assert state["next"] == "JJ7101"


def test_unbalanced_file_leaves_journal_number_untouched(tmp_path):
    repo = make_repo(tmp_path)
    txt = (S / "BearsDen_2026-08-28.txt").read_text().replace("$600.28", "$602.28")
    (repo / "inbox" / "unbalanced.txt").write_text(txt, encoding="utf-8")
    r = run(repo, stdin_text="JJ7200\n")
    assert r.returncode == 0
    assert "does not balance" in r.stdout
    assert (repo / "inbox" / "unbalanced.txt").exists()
    assert not list((repo / "output").glob("*.csv"))
    assert not (repo / "journal_state.json").exists()  # never consumed, nothing to save


def test_saved_journal_number_is_reused_next_run(tmp_path):
    repo = make_repo(tmp_path)
    shutil.copy(S / "BearsDen_2026-08-28.txt", repo / "inbox" / "day1.txt")
    run(repo, stdin_text="JJ7300\n")

    shutil.copy(S / "Pinewoods_2026-08-31.txt", repo / "inbox" / "day2.txt")
    r2 = run(repo)  # no stdin needed - the number is already saved
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert any("JJ7301" in c.name for c in (repo / "output").glob("*.csv"))


def test_invalid_saved_state_asks_again_instead_of_crashing(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "journal_state.json").write_text('{"next": "not-a-journal-number"}', encoding="utf-8")
    shutil.copy(S / "BearsDen_2026-08-28.txt", repo / "inbox" / "day1.txt")
    r = run(repo, stdin_text="JJ7400\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert any("JJ7400" in c.name for c in (repo / "output").glob("*.csv"))


def test_empty_inbox_no_error(tmp_path):
    repo = make_repo(tmp_path)
    r = run(repo)
    assert r.returncode == 0
    assert "Nothing to do" in r.stdout
