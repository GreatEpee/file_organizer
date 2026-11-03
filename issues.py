#this file turns the scan results into a flat list of rows (one row per file per problem)
#and filters / sorts them. The desktop app shows these rows. Keeping this code out of the
#window code makes it easy to test.

from datetime import datetime

import organizer

# Every kind of problem, in the order they are listed
KINDS = ["Duplicate", "Oversized", "Empty file", "Unknown type", "Stale", "Bad name",
         "Missing type", "Skipped"]

# Short names for the filter buttons
LABELS = {
    "Duplicate": "Duplicates", "Oversized": "Oversized", "Empty file": "Empty",
    "Unknown type": "Unknown type", "Stale": "Stale", "Bad name": "Bad names",
    "Missing type": "Missing type", "Skipped": "Skipped",
}


def make_row(kind, item, size, details, path):
    """path is where the item is inside the scanned folder (None if it isn't a real file)."""
    return {"kind": kind, "item": item, "size": size, "details": details, "path": path}


def build_rows(a, now=None):
    """Turn the analysis from organizer.analyze() into rows. A file with two problems
    (for example a duplicate with a bad name) appears twice, once per problem."""
    now = now or datetime.now()
    rows = []

    for n, group in enumerate(a["duplicates"], 1):
        for f in sorted(group, key=lambda f: f["rel"].lower()):
            rows.append(make_row("Duplicate", f["rel"], f["size"],
                                 f"Group {n}: {len(group)} identical copies", f["rel"]))
    for f in a["oversized"]:
        rows.append(make_row("Oversized", f["rel"], f["size"],
                             f"Over the {a['max_size_mb']:g} MB limit", f["rel"]))
    for f in a["empty"]:
        rows.append(make_row("Empty file", f["rel"], 0, "0 bytes", f["rel"]))
    for f in a["unknown"]:
        rows.append(make_row("Unknown type", f["rel"], f["size"], f"Extension: {f['ext']}", f["rel"]))
    for f in a["stale"]:
        rows.append(make_row("Stale", f["rel"], f["size"],
                             f"Last modified {f['modified']:%Y-%m-%d} ({(now - f['modified']).days} days ago)",
                             f["rel"]))
    for f in a["bad_names"]:
        rows.append(make_row("Bad name", f["rel"], f["size"], "; ".join(f["problems"]), f["rel"]))
    for category in a["missing"]:
        rows.append(make_row("Missing type", category, None, "No files of this type found", None))
    for x in a["skipped"]:
        rows.append(make_row("Skipped", x["rel"], None, f"{x['kind']}: {x['reason']}", x["rel"]))
    return rows


def count_by_kind(rows):
    counts = {}
    for r in rows:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return counts


def filter_rows(rows, kinds=(), query=""):
    """Keep rows of the chosen kinds (all kinds if none are chosen) whose text contains every
    word of the search query. Matching ignores upper/lower case."""
    terms = query.lower().split()
    kept = []
    for r in rows:
        if kinds and r["kind"] not in kinds:
            continue
        if terms:
            text = f"{r['item']} {r['details']} {r['kind']}".lower()
            if not all(term in text for term in terms):
                continue
        kept.append(r)
    return kept


SORT_KEYS = {
    "kind": lambda r: KINDS.index(r["kind"]),
    "item": lambda r: r["item"].lower(),
    "size": lambda r: -1 if r["size"] is None else r["size"],   # rows without a size go last when descending
    "details": lambda r: r["details"].lower(),
}


def sort_rows(rows, column, descending=False):
    return sorted(rows, key=SORT_KEYS[column], reverse=descending)


def size_text(row):
    return "" if row["size"] is None else organizer.human_size(row["size"])