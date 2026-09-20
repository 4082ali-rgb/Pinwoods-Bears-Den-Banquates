#!/usr/bin/env python3
"""
setup.py  -  one-time setup check for the offline Silverware JE toolkit.

Run by double-clicking SETUP.bat (Windows) or `python3 setup.py` directly.
Installs the Python packages this needs, creates the inbox/output folders,
and tells you plainly what's ready and what (if anything) still needs doing
for OCR on scanned PDFs. Safe to run again any time - it only ever adds
folders/packages, never touches your PDFs, CSVs, or saved journal number.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def ok(msg):
    print(f"  [OK] {msg}")


def missing(msg):
    print(f"  [--] {msg}")


def main():
    print("=" * 70)
    print("Silverware JE toolkit - setup")
    print("=" * 70)
    print()

    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info < (3, 10):
        print("  WARNING: this was built for Python 3.10+. Consider installing a newer")
        print("  Python from https://www.python.org/downloads/ if anything below errors.")
    print()

    print("Installing required packages (pdfplumber, pytest, and the optional OCR")
    print("package pytesseract)...")
    req = ROOT / "requirements.txt"
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)])
    if result.returncode == 0:
        ok("Python packages installed.")
    else:
        missing("pip install had a problem (see above) - the tool may still work if "
               "pdftotext is installed (see below), just without the pdfplumber fallback.")
    print()

    print("Creating inbox/ and output/ folders...")
    (ROOT / "inbox").mkdir(exist_ok=True)
    (ROOT / "output").mkdir(exist_ok=True)
    ok("Ready.")
    print()

    print("Checking PDF text extraction:")
    if shutil.which("pdftotext"):
        ok("pdftotext found (poppler) - the preferred, most accurate reader.")
    else:
        try:
            import pdfplumber  # noqa: F401
            ok("pdftotext not found, but pdfplumber is installed - reports will still be read fine.")
        except ImportError:
            missing("Neither pdftotext nor pdfplumber is available. Re-run this setup, or install "
                   "poppler (Windows: https://github.com/oschwartz10612/poppler-windows/releases/, "
                   "Mac: brew install poppler, Linux: apt install poppler-utils).")
    print()

    print("Checking OCR (only needed for scanned/photographed PDFs with no text layer):")
    has_tesseract = shutil.which("tesseract") is not None
    try:
        import pytesseract  # noqa: F401
        has_py_ocr = True
    except ImportError:
        has_py_ocr = False

    if has_tesseract and has_py_ocr:
        ok("OCR is fully set up - scanned PDFs will be handled automatically. "
          "(No poppler needed - pages are rendered by pdfplumber.)")
    else:
        missing("OCR is not fully set up yet. Most reports don't need this - only a scanned or")
        missing("photographed one will. If that happens, either:")
        missing("  1) install Tesseract OCR (Windows: "
               "https://github.com/UB-Mannheim/tesseract/wiki - just the OCR engine, no "
               "poppler needed), add it to PATH, then re-run this setup - OCR then works "
               "automatically from then on, or")
        missing("  2) get the report as a .txt file (OCR'd elsewhere) and drop that into inbox "
               "instead of the PDF - no install needed.")
    print()

    print("=" * 70)
    print("Setup done. Drop PDFs into 'inbox' and double-click RUN.bat.")
    print("=" * 70)


if __name__ == "__main__":
    main()
