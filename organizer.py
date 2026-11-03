#this file organizes and generates a report

import argparse
import csv
import hashlib
import html
import io
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Configuration

CATEGORIES = {
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".ico", ".heic"},
    "PDFs": {".pdf"},
    "Documents": {".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".pages"},
    "Spreadsheets": {".xls", ".xlsx", ".xlsm", ".csv", ".tsv", ".ods", ".numbers"},
    "Presentations": {".ppt", ".pptx", ".key", ".odp"},
    "Audio": {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"},
    "Video": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml",
             ".sh", ".bat", ".java", ".c", ".cpp", ".h", ".sql"},
    "Fonts": {".ttf", ".otf", ".woff", ".woff2"},
}

# Asset types a typical project folder is expected to contain.
EXPECTED_CATEGORIES = ["Images", "PDFs", "Documents", "Spreadsheets", "Presentations"]

# Organize mode moves removed files here (inside the scanned folder) so they can be restored
BACKUP_DIR_NAME = "_organizer_backup"

IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode",
               BACKUP_DIR_NAME}

# Types of files that shouldn't sit loose in the root folder
LOOSE_CATEGORIES = {"Images", "Documents", "PDFs", "Spreadsheets", "Presentations", "Audio", "Video"}

# Files that belong in the root of a project, so they are never called "loose" or moved
KEEP_IN_ROOT = ("readme", "license", "licence", "changelog", "contributing", "code_of_conduct",
                "security", "authors")
IGNORE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# Files not modified for this many days are flagged as stale (can be changed)
DEFAULT_STALE_DAYS = 365

# Names longer than this are hard to read and can break on some systems
MAX_NAME_LENGTH = 100

# Words that, together with "final", show a messy versioning habit (e.g. final_v2, final_new)
VERSION_WORDS = {"new", "latest", "updated", "revised", "old"}

# Build a quick lookup: extension -> category
EXT_TO_CATEGORY = {ext: cat for cat, exts in CATEGORIES.items() for ext in exts}


# Helpers

def human_size(num_bytes):
    """Convert bytes to a readable string like '12.3 MB'."""
    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def categorize(path):
    """Return the category name for a file based on its extension."""
    return EXT_TO_CATEGORY.get(path.suffix.lower(), "Other")


def file_hash(path, chunk_size=1024 * 1024):
    """SHA-256 hash of a file, read in chunks so big files don't fill memory."""
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha.update(chunk)
    return sha.hexdigest()


def check_name(name):
    """Return a list of problems with a file name (an empty list means the name is fine)."""
    problems = []
    stem = Path(name).stem
    words = [w for w in re.split(r"[\s_\-.()]+", stem.lower()) if w]   # "final_FINAL_v2" -> final, final, v2

    if "copy" in words or re.search(r"\(\d+\)\s*$", stem):
        problems.append("Looks like a copy")
    if words.count("final") >= 2 or ("final" in words and any(
            w in VERSION_WORDS or re.fullmatch(r"v\d+", w) for w in words)):
        problems.append("Messy version name (like final_v2)")
    if name.startswith("~$") or Path(name).suffix.lower() in {".tmp", ".bak"}:
        problems.append("Temporary or backup file")
    if name != name.strip() or "  " in name:
        problems.append("Extra spaces in the name")
    if len(name) > MAX_NAME_LENGTH:
        problems.append(f"Name over {MAX_NAME_LENGTH} characters long")
    return problems


def is_loose(f):
    """True if a file sits directly in the root folder but belongs in a sub-folder."""
    return ("/" not in f["rel"] and f["category"] in LOOSE_CATEGORIES
            and not f["name"].lower().startswith(KEEP_IN_ROOT))


def describe_error(err):
    """Turn an OS error into a short reason a normal user can understand."""
    if isinstance(err, PermissionError):
        return "Permission denied (no access, or in use by another program)"
    if isinstance(err, FileNotFoundError):
        return "Not found (broken shortcut or link, or deleted during the scan)"
    return err.strerror or str(err)


