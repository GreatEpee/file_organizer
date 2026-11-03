#this file contains automated tests for organizer.py and create_sample_folder.py
#run them with:  python -m pytest

import os
from pathlib import Path

import pytest

import create_sample_folder
import organizer


# --------------------------------------------------------------------------
# Helper: quickly create files inside pytest's temporary folder
# --------------------------------------------------------------------------

def make(root, rel_path, content=b"x"):
    """Create a file at root/rel_path with the given content and return its path."""
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def scan_and_analyze(root, max_size=10):
    files, skipped = organizer.scan_folder(root)
    return organizer.analyze(files, skipped, max_size)


# --------------------------------------------------------------------------
# Helpers: human_size, categorize, md_escape
# --------------------------------------------------------------------------

@pytest.mark.parametrize("num_bytes, expected", [
    (0, "0 B"),
    (500, "500 B"),
    (1024, "1.0 KB"),
    (1536, "1.5 KB"),
    (1024 * 1024, "1.0 MB"),
    (5 * 1024 ** 3, "5.0 GB"),
])
def test_human_size(num_bytes, expected):
    assert organizer.human_size(num_bytes) == expected


@pytest.mark.parametrize("name, expected", [
    ("photo.png", "Images"),
    ("PHOTO.JPG", "Images"),          # uppercase extensions still work
    ("report.pdf", "PDFs"),
    ("notes.docx", "Documents"),
    ("budget.xlsx", "Spreadsheets"),
    ("deck.pptx", "Presentations"),
    ("backup.zip", "Archives"),
    ("script.py", "Code"),
    ("mystery.xyz", "Other"),         # unknown extension
    ("LICENSE", "Other"),             # no extension
])
def test_categorize(name, expected):
    assert organizer.categorize(Path(name)) == expected


def test_md_escape_protects_table_pipes():
    assert organizer.md_escape("a|b.txt") == "a\\|b.txt"


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

def test_scan_finds_files_in_subfolders(tmp_path):
    make(tmp_path, "a.txt")
    make(tmp_path, "images/b.png")
    make(tmp_path, "deep/nested/folder/c.pdf")
    files, skipped = organizer.scan_folder(tmp_path)
    assert sorted(f["rel"] for f in files) == ["a.txt", "deep/nested/folder/c.pdf", "images/b.png"]
    assert skipped == []


def test_scan_ignores_tool_folders_and_system_files(tmp_path):
    make(tmp_path, "keep.txt")
    make(tmp_path, ".git/config")
    make(tmp_path, "node_modules/lib/index.js")
    make(tmp_path, "__pycache__/x.pyc")
    make(tmp_path, "Thumbs.db")
    files, _ = organizer.scan_folder(tmp_path)
    assert [f["rel"] for f in files] == ["keep.txt"]


def test_scan_skips_its_own_report(tmp_path):
    make(tmp_path, "keep.txt")
    report = make(tmp_path, "report.md", "old report")
    files, _ = organizer.scan_folder(tmp_path, skip_paths=[report])
    assert [f["rel"] for f in files] == ["keep.txt"]


