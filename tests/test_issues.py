#this file contains automated tests for issues.py (the rows, filters and sorting in the Issues table)

from datetime import datetime, timedelta

import pytest

import create_sample_folder
import issues
import organizer


def make(root, rel_path, content=b"x"):
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def rows_for(folder, **options):
    files, skipped = organizer.scan_folder(folder)
    return issues.build_rows(organizer.analyze(files, skipped, 10, **options))


@pytest.fixture
def sample_rows(tmp_path, monkeypatch):
    sample = tmp_path / "sample_project"
    monkeypatch.setattr(create_sample_folder, "ROOT", sample)
    create_sample_folder.main()
    return rows_for(sample)


# --------------------------------------------------------------------------
# Building the rows
# --------------------------------------------------------------------------

def test_every_kind_of_problem_is_listed_for_the_sample_folder(sample_rows):
    assert issues.count_by_kind(sample_rows) == {
        "Duplicate": 4, "Oversized": 1, "Empty file": 1, "Unknown type": 2,
        "Stale": 2, "Bad name": 3, "Missing type": 1,
    }
    assert len(sample_rows) == 14


def test_duplicates_list_every_file_with_its_group(sample_rows):
    dups = [r for r in sample_rows if r["kind"] == "Duplicate"]
    assert [(r["item"], r["details"]) for r in dups] == [
        ("docs/contract.pdf", "Group 1: 2 identical copies"),
        ("docs/contract_final.pdf", "Group 1: 2 identical copies"),
        ("images/logo.png", "Group 2: 2 identical copies"),
        ("images/logo_copy.png", "Group 2: 2 identical copies"),
    ]


def test_rows_come_out_in_the_order_of_the_kinds(sample_rows):
    kinds = [r["kind"] for r in sample_rows]
    assert kinds == sorted(kinds, key=issues.KINDS.index)


def test_a_file_with_two_problems_appears_twice(sample_rows):
    kinds = sorted(r["kind"] for r in sample_rows if r["item"] == "images/logo_copy.png")
    assert kinds == ["Bad name", "Duplicate"]


def test_missing_types_are_not_real_files(sample_rows):
    missing = [r for r in sample_rows if r["kind"] == "Missing type"]
    assert [(r["item"], r["size"], r["path"]) for r in missing] == [("Presentations", None, None)]
    assert issues.size_text(missing[0]) == ""


def test_stale_rows_say_how_old_the_file_is():
    analysis = {"duplicates": [], "oversized": [], "empty": [], "unknown": [], "bad_names": [],
                "missing": [], "skipped": [], "max_size_mb": 10,
                "stale": [{"rel": "old.txt", "size": 5, "modified": datetime(2024, 1, 1)}]}
    row = issues.build_rows(analysis, now=datetime(2024, 1, 11))[0]
    assert row["details"] == "Last modified 2024-01-01 (10 days ago)"


def test_skipped_items_are_listed(tmp_path, monkeypatch):
    import os
    make(tmp_path, "ok.txt")
    make(tmp_path, "private/secret.txt")
    real_scandir = os.scandir

    def fake_scandir(path="."):
        if str(path).endswith("private"):
            raise PermissionError(13, "Permission denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", fake_scandir)
    skipped = [r for r in rows_for(tmp_path) if r["kind"] == "Skipped"]
    assert len(skipped) == 1
    assert skipped[0]["item"] == "private" and skipped[0]["path"] == "private"
    assert "Permission denied" in skipped[0]["details"]


def test_a_tidy_folder_has_no_rows(tmp_path):
    for rel in ["images/a.png", "pdfs/b.pdf", "docs/c.docx", "data/d.xlsx", "slides/e.pptx"]:
        make(tmp_path, rel, rel)
    assert rows_for(tmp_path) == []


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------

def test_no_filter_keeps_everything(sample_rows):
    assert issues.filter_rows(sample_rows) == sample_rows
    assert issues.filter_rows(sample_rows, set(), "") == sample_rows


def test_filter_by_one_kind(sample_rows):
    result = issues.filter_rows(sample_rows, {"Stale"})
    assert sorted(r["item"] for r in result) == ["data/budget.csv", "misc/old_assets.zip"]


def test_filter_by_several_kinds_shows_all_of_them(sample_rows):
    result = issues.filter_rows(sample_rows, {"Oversized", "Empty file"})
    assert sorted(r["kind"] for r in result) == ["Empty file", "Oversized"]


def test_search_ignores_upper_and_lower_case(sample_rows):
    assert [r["item"] for r in issues.filter_rows(sample_rows, query="CONTRACT")] == \
           ["docs/contract.pdf", "docs/contract_final.pdf"]


def test_search_needs_every_word(sample_rows):
    result = issues.filter_rows(sample_rows, query="logo identical")
    assert sorted(r["item"] for r in result) == ["images/logo.png", "images/logo_copy.png"]
    assert issues.filter_rows(sample_rows, query="logo banana") == []


def test_search_also_looks_at_the_details_and_the_kind(sample_rows):
    assert [r["item"] for r in issues.filter_rows(sample_rows, query="1095 days")] == ["misc/old_assets.zip"]
    assert len(issues.filter_rows(sample_rows, query="oversized")) == 1


def test_kind_and_search_work_together(sample_rows):
    result = issues.filter_rows(sample_rows, {"Duplicate"}, "images")
    assert [r["item"] for r in result] == ["images/logo.png", "images/logo_copy.png"]
    assert issues.filter_rows(sample_rows, {"Stale"}, "images") == []


def test_filtering_never_changes_the_original_list(sample_rows):
    before = list(sample_rows)
    issues.filter_rows(sample_rows, {"Stale"}, "csv")
    assert sample_rows == before


# --------------------------------------------------------------------------
# Sorting
# --------------------------------------------------------------------------

def test_sort_by_file_name_ignores_case(sample_rows):
    names = [r["item"] for r in issues.sort_rows(sample_rows, "item")]
    assert names == sorted(names, key=str.lower)


def test_sort_by_size_biggest_first(sample_rows):
    result = issues.sort_rows(sample_rows, "size", descending=True)
    assert result[0]["item"] == "images/hero_raw.png"
    assert result[-1]["size"] is None or result[-1]["size"] == 0     # rows without a size come last


def test_sort_by_size_smallest_first(sample_rows):
    result = issues.sort_rows(sample_rows, "size")
    assert result[0]["size"] is None                                   # "Presentations" has no size
    sizes = [r["size"] for r in result if r["size"] is not None]
    assert sizes == sorted(sizes)


def test_sort_by_kind_follows_the_standard_order(sample_rows):
    result = issues.sort_rows(list(reversed(sample_rows)), "kind")
    assert [r["kind"] for r in result] == [r["kind"] for r in sample_rows]


@pytest.mark.parametrize("column", ["kind", "item", "size", "details"])
def test_every_sort_column_works_and_keeps_all_rows(sample_rows, column):
    for descending in (False, True):
        assert len(issues.sort_rows(sample_rows, column, descending)) == len(sample_rows)