def skipped_entry(rel, kind, err, note=""):
    """Build one record for the 'Skipped' section of the report."""
    return {"rel": rel, "kind": kind, "reason": describe_error(err) + note}


# Scanning and analysis

def scan_folder(root, skip_paths=()):
    """Walk the folder and collect info about every file.
    Returns (files, skipped): skipped lists every file or folder that couldn't be read."""
    files = []
    skipped = []
    skip = {Path(p).resolve() for p in skip_paths}

    def on_folder_error(err):
        # os.walk calls this when it can't open a folder (e.g. no permission)
        try:
            rel = Path(err.filename).relative_to(root).as_posix()
        except (TypeError, ValueError):
            rel = str(err.filename)
        skipped.append(skipped_entry(rel, "Folder", err, " - nothing inside it was scanned"))

    for dirpath, dirnames, filenames in os.walk(root, onerror=on_folder_error):
        # Prune ignored folders in place so os.walk doesn't enter them
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
        for name in sorted(filenames):
            if name in IGNORE_FILES:
                continue
            full = Path(dirpath) / name
            if full.resolve() in skip:
                continue
            try:
                stat = full.stat()
            except OSError as err:
                # Unreadable file: record it instead of hiding it
                skipped.append(skipped_entry(full.relative_to(root).as_posix(), "File", err))
                continue
            files.append({
                "path": full,
                "rel": full.relative_to(root).as_posix(),
                "name": name,
                "ext": full.suffix.lower() or "(none)",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime),
                "category": categorize(full),
            })
    return files, skipped


def find_duplicates(files):
    """Group identical files. Compare sizes first, then hash only size matches.
    Returns (duplicate_groups, skipped): skipped lists files that couldn't be opened."""
    skipped = []
    by_size = defaultdict(list)
    for f in files:
        if f["size"] > 0:
            by_size[f["size"]].append(f)

    by_hash = defaultdict(list)
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        for f in same_size:
            try:
                by_hash[file_hash(f["path"])].append(f)
            except OSError as err:
                # File is listed in the inventory, but couldn't be opened to compare contents
                skipped.append(skipped_entry(f["rel"], "File", err, " - not checked for duplicates"))
    return [group for group in by_hash.values() if len(group) > 1], skipped


def analyze(files, skipped, max_size_mb, stale_days=DEFAULT_STALE_DAYS):
    """Compute stats and issues from the scanned file list."""
    by_category = defaultdict(list)
    for f in files:
        by_category[f["category"]].append(f)

    max_bytes = max_size_mb * 1024 * 1024
    stale_cutoff = datetime.now() - timedelta(days=stale_days)
    duplicates, hash_skipped = find_duplicates(files)
    wasted = sum(g[0]["size"] * (len(g) - 1) for g in duplicates)

    return {
        "files": files,
        "total_files": len(files),
        "total_size": sum(f["size"] for f in files),
        "by_category": dict(sorted(by_category.items(), key=lambda kv: -len(kv[1]))),
        "duplicates": duplicates,
        "wasted_bytes": wasted,
        "oversized": sorted([f for f in files if f["size"] > max_bytes], key=lambda f: -f["size"]),
        "empty": [f for f in files if f["size"] == 0],
        "missing": [c for c in EXPECTED_CATEGORIES if c not in by_category],
        "unknown": by_category.get("Other", []),
        "largest": sorted(files, key=lambda f: -f["size"])[:5],
        "skipped": skipped + hash_skipped,
        "stale": sorted([f for f in files if f["modified"] < stale_cutoff], key=lambda f: f["modified"]),
        "bad_names": [{**f, "problems": check_name(f["name"])} for f in files if check_name(f["name"])],
        "stale_days": stale_days,
        "max_size_mb": max_size_mb,
    }


