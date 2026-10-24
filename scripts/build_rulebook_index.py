"""Rebuild assets/usbc_rulebook_index.json from the rulebook PDF.

Run after replacing the PDF:  python scripts/build_rulebook_index.py
Needs either the `pdftotext` command (poppler) or `pip install pypdf`.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from modules.rulebook import INDEX_PATH, parse_rulebook_text  # noqa: E402

PDF = ROOT / "assets" / "USBC-Playing-Rulebook-26-27.pdf"


def pdf_text(path: Path) -> str:
    if shutil.which("pdftotext"):
        return subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=True).stdout
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


if __name__ == "__main__":
    sections = parse_rulebook_text(pdf_text(PDF))
    INDEX_PATH.write_text(json.dumps(sections, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Wrote {len(sections)} sections to {INDEX_PATH}")
