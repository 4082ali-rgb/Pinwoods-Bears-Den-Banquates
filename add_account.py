#!/usr/bin/env python3
"""
Adds a new sales category or payment tender the reports have never shown before,
without editing silverware_je.py. Saves into extra_accounts.json, which
silverware_je.py (and run_batch.py) load automatically on every run.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXTRA_FILE = ROOT / "extra_accounts.json"
OUTLETS = {"1": ("pinewoods", "Pinewoods"), "2": ("bearsden", "Bears Den"), "3": ("banquets", "Banquets")}


def ask_optional(prompt):
    while True:
        s = input(prompt).strip()
        if "," in s:
            print("  No commas allowed - a comma anywhere in the CSV breaks the QuickBooks import. "
                 "Reword it without one.")
            continue
        return s if s else None


def ask_required(prompt):
    while True:
        s = input(prompt).strip()
        if not s:
            print("  This can't be blank. Try again.")
            continue
        if "," in s:
            print("  No commas allowed - a comma anywhere in the CSV breaks the QuickBooks import. "
                 "Reword it without one.")
            continue
        return s


def main():
    print("Add a new sales category or payment tender that a report has shown for the")
    print("first time. This does not change any existing mapping.")
    print()
    print("Which outlet is this for?")
    print("  1) Pinewoods")
    print("  2) Bears Den")
    print("  3) Banquets")
    outlet = None
    while outlet is None:
        outlet_entry = OUTLETS.get(input("  Choice (1/2/3): ").strip())
        if outlet_entry is None:
            print("  Please type 1, 2 or 3.")
        else:
            outlet, outlet_name = outlet_entry

    print()
    kind = None
    while kind is None:
        choice = input("Is this a Sales category or a Payment tender? (1=Sales, 2=Tender): ").strip()
        kind = {"1": "sales", "2": "tenders"}.get(choice)
        if kind is None:
            print("Please type 1 or 2.")

    print()
    label = ask_required("Label exactly as it is printed on the report (e.g. '12- CATERING'): ")
    account = ask_required("QBO account, spelled exactly like the Chart of Accounts (e.g. '3001 Revenue'): ")
    prefix = ask_optional("Description prefix for the CSV, blank for none (e.g. 'Catering'): ")
    cls = ask_optional("Class override, blank to use the outlet's default class: ")

    data = {}
    if EXTRA_FILE.exists():
        try:
            data = json.loads(EXTRA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"WARNING: {EXTRA_FILE.name} was not valid JSON - starting a fresh one.")
            data = {}

    existing = data.get(outlet, {}).get(kind, {}).get(label)
    if existing is not None:
        print()
        print(f"'{label}' on {outlet_name} is already mapped to '{existing[0]}'.")
        answer = input("Type YES to overwrite it, anything else to cancel: ").strip()
        if answer != "YES":
            print("Cancelled - nothing changed.")
            return

    data.setdefault(outlet, {}).setdefault(kind, {})[label] = [account, prefix, cls]
    EXTRA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    print()
    print(f"Saved. On {outlet_name}, '{label}' now maps to '{account}'.")
    print("This takes effect the next time RUN or silverware_je.py runs.")


if __name__ == "__main__":
    main()
