#this file contains automated tests for organize mode (organize.py)
#these matter most: organize mode moves real files, so it must never lose anything

from pathlib import Path

import pytest

import create_sample_folder
import organize
import organizer


def make(root, rel_path, content=b"x"):
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return path


def snapshot(root):
    """Every file under root (except the backup folder) with its content, to compare before/after."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(Path(root).rglob("*"))
            if p.is_file() and organize.BACKUP_DIR not in p.parts}


def plan_for(root, **options):
    root, analysis = organize.analyze_folder(root)
    return root, organize.plan_changes(root, analysis, **options)


# --------------------------------------------------------------------------
# Planning (nothing should change on disk)
# --------------------------------------------------------------------------

def test_planning_does_not_touch_any_file(tmp_path):
    make(tmp_path, "a.png", b"same")
    make(tmp_path, "b.png", b"same")
    make(tmp_path, "empty.txt", b"")
    before = snapshot(tmp_path)
    _, plan = plan_for(tmp_path)
    assert len(plan) > 0
    assert snapshot(tmp_path) == before


def test_keeps_the_copy_with_the_cleanest_name(tmp_path):
    make(tmp_path, "images/logo_copy.png", b"same")
    make(tmp_path, "images/logo.png", b"same")
    make(tmp_path, "images/Copy of logo.png", b"same")
    _, plan = plan_for(tmp_path)
    removed = sorted(p["src"] for p in plan if p["action"] == organize.REMOVE_DUPLICATE)
    assert removed == ["images/Copy of logo.png", "images/logo_copy.png"]
    assert all(p["keep"] == "images/logo.png" for p in plan)


def test_loose_files_go_to_category_folders(tmp_path):
    make(tmp_path, "photo.jpg", "1")
    make(tmp_path, "notes.docx", "2")
    make(tmp_path, "budget.xlsx", "3")
    make(tmp_path, "build.py", "4")        # code is not "loose", so it stays
    _, plan = plan_for(tmp_path)
    moves = {p["src"]: p["dst"] for p in plan if p["action"] == organize.MOVE_LOOSE}
    assert moves == {"photo.jpg": "images/photo.jpg", "notes.docx": "docs/notes.docx",
                     "budget.xlsx": "data/budget.xlsx"}


@pytest.mark.parametrize("name", ["README.md", "readme.txt", "LICENSE.md", "CHANGELOG.md",
                                  "CONTRIBUTING.md"])
def test_project_files_are_never_moved_out_of_root(tmp_path, name):
    make(tmp_path, name, "keep me here")
    _, plan = plan_for(tmp_path)
    assert plan == []


def test_never_plans_to_overwrite_an_existing_file(tmp_path):
    make(tmp_path, "images/photo.jpg", "already here")
    make(tmp_path, "photo.jpg", "loose one")
    _, plan = plan_for(tmp_path)
    assert plan[0]["dst"] == "images/photo_1.jpg"


def test_options_turn_each_fix_on_or_off(tmp_path):
    make(tmp_path, "images/a.png", b"same")
    make(tmp_path, "images/b.png", b"same")
    make(tmp_path, "docs/empty.txt", b"")
    make(tmp_path, "loose.png", b"other")
    _, plan = plan_for(tmp_path, duplicates=False, empty=False, loose=True)
    assert [p["action"] for p in plan] == [organize.MOVE_LOOSE]
    _, plan = plan_for(tmp_path, duplicates=False, empty=False, loose=False)
    assert plan == []


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------

def test_apply_moves_files_and_keeps_removed_ones_in_backup(tmp_path):
    make(tmp_path, "images/logo.png", b"same")
    make(tmp_path, "images/logo_copy.png", b"same")
    make(tmp_path, "shot.png", b"loose")
    root, plan = plan_for(tmp_path)
    result = organize.apply_changes(root, plan)

    assert len(result["done"]) == 2 and result["failed"] == []
    assert sorted(snapshot(tmp_path)) == ["images/logo.png", "images/shot.png"]
    backed_up = [p.name for p in (tmp_path / organize.BACKUP_DIR).rglob("*.png")]
    assert backed_up == ["logo_copy.png"]          # not deleted, just moved aside
    assert result["log"].exists()


def test_backup_folder_is_ignored_by_later_scans(tmp_path):
    make(tmp_path, "images/a.png", b"same")
    make(tmp_path, "images/b.png", b"same")
    root, plan = plan_for(tmp_path)
    organize.apply_changes(root, plan)
    _, analysis = organize.analyze_folder(tmp_path)
    assert analysis["total_files"] == 1
    assert analysis["duplicates"] == []


def test_skips_a_duplicate_that_was_edited_after_the_scan(tmp_path):
    make(tmp_path, "images/a.png", b"same")
    copy = make(tmp_path, "images/b.png", b"same")
    root, plan = plan_for(tmp_path)
    copy.write_bytes(b"edited!")                   # someone changed it before Apply was clicked
    result = organize.apply_changes(root, plan)
    assert result["done"] == []
    assert "no longer an identical copy" in result["failed"][0][1]
    assert copy.read_bytes() == b"edited!"         # still there, untouched


def test_skips_a_file_that_was_deleted_after_the_scan(tmp_path):
    loose = make(tmp_path, "photo.png", b"x")
    root, plan = plan_for(tmp_path)
    loose.unlink()
    result = organize.apply_changes(root, plan)
    assert result["failed"][0][1] == "The file no longer exists"
    assert result["log"] is None                   # nothing changed, so no undo log


def test_skips_an_empty_file_that_got_content(tmp_path):
    empty = make(tmp_path, "docs/draft.txt", b"")
    root, plan = plan_for(tmp_path)
    empty.write_bytes(b"now it has text")
    result = organize.apply_changes(root, plan)
    assert result["failed"][0][1] == "The file is no longer empty"


# --------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------

def test_undo_restores_everything_exactly(tmp_path):
    make(tmp_path, "images/logo.png", b"same")
    make(tmp_path, "images/logo_copy.png", b"same")
    make(tmp_path, "docs/empty.txt", b"")
    make(tmp_path, "Screenshot (2).png", b"loose")
    make(tmp_path, "report.pdf", b"pdf")
    before = snapshot(tmp_path)

    root, plan = plan_for(tmp_path)
    organize.apply_changes(root, plan)
    assert snapshot(tmp_path) != before
    result = organize.undo_last(root)

    assert result["restored"] == len(plan) and result["failed"] == []
    assert snapshot(tmp_path) == before                       # every file back, same content
    assert not (tmp_path / organize.BACKUP_DIR).exists()       # backup folder cleaned up
    assert not (tmp_path / "data").exists()                    # folders it created are removed
    assert not organize.has_undo(root)


def test_undo_does_not_overwrite_a_new_file(tmp_path):
    make(tmp_path, "photo.png", b"original")
    root, plan = plan_for(tmp_path)
    organize.apply_changes(root, plan)
    make(tmp_path, "photo.png", b"a new file the user made")   # original spot is taken now
    result = organize.undo_last(root)

    assert result["restored"] == 0
    assert "already taken" in result["failed"][0][1]
    assert (tmp_path / "photo.png").read_bytes() == b"a new file the user made"
    assert (tmp_path / "images/photo.png").read_bytes() == b"original"
    assert organize.has_undo(root)                             # can try again later


def test_undo_twice_reverses_two_organizes(tmp_path):
    make(tmp_path, "one.png", b"1")
    before = snapshot(tmp_path)
    root, plan = plan_for(tmp_path)
    organize.apply_changes(root, plan)
    after_first = snapshot(tmp_path)
    make(tmp_path, "two.png", b"2")
    root, plan = plan_for(tmp_path)
    organize.apply_changes(root, plan)

    organize.undo_last(root)                                   # undoes the second organize
    assert snapshot(tmp_path) == {**after_first, "two.png": b"2"}
    organize.undo_last(root)                                   # then the first
    assert snapshot(tmp_path) == {**before, "two.png": b"2"}


def test_nothing_to_undo(tmp_path):
    result = organize.undo_last(tmp_path)
    assert result["nothing_to_undo"] is True


# --------------------------------------------------------------------------
# End-to-end with the sample folder, and the command line
# --------------------------------------------------------------------------

def test_sample_folder_organize_and_undo(tmp_path, monkeypatch):
    sample = tmp_path / "sample_project"
    monkeypatch.setattr(create_sample_folder, "ROOT", sample)
    create_sample_folder.main()
    before = snapshot(sample)

    root, plan = plan_for(sample)
    assert sorted((p["action"], p["src"]) for p in plan) == [
        (organize.MOVE_LOOSE, "Screenshot (2).png"),
        (organize.REMOVE_DUPLICATE, "docs/contract_final.pdf"),
        (organize.REMOVE_DUPLICATE, "images/logo_copy.png"),
        (organize.REMOVE_EMPTY, "docs/empty_draft.txt"),
    ]
    organize.apply_changes(root, plan)
    _, analysis = organize.analyze_folder(sample)
    assert analysis["total_files"] == 14
    assert analysis["duplicates"] == [] and analysis["empty"] == []

    organize.undo_last(root)
    assert snapshot(sample) == before


def test_cli_cancel_changes_nothing(tmp_path, monkeypatch, capsys):
    make(tmp_path, "a.png", b"same")
    make(tmp_path, "b.png", b"same")
    before = snapshot(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert organize.run_cli(tmp_path) is False
    assert "Nothing was changed" in capsys.readouterr().out
    assert snapshot(tmp_path) == before