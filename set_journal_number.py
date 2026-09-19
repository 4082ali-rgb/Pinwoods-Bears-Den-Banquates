#!/usr/bin/env python3
"""Directly sets the journal number RUN will use for its next entry."""
import json
import re
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent / "journal_state.json"


def main():
    while True:
        raw = input("Journal number for the NEXT entry (e.g. JJ3528): ").strip().upper()
        if re.fullmatch(r"JJ\d+", raw):
            break
        print("That doesn't look like a journal number (expected e.g. JJ3528). Try again.")
    STATE_FILE.write_text(json.dumps({"next": raw}, indent=2), encoding="utf-8")
    print(f"Done. RUN will use {raw} for its next entry.")


if __name__ == "__main__":
    main()
