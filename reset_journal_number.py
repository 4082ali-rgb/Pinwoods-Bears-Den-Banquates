#!/usr/bin/env python3
"""Clears the saved journal number so the next RUN asks you for a starting number again."""
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent / "journal_state.json"


def main():
    print("This clears the saved journal number.")
    print("The next time you run RUN, it will ask you for a journal number again.")
    print()
    answer = input("Type YES to continue: ").strip()
    if answer != "YES":
        print("Cancelled - nothing changed.")
        return
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print("Done. Journal number cleared.")
    else:
        print("Nothing to clear - no journal number was saved yet.")


if __name__ == "__main__":
    main()