def build_recommendations(a):
    """Turn the analysis into a list of plain-English recommendations."""
    recs = []
    if a["skipped"]:
        recs.append(f"{len(a['skipped'])} item(s) could not be read, so parts of this report may be "
                    "incomplete. Check their permissions or close any program using them, then scan again.")
    if a["duplicates"]:
        recs.append(f"Remove duplicate copies: {len(a['duplicates'])} group(s) of identical files "
                    f"are wasting {human_size(a['wasted_bytes'])}. Keep one copy of each.")
    if a["oversized"]:
        recs.append(f"Compress or archive {len(a['oversized'])} file(s) larger than "
                    f"{a['max_size_mb']:g} MB (e.g. resize images, export lighter PDFs, "
                    f"or move raw files to cloud storage).")
    if a["empty"]:
        recs.append(f"Delete or fill in {len(a['empty'])} empty file(s); they are usually leftovers.")
    if a["missing"]:
        recs.append("Check whether these common asset types should exist in the project: "
                    + ", ".join(a["missing"]) + ".")
    if a["unknown"]:
        recs.append(f"Review {len(a['unknown'])} file(s) with unknown or missing extensions "
                    "and rename or remove them.")
    if a["stale"]:
        recs.append(f"Archive or delete {len(a['stale'])} file(s) that haven't been changed in over "
                    f"{a['stale_days']} days, if they are no longer needed.")
    if a["bad_names"]:
        recs.append(f"Rename {len(a['bad_names'])} file(s) with confusing names (copies, 'final_v2' "
                    "versions, temporary files) so everyone can tell which version is current.")
    loose = [f for f in a["files"] if is_loose(f)]
    if loose:
        recs.append(f"Move {len(loose)} loose file(s) from the root folder into sub-folders "
                    "(e.g. images/, docs/) to keep the project tidy.")
    if not recs:
        recs.append("No issues found. The folder looks well organized.")
    return recs


# Report rendering

def md_escape(text):
    return str(text).replace("|", "\\|")


def render_markdown(root, a, recs):
    lines = []
    add = lines.append
    total = a["total_files"] or 1

    add("# File & Asset Inventory Report\n")
    add(f"**Folder:** `{root}`  ")
    add(f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}\n")

    add("## Summary\n")
    add("| Metric | Value |\n|---|---|")
    add(f"| Files scanned | {a['total_files']} |")
    add(f"| Total size | {human_size(a['total_size'])} |")
    add(f"| Categories found | {len(a['by_category'])} |")
    add(f"| Duplicate groups | {len(a['duplicates'])} ({human_size(a['wasted_bytes'])} wasted) |")
    add(f"| Oversized files (> {a['max_size_mb']:g} MB) | {len(a['oversized'])} |")
    add(f"| Empty files | {len(a['empty'])} |")
    add(f"| Skipped (unreadable) | {len(a['skipped'])} |")
    add(f"| Stale files (> {a['stale_days']} days old) | {len(a['stale'])} |")
    add(f"| Naming problems | {len(a['bad_names'])} |")
    add(f"| Missing asset types | {', '.join(a['missing']) or 'None'} |\n")

    add("## Files by Category\n")
    add("| Category | Files | Size | Share |\n|---|---:|---:|---:|")
    for cat, items in a["by_category"].items():
        size = sum(f["size"] for f in items)
        add(f"| {cat} | {len(items)} | {human_size(size)} | {len(items) / total:.0%} |")
    add("")

    add("## Issues\n")
    add("### Duplicates")
    if a["duplicates"]:
        for i, group in enumerate(a["duplicates"], 1):
            add(f"- **Group {i}** ({human_size(group[0]['size'])} each): "
                + ", ".join(f"`{f['rel']}`" for f in group))
    else:
        add("- None found")
    add("\n### Oversized Files")
    if a["oversized"]:
        for f in a["oversized"]:
            add(f"- `{f['rel']}` ({human_size(f['size'])})")
    else:
        add("- None found")
    add("\n### Empty Files")
    add("\n".join(f"- `{f['rel']}`" for f in a["empty"]) or "- None found")
    add("\n### Unknown File Types")
    add("\n".join(f"- `{f['rel']}` (extension: {f['ext']})" for f in a["unknown"]) or "- None found")
    add("\n### Missing Common Asset Types")
    add("\n".join(f"- {c}" for c in a["missing"]) or "- None, all expected types are present")
    add("\n### Stale Files")
    add("\n".join(f"- `{f['rel']}` (last modified {f['modified']:%Y-%m-%d}, "
                  f"{(datetime.now() - f['modified']).days} days ago)" for f in a["stale"]) or "- None found")
    add("\n### Naming Problems")
    add("\n".join(f"- `{f['rel']}`: {'; '.join(f['problems'])}" for f in a["bad_names"]) or "- None found")
    add("\n### Skipped Files")
    add("\n".join(f"- `{x['rel']}` ({x['kind']}): {x['reason']}" for x in a["skipped"])
        or "- None, every file was read successfully")
    add("")

    add("## Recommendations\n")
    for i, r in enumerate(recs, 1):
        add(f"{i}. {r}")
    add("")

    add("## Largest Files\n")
    add("| File | Size |\n|---|---:|")
    for f in a["largest"]:
        add(f"| `{md_escape(f['rel'])}` | {human_size(f['size'])} |")
    add("")

    add("## Full Inventory\n")
    for cat, items in a["by_category"].items():
        add(f"### {cat} ({len(items)})\n")
        add("| File | Type | Size | Last Modified |\n|---|---|---:|---|")
        for f in items:
            add(f"| `{md_escape(f['rel'])}` | {f['ext']} | {human_size(f['size'])} "
                f"| {f['modified']:%Y-%m-%d %H:%M} |")
        add("")
    return "\n".join(lines)


