#this file is organize mode: it plans fixes, applies them safely, and can undo them
#nothing is ever deleted permanently: removed files are moved into a backup folder

import json
import shutil
from datetime import datetime
from pathlib import Path

import organizer

BACKUP_DIR = organizer.BACKUP_DIR_NAME
LOGS_DIR = f"{BACKUP_DIR}/undo_logs"

# Where loose root files are moved, by category
CATEGORY_FOLDERS = {
    "Images": "images",
    "Documents": "docs",
    "PDFs": "docs",
    "Spreadsheets": "data",
    "Presentations": "presentations",
    "Audio": "audio",
    "Video": "video",
}

# Action names (shown to the user)
REMOVE_DUPLICATE = "Remove duplicate"
REMOVE_EMPTY = "Remove empty file"
MOVE_LOOSE = "Move loose file"


class SkipAction(Exception):
    """Raised when a planned change is no longer safe to do (e.g. the file changed after the scan)."""


# --------------------------------------------------------------------------
# Step 1: plan the changes (nothing is touched here)
# --------------------------------------------------------------------------

def analyze_folder(folder, max_size=10, stale_days=organizer.DEFAULT_STALE_DAYS):
    """Scan a folder and analyze it, without writing any report."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"'{folder}' is not a folder or does not exist.")
    files, skipped = organizer.scan_folder(root)
    return root, organizer.analyze(files, skipped, max_size, stale_days)


def choose_keeper(group):
    """Pick which copy to keep: the cleanest name first, then the shortest path."""
    return min(group, key=lambda f: (bool(organizer.check_name(f["name"])),  # clean names first
                                     f["rel"].count("/"),                    # less nested first
                                     len(f["name"]),                         # shorter name first
                                     f["rel"].lower()))                      # then alphabetical


def free_destination(root, rel, taken):
    """Return rel, or rel with _1, _2 ... added, so we never overwrite an existing file."""
    candidate = Path(rel)
    n = 1
    while (root / candidate).exists() or candidate.as_posix() in taken:
        candidate = Path(rel).with_name(f"{Path(rel).stem}_{n}{Path(rel).suffix}")
        n += 1
    return candidate.as_posix()


def plan_changes(root, analysis, duplicates=True, empty=True, loose=True):
    """Build the list of changes to make. This only plans; it does not move anything."""
    root = Path(root)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup = f"{BACKUP_DIR}/{stamp}"
    plan, handled, taken = [], set(), set()

    if duplicates:
        for group in analysis["duplicates"]:
            keeper = choose_keeper(group)
            for f in group:
                if f is keeper:
                    continue
                plan.append({"action": REMOVE_DUPLICATE, "src": f["rel"], "dst": f"{backup}/{f['rel']}",
                             "keep": keeper["rel"], "reason": f"Same content as {keeper['rel']}"})
                handled.add(f["rel"])

    if empty:
        for f in analysis["empty"]:
            plan.append({"action": REMOVE_EMPTY, "src": f["rel"], "dst": f"{backup}/{f['rel']}",
                         "reason": "File is empty (0 bytes)"})
            handled.add(f["rel"])

    if loose:
        for f in analysis["files"]:
            if f["rel"] in handled or not organizer.is_loose(f):
                continue
            folder = CATEGORY_FOLDERS.get(f["category"], "misc")
            dst = free_destination(root, f"{folder}/{f['name']}", taken)
            taken.add(dst)
            plan.append({"action": MOVE_LOOSE, "src": f["rel"], "dst": dst,
                         "reason": f"{f['category']} file sitting in the root folder"})
    return plan


# --------------------------------------------------------------------------
# Step 2: apply the plan (with safety checks right before each change)
# --------------------------------------------------------------------------

def check_still_safe(root, item):
    """Re-check a planned change, because files may have changed since the scan."""
    src, dst = root / item["src"], root / item["dst"]
    if not src.is_file():
        raise SkipAction("The file no longer exists")
    if dst.exists():
        raise SkipAction(f"Something already exists at {item['dst']}")
    if item["action"] == REMOVE_DUPLICATE:
        keeper = root / item["keep"]
        if not keeper.is_file():
            raise SkipAction(f"The copy being kept ({item['keep']}) no longer exists")
        if organizer.file_hash(keeper) != organizer.file_hash(src):
            raise SkipAction("The file was changed and is no longer an identical copy")
    if item["action"] == REMOVE_EMPTY and src.stat().st_size != 0:
        raise SkipAction("The file is no longer empty")


def apply_changes(root, plan):
    """Apply each planned change. Returns {"done": [...], "failed": [(item, reason)], "log": path}."""
    root = Path(root)
    done, failed = [], []
    log = {"created": datetime.now().isoformat(timespec="seconds"), "moves": [], "created_dirs": []}

    for item in plan:
        try:
            check_still_safe(root, item)
            dst = root / item["dst"]
            # remember which folders we create, so undo can remove them again
            missing, parent = [], dst.parent
            while not parent.exists():
                missing.append(parent.relative_to(root).as_posix())
                parent = parent.parent
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root / item["src"]), str(dst))
            log["created_dirs"] += missing
            log["moves"].append({"from": item["src"], "to": item["dst"]})
            done.append(item)
        except SkipAction as err:
            failed.append((item, str(err)))
        except OSError as err:
            failed.append((item, organizer.describe_error(err)))

    log_path = None
    if log["moves"]:   # save the undo log only if something actually changed
        logs = root / LOGS_DIR
        logs.mkdir(parents=True, exist_ok=True)
        log_path = logs / f"undo_{datetime.now():%Y-%m-%d_%H-%M-%S_%f}.json"
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return {"done": done, "failed": failed, "log": log_path}


# --------------------------------------------------------------------------
# Step 3: undo
# --------------------------------------------------------------------------

def latest_undo_log(root):
    logs = sorted((Path(root) / LOGS_DIR).glob("undo_*.json"))
    return logs[-1] if logs else None


def has_undo(root):
    return latest_undo_log(root) is not None


def remove_empty_dirs(root, rel_dirs):
    """Remove the given folders if they are empty, deepest first."""
    for rel in sorted(set(rel_dirs), key=lambda r: r.count("/"), reverse=True):
        path = Path(root) / rel
        try:
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
        except OSError:
            pass


def undo_last(root):
    """Put back every file moved by the last organize. Returns {"restored": n, "failed": [...]}."""
    root = Path(root)
    log_path = latest_undo_log(root)
    if not log_path:
        return {"restored": 0, "failed": [], "nothing_to_undo": True}

    log = json.loads(log_path.read_text(encoding="utf-8"))
    restored, failed, remaining = 0, [], []
    for move in reversed(log["moves"]):   # reverse order = exact opposite of what happened
        original, current = root / move["from"], root / move["to"]
        if not current.exists():
            failed.append((move, f"{move['to']} no longer exists"))
            remaining.append(move)
        elif original.exists():
            failed.append((move, f"{move['from']} is already taken by another file"))
            remaining.append(move)
        else:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), str(original))
            restored += 1

    remove_empty_dirs(root, log["created_dirs"])
    if remaining:
        # keep a log of what couldn't be restored, so the user can try again later
        log["moves"] = list(reversed(remaining))
        log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    else:
        log_path.unlink()
    # tidy up the backup folder if it is now empty
    backup = root / BACKUP_DIR
    if backup.exists():
        all_dirs = [p.relative_to(root).as_posix() for p in backup.rglob("*") if p.is_dir()]
        remove_empty_dirs(root, all_dirs + [BACKUP_DIR])
    return {"restored": restored, "failed": failed, "nothing_to_undo": False}


# --------------------------------------------------------------------------
# Command-line version
# --------------------------------------------------------------------------

def run_cli(folder, undo=False, max_size=10, stale_days=organizer.DEFAULT_STALE_DAYS):
    try:
        root, analysis = analyze_folder(folder, max_size, stale_days)
    except NotADirectoryError as err:
        print(f"Error: {err}")
        return False

    if undo:
        result = undo_last(root)
        if result["nothing_to_undo"]:
            print("Nothing to undo for this folder.")
            return True
        print(f"Restored {result['restored']} file(s).")
        for move, reason in result["failed"]:
            print(f"  Could not restore {move['from']}: {reason}")
        return not result["failed"]

    plan = plan_changes(root, analysis)
    if not plan:
        print("Nothing to organize. The folder is already tidy.")
        return True

    print(f"\nPreview: {len(plan)} change(s) for {root}\n")
    for item in plan:
        print(f"  {item['action']:<18} {item['src']}  ->  {item['dst']}")
    print(f"\nNothing is deleted: removed files go into the '{BACKUP_DIR}' folder.")
    answer = input("Apply these changes? (y/n): ").strip().lower()
    if answer not in ("y", "yes"):
        print("Cancelled. Nothing was changed.")
        return False

    result = apply_changes(root, plan)
    print(f"\nDone: {len(result['done'])} change(s) applied.")
    for item, reason in result["failed"]:
        print(f"  Skipped {item['src']}: {reason}")
    if result["log"]:
        print(f"To undo:  python organizer.py \"{folder}\" --undo")
    return True