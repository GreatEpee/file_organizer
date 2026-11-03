#this file contains automated tests for organize mode (organize.py)
#these matter most: organize mode moves real files, so it must never lose anything

import os
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
# Choosing which changes to apply (the tick boxes in the preview)
# --------------------------------------------------------------------------

def test_applying_only_some_changes_leaves_the_rest_alone(tmp_path):
    make(tmp_path, "images/a.png", b"same")
    make(tmp_path, "images/b.png", b"same")
    make(tmp_path, "docs/empty.txt", b"")
    make(tmp_path, "loose.png", b"other")
    root, plan = plan_for(tmp_path)
    assert len(plan) == 3

    chosen = [p for p in plan if p["action"] != organize.REMOVE_EMPTY]   # the user unticks the empty file
    result = organize.apply_changes(root, chosen)

    assert len(result["done"]) == 2 and result["failed"] == []
    assert (tmp_path / "docs/empty.txt").exists()          # not ticked, so not touched
    assert (tmp_path / "images/loose.png").exists()          # the loose file was moved
    assert not (tmp_path / "images/b.png").exists()        # the duplicate was removed


def test_applying_nothing_changes_nothing(tmp_path):
    make(tmp_path, "images/a.png", b"same")
    make(tmp_path, "images/b.png", b"same")
    before = snapshot(tmp_path)
    root, _ = plan_for(tmp_path)
    result = organize.apply_changes(root, [])
    assert result == {"done": [], "failed": [], "log": None}
    assert snapshot(tmp_path) == before
    assert not (tmp_path / organize.BACKUP_DIR).exists()   # no empty backup folder left behind


def test_undo_after_a_partial_apply_restores_exactly_that(tmp_path):
    make(tmp_path, "images/a.png", b"same")
    make(tmp_path, "images/b.png", b"same")
    make(tmp_path, "loose.png", b"other")
    before = snapshot(tmp_path)
    root, plan = plan_for(tmp_path)
    organize.apply_changes(root, [p for p in plan if p["action"] == organize.MOVE_LOOSE])
    assert (tmp_path / "images/b.png").exists()            # the duplicate was left alone
    organize.undo_last(root)
    assert snapshot(tmp_path) == before


def test_a_kept_copy_is_never_lost_if_one_duplicate_is_left_in_place(tmp_path):
    for name in ["a.bin", "b.bin", "c.bin"]:
        make(tmp_path, f"data/{name}", b"x" * 50)
    root, plan = plan_for(tmp_path)
    assert len(plan) == 2                                  # 3 copies: keep 1, remove 2
    organize.apply_changes(root, plan[:1])                 # the user only ticks one of them
    assert len([p for p in (tmp_path / "data").iterdir()]) == 2   # one removed, two copies remain


# --------------------------------------------------------------------------
# Emptying the backup folder (the only thing that removes files for good)
# --------------------------------------------------------------------------

def organized(tmp_path):
    """A folder that has been organized once, so it has a backup folder. Returns its root."""
    make(tmp_path, "images/logo.png", b"same content")
    make(tmp_path, "images/logo_copy.png", b"same content")
    make(tmp_path, "docs/notes.txt", b"keep me")
    root, plan = plan_for(tmp_path)
    organize.apply_changes(root, plan)
    return root


def test_backup_info_when_there_is_no_backup(tmp_path):
    make(tmp_path, "a.txt")
    info = organize.backup_info(tmp_path)
    assert info == {"exists": False, "files": 0, "size": 0, "can_undo": False}


def test_backup_info_counts_removed_files_not_undo_logs(tmp_path):
    root = organized(tmp_path)
    info = organize.backup_info(root)
    assert info["exists"] is True
    assert info["files"] == 1                       # only logo_copy.png, not the undo log
    assert info["size"] >= len(b"same content")     # size includes everything stored
    assert info["can_undo"] is True


def test_empty_backup_frees_space_and_turns_off_undo(tmp_path):
    root = organized(tmp_path)
    result = organize.empty_backup(root)
    assert result["emptied"] is True
    assert result["files"] == 1 and result["freed"] >= len(b"same content")
    assert result["method"] == "deleted permanently"
    assert not (root / organize.BACKUP_DIR).exists()
    assert not organize.has_undo(root)
    assert organize.undo_last(root)["nothing_to_undo"] is True