HTML_STYLE = """
:root { --bg:#f7f7f8; --card:#fff; --text:#1d1d1f; --muted:#6b6b70; --line:#e3e3e6;
        --accent:#2f6fed; --warn:#c2410c; --ok:#15803d; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#141416; --card:#1e1e21; --text:#ececef; --muted:#9a9aa2; --line:#2e2e33;
          --accent:#6b9bff; --warn:#fb923c; --ok:#4ade80; } }
* { box-sizing:border-box; }
body { margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       background:var(--bg); color:var(--text); line-height:1.5; }
main { max-width:1000px; margin:0 auto; padding:32px 20px; }
h1 { margin:0 0 4px; } h2 { margin-top:36px; border-bottom:1px solid var(--line); padding-bottom:6px; }
.meta { color:var(--muted); margin-bottom:24px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }
.card .n { font-size:1.6rem; font-weight:700; } .card .l { color:var(--muted); font-size:.85rem; }
.card.warn .n { color:var(--warn); } .card.ok .n { color:var(--ok); }
.table-wrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; background:var(--card); border-radius:8px; overflow:hidden; }
th,td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; font-size:.92rem; }
th { background:var(--line); } td.r, th.r { text-align:right; }
code { font-family:ui-monospace,Consolas,monospace; font-size:.88em; }
.bar { height:8px; background:var(--accent); border-radius:4px; }
li { margin:4px 0; } .none { color:var(--ok); }
"""