def test_scan_records_unreadable_folder(tmp_path, monkeypatch):
    make(tmp_path, "ok.txt")
    make(tmp_path, "private/secret.txt")
    real_scandir = os.scandir

    def fake_scandir(path="."):
        if str(path).endswith("private"):
            raise PermissionError(13, "Permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    files, skipped = organizer.scan_folder(tmp_path)
    assert [f["rel"] for f in files] == ["ok.txt"]   # secret.txt can't be seen
    assert len(skipped) == 1
    assert skipped[0]["rel"] == "private"
    assert skipped[0]["kind"] == "Folder"
    assert "Permission denied" in skipped[0]["reason"]


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------

def test_identical_files_are_duplicates_even_with_different_names(tmp_path):
    make(tmp_path, "logo.png", b"same content")
    make(tmp_path, "copies/logo_copy.png", b"same content")
    make(tmp_path, "other.png", b"different!!!")   # same size, different content
    files, _ = organizer.scan_folder(tmp_path)
    groups, skipped = organizer.find_duplicates(files)
    assert len(groups) == 1
    assert sorted(f["rel"] for f in groups[0]) == ["copies/logo_copy.png", "logo.png"]
    assert skipped == []


def test_empty_files_are_not_counted_as_duplicates(tmp_path):
    make(tmp_path, "a.txt", b"")
    make(tmp_path, "b.txt", b"")
    files, _ = organizer.scan_folder(tmp_path)
    groups, _ = organizer.find_duplicates(files)
    assert groups == []


def test_wasted_space_counts_every_extra_copy(tmp_path):
    for name in ["a.bin", "b.bin", "c.bin"]:
        make(tmp_path, name, b"x" * 100)
    a = scan_and_analyze(tmp_path)
    assert a["wasted_bytes"] == 200   # 3 copies, only 1 needed


def test_file_that_cannot_be_hashed_is_reported(tmp_path, monkeypatch):
    make(tmp_path, "a.txt", b"same")
    make(tmp_path, "b.txt", b"same")

    def fake_hash(path, chunk_size=0):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(organizer, "file_hash", fake_hash)
    files, _ = organizer.scan_folder(tmp_path)
    groups, skipped = organizer.find_duplicates(files)
    assert groups == []
    assert len(skipped) == 2
    assert "not checked for duplicates" in skipped[0]["reason"]


# --------------------------------------------------------------------------
# Analysis: oversized, empty, unknown, missing
# --------------------------------------------------------------------------

def test_oversized_uses_the_size_limit(tmp_path):
    make(tmp_path, "small.txt", b"x" * 500)
    make(tmp_path, "big.txt", b"x" * 2000)
    a = scan_and_analyze(tmp_path, max_size=0.001)   # 0.001 MB = about 1048 bytes
    assert [f["rel"] for f in a["oversized"]] == ["big.txt"]


def test_file_exactly_at_the_limit_is_not_oversized(tmp_path):
    make(tmp_path, "edge.bin", b"x" * 1024 * 1024)   # exactly 1 MB
    a = scan_and_analyze(tmp_path, max_size=1)
    assert a["oversized"] == []


def test_empty_and_unknown_files(tmp_path):
    make(tmp_path, "empty.txt", b"")
    make(tmp_path, "LICENSE", b"MIT")
    make(tmp_path, "data.xyz", b"???")
    a = scan_and_analyze(tmp_path)
    assert [f["rel"] for f in a["empty"]] == ["empty.txt"]
    assert sorted(f["rel"] for f in a["unknown"]) == ["LICENSE", "data.xyz"]


def test_missing_asset_types(tmp_path):
    make(tmp_path, "photo.png")
    make(tmp_path, "doc.pdf")
    a = scan_and_analyze(tmp_path)
    assert a["missing"] == ["Documents", "Spreadsheets", "Presentations"]


def test_empty_folder_does_not_crash(tmp_path):
    a = scan_and_analyze(tmp_path)
    assert a["total_files"] == 0
    assert a["missing"] == organizer.EXPECTED_CATEGORIES
    # rendering must not divide by zero
    organizer.render_markdown(tmp_path, a, organizer.build_recommendations(a))
    organizer.render_html(tmp_path, a, organizer.build_recommendations(a))


# --------------------------------------------------------------------------
# Recommendations
# --------------------------------------------------------------------------

def test_tidy_folder_gets_no_issues_message(tmp_path):
    for rel in ["images/a.png", "pdfs/b.pdf", "docs/c.docx", "data/d.xlsx", "slides/e.pptx"]:
        make(tmp_path, rel, rel)   # different content in each, so no duplicates
    a = scan_and_analyze(tmp_path)
    assert organizer.build_recommendations(a) == ["No issues found. The folder looks well organized."]


def test_loose_root_file_gets_recommendation(tmp_path):
    make(tmp_path, "screenshot.png")
    recs = organizer.build_recommendations(scan_and_analyze(tmp_path))
    assert any("loose file" in r for r in recs)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------

def test_generate_reports_writes_both_formats(tmp_path):
    project = tmp_path / "My Project!"
    make(project, "a.txt", "hello")
    analysis, recs, paths = organizer.generate_reports(project, ["md", "html"],
                                                       reports_dir=tmp_path / "reports")
    assert [p.name for p in paths] == ["report_My_Project_.md", "report_My_Project_.html"]
    assert all(p.exists() for p in paths)
    assert "Files scanned" in paths[0].read_text(encoding="utf-8")


def test_generate_reports_rejects_missing_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        organizer.generate_reports(tmp_path / "does_not_exist", ["md"], reports_dir=tmp_path)


def test_html_report_escapes_special_characters(tmp_path):
    # "&" and "'" have special meaning in HTML, and both are allowed in Windows file names
    make(tmp_path, "project/Tom & Jerry's notes.txt", "x")
    _, _, paths = organizer.generate_reports(tmp_path / "project", ["html"],
                                             reports_dir=tmp_path / "reports")
    html_text = paths[0].read_text(encoding="utf-8")
    assert "Tom & Jerry's" not in html_text                # raw text would break the HTML
    assert "Tom &amp; Jerry&#x27;s notes.txt" in html_text  # escaped version is used instead


# --------------------------------------------------------------------------
# End-to-end: the sample folder gives the expected results
# --------------------------------------------------------------------------

def test_sample_folder_results(tmp_path, monkeypatch, capsys):
    sample = tmp_path / "sample_project"
    monkeypatch.setattr(create_sample_folder, "ROOT", sample)   # build it in the temp folder
    create_sample_folder.main()

    a = scan_and_analyze(sample)
    assert a["total_files"] == 17
    assert len(a["duplicates"]) == 2
    assert [f["rel"] for f in a["oversized"]] == ["images/hero_raw.png"]
    assert [f["rel"] for f in a["empty"]] == ["docs/empty_draft.txt"]
    assert a["missing"] == ["Presentations"]
    assert a["skipped"] == []