def test_empty_backup_never_touches_the_real_files(tmp_path):
    root = organized(tmp_path)
    kept = snapshot(root)
    organize.empty_backup(root)
    assert snapshot(root) == kept
    assert (root / "images/logo.png").read_bytes() == b"same content"
    assert (root / "docs/notes.txt").read_bytes() == b"keep me"


def test_empty_backup_with_nothing_to_empty(tmp_path):
    make(tmp_path, "a.txt")
    result = organize.empty_backup(tmp_path)
    assert result == {"emptied": False, "files": 0, "freed": 0, "method": None}


def test_can_organize_again_after_emptying_the_backup(tmp_path):
    root = organized(tmp_path)
    organize.empty_backup(root)
    make(tmp_path, "images/extra.png", b"same content")     # a new duplicate appears
    root, plan = plan_for(tmp_path)
    assert organize.apply_changes(root, plan)["failed"] == []
    assert organize.has_undo(root)


def test_recycle_option_uses_the_recycle_bin_instead_of_deleting(tmp_path, monkeypatch):
    root = organized(tmp_path)
    sent = []
    monkeypatch.setattr(organize, "send_to_recycle_bin", lambda path: sent.append(Path(path).name))
    result = organize.empty_backup(root, recycle=True)
    assert sent == [organize.BACKUP_DIR]
    assert result["method"] == "Recycle Bin"
    assert (root / organize.BACKUP_DIR).exists()   # the fake recycle bin didn't remove it, so
                                                   # we know empty_backup didn't delete it itself


def test_if_the_recycle_bin_fails_nothing_is_deleted(tmp_path, monkeypatch):
    root = organized(tmp_path)

    def broken(path):
        raise OSError("Recycle Bin is not available")

    monkeypatch.setattr(organize, "send_to_recycle_bin", broken)
    with pytest.raises(OSError):
        organize.empty_backup(root, recycle=True)
    assert organize.backup_info(root)["files"] == 1   # backup untouched
    assert organize.has_undo(root)                    # undo still works


def test_recycle_bin_is_refused_on_other_systems(tmp_path, monkeypatch):
    monkeypatch.setattr(organize, "can_use_recycle_bin", lambda: False)
    with pytest.raises(OSError):
        organize.send_to_recycle_bin(tmp_path)


def test_refuses_to_remove_a_symlinked_backup_folder(tmp_path):
    elsewhere = tmp_path / "important_elsewhere"
    make(elsewhere, "precious.txt", b"do not delete")
    project = tmp_path / "project"
    project.mkdir()
    try:
        os.symlink(elsewhere, project / organize.BACKUP_DIR, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system doesn't allow creating symlinks")
    with pytest.raises(OSError, match="Refusing"):
        organize.empty_backup(project)
    assert (elsewhere / "precious.txt").read_bytes() == b"do not delete"


def test_cli_clean_backup_cancel_removes_nothing(tmp_path, monkeypatch, capsys):
    root = organized(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert organize.run_clean_cli(root) is False
    assert "Nothing was removed" in capsys.readouterr().out
    assert organize.backup_info(root)["exists"]


def test_cli_clean_backup_confirm_removes_it(tmp_path, monkeypatch, capsys):
    root = organized(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert organize.run_clean_cli(root) is True
    out = capsys.readouterr().out
    assert "undo" in out and "freed" in out
    assert not organize.backup_info(root)["exists"]


def test_cli_clean_backup_with_no_backup(tmp_path, capsys):
    make(tmp_path, "a.txt")
    assert organize.run_clean_cli(tmp_path) is True
    assert "no backup folder" in capsys.readouterr().out


def test_cli_recycle_flag_gives_a_clear_error_off_windows(tmp_path, monkeypatch, capsys):
    root = organized(tmp_path)
    monkeypatch.setattr(organize, "can_use_recycle_bin", lambda: False)
    assert organize.run_clean_cli(root, recycle=True) is False
    assert "only works on Windows" in capsys.readouterr().out
    assert organize.backup_info(root)["exists"]


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