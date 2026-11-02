#this file is for creating an unorganized folder so it can be tested before completing this automation

import base64
import os
import shutil
import struct
import zipfile
import zlib
from pathlib import Path
 
# Always create the folder next to this script (inside the project folder),
# no matter which directory the terminal is in.
ROOT = Path(__file__).resolve().parent / "sample_project"
 
# A real 32x16 JPEG image (blue-purple gradient)
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+"
    "JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7"
    "Ozv/wAARCAAQACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQID"
    "AAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlq"
    "c3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3"
    "+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEI"
    "FEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImK"
    "kpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDC"
    "SrMdVkqzHX0GKMMJ0LCVZSqyVZSvmcUfVYQ//9k="
)
 
 
# --------------------------------------------------------------------------
# Builders for real file formats (standard library only)
# --------------------------------------------------------------------------
 
def make_png(width, height, pixel_rows):
    """Build a valid PNG from rows of raw RGB bytes."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
 
    raw = b"".join(b"\x00" + row for row in pixel_rows)  # filter byte 0 per row
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 1))
            + chunk(b"IEND", b""))
 
 
def solid_png(width, height, rgb):
    return make_png(width, height, [bytes(rgb) * width] * height)
 
 
def noise_png(width, height):
    """Random-colour PNG. Random pixels barely compress, so the file stays large."""
    return make_png(width, height, (os.urandom(width * 3) for _ in range(height)))
 
 
def make_pdf(text):
    """Build a valid one-page PDF showing a line of text."""
    stream = f"BT /F1 18 Tf 50 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
 
 
def make_docx(path, paragraphs):
    """Build a minimal Word document that opens in Word / LibreOffice."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body>{body}</w:body></w:document>')
 
 
def make_xlsx(path, rows):
    """Build a minimal Excel workbook that opens in Excel / LibreOffice."""
    def cell(ref, value):
        if isinstance(value, (int, float)):
            return f'<c r="{ref}"><v>{value}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'
 
    sheet_rows = "".join(
        f'<row r="{r}">' + "".join(cell(f"{chr(65 + c)}{r}", v) for c, v in enumerate(row)) + "</row>"
        for r, row in enumerate(rows, 1))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Sales" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{sheet_rows}</sheetData></worksheet>')
 
 
# --------------------------------------------------------------------------
# Folder creation
# --------------------------------------------------------------------------
 
def write(rel_path, data):
    path = ROOT / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    print(f"  created {path.relative_to(ROOT.parent)}")
 
 
def build(rel_path, builder, *args):
    """For formats built straight into a file (docx, xlsx, zip)."""
    path = ROOT / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    builder(path, *args)
    print(f"  created {path.relative_to(ROOT.parent)}")
 
 
def make_zip(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("readme.txt", "Old assets backup from the previous website version.\n")
        z.writestr("old_logo.png", solid_png(64, 64, (120, 120, 120)))
 
 
def main():
    if ROOT.exists():
        shutil.rmtree(ROOT)
    print(f"Creating sample folder at: {ROOT}\n")
 
    # Images (logo_copy.png is a duplicate of logo.png)
    logo = solid_png(128, 128, (47, 111, 237))
    write("images/logo.png", logo)
    write("images/logo_copy.png", logo)
    write("images/banner.jpg", TINY_JPEG)
    write("images/hero_raw.png", noise_png(2000, 2000))  # about 11.5 MB, oversized
 
    # Documents and PDFs (contract_final.pdf duplicates contract.pdf)
    write("docs/project_brief.txt", "Project brief\n\nGoal: launch the new website by Q1.\n")
    write("docs/meeting_notes.md", "# Meeting Notes\n\n- Agreed on colour palette\n- Next review Friday\n")
    build("docs/proposal.docx", make_docx,
          ["Website Redesign Proposal", "Scope: new homepage, blog and contact page.",
           "Timeline: 6 weeks."])
    write("docs/empty_draft.txt", "")  # empty file
    contract = make_pdf("Service Contract - Sample")
    write("docs/contract.pdf", contract)
    write("docs/contract_final.pdf", contract)
 
    # Spreadsheets
    write("data/budget.csv", "item,cost\nhosting,120\ndesign,800\nads,300\n")
    build("data/sales_2026.xlsx", make_xlsx,
          [["Month", "Sales"], ["January", 4200], ["February", 3900], ["March", 5100]])
 
    # Code, unknown types, loose root file
    write("scripts/build.py", "print('building project...')\n")
    write("misc/LICENSE", "MIT License\n")  # no extension
    write("misc/export.dat", "id|name|status\n1|homepage|done\n2|blog|in progress\n")  # unknown extension
    write("screenshot.png", solid_png(200, 120, (240, 240, 240)))  # loose file in root
 
    # A real zip archive
    build("misc/old_assets.zip", make_zip)
 
    print(f"\nDone! Sample folder saved at: {ROOT}")
    print("Now run:  python organizer.py   (then select the sample_project folder)")
 
 
if __name__ == "__main__":
    main()