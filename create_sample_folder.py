#this file is for creating an unorganized folder so it can be tested before completing this automation

import base64
import shutil
import zipfile
from pathlib import Path

# Always create the folder next to this script (inside the project folder),
# no matter which directory the terminal is in.
ROOT = Path(__file__).resolve().parent / "sample_project"

# A real 1x1 pixel PNG image
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

# A minimal valid one-page PDF
TINY_PDF = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] >> endobj
trailer << /Root 1 0 R >>
%%EOF
"""


def write(rel_path, data):
    path = ROOT / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    print(f"  created {path.relative_to(ROOT.parent)}")


def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    print(f"Creating sample folder at: {ROOT}")

    # Images (logo_copy.png is a duplicate of logo.png)
    write("images/logo.png", TINY_PNG)
    write("images/logo_copy.png", TINY_PNG)
    write("images/banner.jpg", b"\xff\xd8\xff\xe0" + b"fake jpeg data " * 200)
    write("images/hero_raw.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * (12 * 1024 * 1024))  # 12 MB, oversized

    # Documents and PDFs (contract_final.pdf duplicates contract.pdf)
    write("docs/project_brief.txt", "Project brief\n\nGoal: launch the new website by Q1.\n")
    write("docs/meeting_notes.md", "# Meeting Notes\n\n- Agreed on colour palette\n- Next review Friday\n")
    write("docs/proposal.docx", b"PK\x03\x04 placeholder docx content " * 50)
    write("docs/empty_draft.txt", "")  # empty file
    write("docs/contract.pdf", TINY_PDF)
    write("docs/contract_final.pdf", TINY_PDF)

    # Spreadsheets
    write("data/budget.csv", "item,cost\nhosting,120\ndesign,800\nads,300\n")
    write("data/sales_2026.xlsx", b"PK\x03\x04 placeholder xlsx content " * 80)

    # Code, unknown types, loose root files
    write("scripts/build.py", "print('building project...')\n")
    write("misc/LICENSE", "MIT License\n")          # no extension
    write("misc/export.dat", b"\x01\x02\x03" * 100)  # unknown extension
    write("screenshot.png", TINY_PNG + b"\x00")     # loose file in root

    # A real zip archive
    archive = ROOT / "misc/old_assets.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("readme.txt", "Old assets backup")
    print(f"  created {archive.relative_to(ROOT.parent)}")

    print(f"\nDone! Sample folder saved at: {ROOT}")
    print("Now run:  python organizer.py   (then select the sample_project folder)")


if __name__ == "__main__":
    main()