def render_html(root, a, recs):
    e = html.escape
    total = a["total_files"] or 1
    parts = []
    add = parts.append

    def card(label, value, state=""):
        add(f'<div class="card {state}"><div class="n">{e(str(value))}</div>'
            f'<div class="l">{e(label)}</div></div>')

    def file_list(items, fmt):
        if not items:
            return '<p class="none">None found</p>'
        return "<ul>" + "".join(f"<li>{fmt(x)}</li>" for x in items) + "</ul>"

    add(f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>File Inventory Report</title><style>{HTML_STYLE}</style></head><body><main>")
    add("<h1>File &amp; Asset Inventory Report</h1>")
    add(f"<div class='meta'>Folder: <code>{e(str(root))}</code> &middot; "
        f"Generated {datetime.now():%Y-%m-%d %H:%M}</div>")

    add("<div class='cards'>")
    card("Files scanned", a["total_files"])
    card("Total size", human_size(a["total_size"]))
    card("Categories", len(a["by_category"]))
    card("Duplicate groups", len(a["duplicates"]), "warn" if a["duplicates"] else "ok")
    card(f"Oversized (> {a['max_size_mb']:g} MB)", len(a["oversized"]), "warn" if a["oversized"] else "ok")
    card("Empty files", len(a["empty"]), "warn" if a["empty"] else "ok")
    card("Skipped (unreadable)", len(a["skipped"]), "warn" if a["skipped"] else "ok")
    card(f"Stale (> {a['stale_days']} days)", len(a["stale"]), "warn" if a["stale"] else "ok")
    card("Naming problems", len(a["bad_names"]), "warn" if a["bad_names"] else "ok")
    add("</div>")

    add("<h2>Files by Category</h2><div class='table-wrap'><table>"
        "<tr><th>Category</th><th class='r'>Files</th><th class='r'>Size</th><th>Share</th></tr>")
    for cat, items in a["by_category"].items():
        share = len(items) / total
        add(f"<tr><td>{e(cat)}</td><td class='r'>{len(items)}</td>"
            f"<td class='r'>{human_size(sum(f['size'] for f in items))}</td>"
            f"<td><div class='bar' style='width:{share * 100:.0f}%'></div> {share:.0%}</td></tr>")
    add("</table></div>")

    add("<h2>Issues</h2><h3>Duplicates</h3>")
    add(file_list(a["duplicates"], lambda g: f"{human_size(g[0]['size'])} each: "
                  + ", ".join(f"<code>{e(f['rel'])}</code>" for f in g)))
    add("<h3>Oversized Files</h3>")
    add(file_list(a["oversized"], lambda f: f"<code>{e(f['rel'])}</code> ({human_size(f['size'])})"))
    add("<h3>Empty Files</h3>")
    add(file_list(a["empty"], lambda f: f"<code>{e(f['rel'])}</code>"))
    add("<h3>Unknown File Types</h3>")
    add(file_list(a["unknown"], lambda f: f"<code>{e(f['rel'])}</code> (extension: {e(f['ext'])})"))
    add("<h3>Missing Common Asset Types</h3>")
    add(file_list(a["missing"], e))
    add("<h3>Stale Files</h3>")
    add(file_list(a["stale"], lambda f: f"<code>{e(f['rel'])}</code> (last modified "
                  f"{f['modified']:%Y-%m-%d}, {(datetime.now() - f['modified']).days} days ago)"))
    add("<h3>Naming Problems</h3>")
    add(file_list(a["bad_names"], lambda f: f"<code>{e(f['rel'])}</code>: {e('; '.join(f['problems']))}"))
    add("<h3>Skipped Files</h3>")
    add(file_list(a["skipped"], lambda x: f"<code>{e(x['rel'])}</code> ({e(x['kind'])}): {e(x['reason'])}"))

    add("<h2>Recommendations</h2><ol>" + "".join(f"<li>{e(r)}</li>" for r in recs) + "</ol>")

    add("<h2>Full Inventory</h2>")
    for cat, items in a["by_category"].items():
        add(f"<h3>{e(cat)} ({len(items)})</h3><div class='table-wrap'><table>"
            "<tr><th>File</th><th>Type</th><th class='r'>Size</th><th>Last Modified</th></tr>")
        for f in items:
            add(f"<tr><td><code>{e(f['rel'])}</code></td><td>{e(f['ext'])}</td>"
                f"<td class='r'>{human_size(f['size'])}</td><td>{f['modified']:%Y-%m-%d %H:%M}</td></tr>")
        add("</table></div>")

    add("</main></body></html>")
    return "\n".join(parts)


# CSV export: one row per file, so the data can be sorted and filtered in Excel

CSV_COLUMNS = ["path", "name", "extension", "category", "size_bytes", "size",
               "last_modified", "duplicate_group", "issues"]


def build_csv_rows(a):
    """One row per file with every issue it has, plus one row per item that couldn't be read."""
    dup_group = {f["rel"]: i for i, group in enumerate(a["duplicates"], 1) for f in group}
    oversized = {f["rel"] for f in a["oversized"]}
    stale = {f["rel"] for f in a["stale"]}
    name_problems = {f["rel"]: f["problems"] for f in a["bad_names"]}
    skipped = {x["rel"]: x for x in a["skipped"]}

    rows = []
    for f in sorted(a["files"], key=lambda f: f["rel"].lower()):
        rel = f["rel"]
        issues = []
        if rel in dup_group:
            issues.append(f"Duplicate (group {dup_group[rel]})")
        if rel in oversized:
            issues.append("Oversized")
        if f["size"] == 0:
            issues.append("Empty file")
        if f["category"] == "Other":
            issues.append("Unknown type")
        if rel in stale:
            issues.append("Stale")
        issues += name_problems.get(rel, [])
        if is_loose(f):
            issues.append("Loose file in root folder")
        if rel in skipped:   # listed, but couldn't be opened for the duplicate check
            issues.append(skipped.pop(rel)["reason"])
        rows.append({
            "path": rel, "name": f["name"], "extension": f["ext"], "category": f["category"],
            "size_bytes": f["size"], "size": human_size(f["size"]),
            "last_modified": f"{f['modified']:%Y-%m-%d %H:%M}",
            "duplicate_group": dup_group.get(rel, ""),
            "issues": "; ".join(issues),
        })

    # Files and folders that couldn't be read at all get their own rows
    for x in skipped.values():
        rows.append({"path": x["rel"], "name": Path(x["rel"]).name, "extension": "",
                     "category": x["kind"], "size_bytes": "", "size": "", "last_modified": "",
                     "duplicate_group": "", "issues": f"Skipped: {x['reason']}"})
    return rows


def render_csv(a):
    """Return the CSV text. The csv module handles commas and quotes inside file names."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(build_csv_rows(a))
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

REPORTS_DIR = Path("reports")


def pick_folder():
    """Open a folder picker window. Falls back to typing a path if no window can open."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        window = tk.Tk()
        window.withdraw()                      # hide the empty main window
        window.attributes("-topmost", True)    # keep the picker in front of VS Code
        folder = filedialog.askdirectory(title="Select a folder to scan")
        window.destroy()
        return folder or None
    except Exception:
        path = input("Enter the folder path to scan (or press Enter to quit): ").strip().strip('"')
        return path or None


def generate_reports(folder, formats=("md", "html"), max_size=10, output_name=None,
                     reports_dir=REPORTS_DIR, stale_days=DEFAULT_STALE_DAYS):
    """Scan one folder and write its report(s). Shared by the command line and the desktop app.
    Returns (analysis, recommendations, report_paths). Raises NotADirectoryError for a bad folder."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"'{folder}' is not a folder or does not exist.")

    # Name reports after the scanned folder so different scans don't overwrite each other
    if not output_name:
        safe = re.sub(r"[^\w-]", "_", root.name) or "drive_root"
        output_name = str(Path(reports_dir) / f"report_{safe}")
    Path(output_name).parent.mkdir(parents=True, exist_ok=True)
    outputs = [Path(f"{output_name}.{f}") for f in formats]

    files, skipped = scan_folder(root, skip_paths=outputs)  # don't count our own report
    analysis = analyze(files, skipped, max_size, stale_days)
    recs = build_recommendations(analysis)

    for f, out in zip(formats, outputs):
        if f == "csv":
            # utf-8-sig adds a marker so Excel shows non-English names correctly;
            # newline="" stops Windows from adding blank lines between rows
            with open(out, "w", encoding="utf-8-sig", newline="") as fh:
                fh.write(render_csv(analysis))
        else:
            content = render_markdown(root, analysis, recs) if f == "md" else render_html(root, analysis, recs)
            out.write_text(content, encoding="utf-8")
    return analysis, recs, [out.resolve() for out in outputs]


# What each --format option produces
FORMAT_CHOICES = {
    "md": ["md"], "html": ["html"], "csv": ["csv"],
    "both": ["md", "html"],
    "all": ["md", "html", "csv"],
}


def run_report(folder, fmt, output_name, max_size, stale_days=DEFAULT_STALE_DAYS):
    """Command-line version: scan one folder and print the results. Returns True on success."""
    formats = FORMAT_CHOICES[fmt]
    try:
        print(f"\nScanning {Path(folder).expanduser().resolve()} ...")
        analysis, recs, outputs = generate_reports(folder, formats, max_size, output_name,
                                                   stale_days=stale_days)
    except NotADirectoryError as err:
        print(f"Error: {err}")
        return False

    for out in outputs:
        print(f"Report written: {out}")
    print(f"\n{analysis['total_files']} files, {human_size(analysis['total_size'])} | "
          f"{len(analysis['duplicates'])} duplicate group(s), {len(analysis['oversized'])} oversized, "
          f"{len(analysis['empty'])} empty, {len(analysis['stale'])} stale, "
          f"{len(analysis['bad_names'])} bad names, {len(analysis['skipped'])} skipped, missing: "
          f"{', '.join(analysis['missing']) or 'none'}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Scan a folder and generate a file inventory report.")
    parser.add_argument("folder", nargs="?",
                        help="Folder to scan. Leave it out to choose folders with a picker window.")
    parser.add_argument("-f", "--format", choices=list(FORMAT_CHOICES), default="both",
                        help="Report format: md, html, csv, both (md + html) or all (default: both)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output file name without extension (default: reports/report_<folder>)")
    parser.add_argument("--max-size", type=float, default=10,
                        help="Flag files larger than this many MB (default: 10)")
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                        help=f"Flag files not modified for this many days (default: {DEFAULT_STALE_DAYS})")
    parser.add_argument("--organize", action="store_true",
                        help="Preview and apply fixes: remove duplicates and empty files, move loose files")
    parser.add_argument("--undo", action="store_true",
                        help="Undo the last organize on this folder")
    parser.add_argument("--clean-backup", action="store_true",
                        help="Empty the backup folder left by organize mode (undo is no longer possible)")
    parser.add_argument("--recycle-bin", action="store_true",
                        help="With --clean-backup: send the backup to the Recycle Bin (Windows only)")
    args = parser.parse_args()

    # Emptying the backup folder
    if args.clean_backup:
        if not args.folder:
            sys.exit("Error: please give a folder, e.g.  python organizer.py sample_project --clean-backup")
        import organize
        sys.exit(0 if organize.run_clean_cli(args.folder, recycle=args.recycle_bin) else 1)

    # Organize mode and undo (imported here because organize.py itself imports this file)
    if args.organize or args.undo:
        if not args.folder:
            sys.exit("Error: please give a folder, e.g.  python organizer.py sample_project --organize")
        import organize
        ok = organize.run_cli(args.folder, undo=args.undo, max_size=args.max_size,
                              stale_days=args.stale_days)
        if ok and args.organize:
            run_report(args.folder, args.format, args.output, args.max_size, args.stale_days)
        sys.exit(0 if ok else 1)

    # Folder given on the command line: scan it once and stop
    if args.folder:
        ok = run_report(args.folder, args.format, args.output, args.max_size, args.stale_days)
        sys.exit(0 if ok else 1)

    # No folder given: interactive mode, scan as many folders as the user wants
    print("=== File & Asset Organizer ===")
    print("Select a folder in the window that opens (cancel to quit).")
    while True:
        folder = pick_folder()
        if not folder:
            print("No folder selected. Goodbye!")
            break
        run_report(folder, args.format, args.output, args.max_size, args.stale_days)
        again = input("\nScan another folder? (y/n): ").strip().lower()
        if again not in ("y", "yes"):
            print("Goodbye!")
            break


if __name__ == "__main__":
    main()