# File & Asset Organizer + Report Generator

A Python script that scans a project folder, categorizes every file, flags potential
issues, and generates a clean Markdown and/or HTML report with summary stats and
recommendations.

## Features

- **Categorizes files** into Images, PDFs, Documents, Spreadsheets, Presentations,
  Audio, Video, Archives, Code, Fonts, and Other.
- **Flags issues:**
  - Duplicate files (detected by content using SHA-256, not just by name)
  - Oversized files (default limit 10 MB, configurable)
  - Empty files
  - Files with unknown or missing extensions
  - Missing common asset types (Images, PDFs, Documents, Spreadsheets, Presentations)
  - Loose files sitting in the root folder
  - Unreadable files and folders (no permission, locked, broken links), listed in a
    "Skipped Files" section instead of being silently ignored
- **Generates reports** in Markdown, HTML (supports light and dark mode), or both.
- No external libraries needed. Uses only the Python standard library.

## Requirements

- Python 3.8 or newer

## Project Structure

```
file-organizer/
├── organizer.py              # main script
├── create_sample_folder.py   # builds a test folder with mixed files
├── README.md
├── reports/                  # generated reports go here
└── sample_project/           # test folder, created by create_sample_folder.py
```

## How to Run

First, create the sample test folder (optional, but useful for testing):
```bash
python create_sample_folder.py
```
This always saves `sample_project/` inside the project folder, next to the script,
no matter which directory your terminal is in. Running it again deletes the old
`sample_project/` and builds a fresh one, so test results stay the same.

### Option 1: Interactive mode (pick folders with a window)
```bash
python organizer.py
```
1. A folder picker window opens. Select the folder you want to scan.
2. The report is generated in the `reports/` folder.
3. You are asked `Scan another folder? (y/n)`. Type `y` to pick another folder,
   or `n` to quit.

If no window can open, the script asks you to type the folder path instead.

### Option 2: Command line (scan one folder directly)
```bash
python organizer.py sample_project
python organizer.py "D:\MyProject"
```

Reports are saved as `reports/report_<folder name>.md` and `.html`, so scanning
several folders never overwrites an earlier report.

> On Windows, use `py` instead of `python` if `python` is not recognized.

## Options

| Option | Description | Default |
|---|---|---|
| `folder` | Folder to scan. Leave it out for interactive mode | — |
| `-f`, `--format` | `md`, `html`, or `both` | `both` |
| `-o`, `--output` | Custom output file name without extension | `reports/report_<folder>` |
| `--max-size` | Size limit in MB for the oversized check | `10` |

Example:
```bash
python organizer.py sample_project --format html --max-size 5
```

## What the Sample Folder Tests

Every sample file is a real, valid file (images, PDF, Word, Excel, zip), so they all
open normally in their usual apps.

To test, run `python organizer.py` and select the `sample_project` folder in the
picker window (or run `python organizer.py sample_project`).

| Test case | File(s) |
|---|---|
| Duplicates | `logo.png` / `logo_copy.png`, `contract.pdf` / `contract_final.pdf` |
| Oversized file | `images/hero_raw.png` (about 11.5 MB) |
| Empty file | `docs/empty_draft.txt` |
| Unknown types | `misc/LICENSE`, `misc/export.dat` |
| Missing asset type | No presentations included |
| Loose root file | `screenshot.png` |

## Customizing

Edit the configuration section at the top of `organizer.py`:
- `CATEGORIES` to add file extensions or new categories
- `EXPECTED_CATEGORIES` to change which asset types are checked as "missing"
- `IGNORE_DIRS` / `IGNORE_FILES` to skip folders like `.git` or `node_modules`