# File & Asset Organizer + Report Generator

A Python script that scans a project folder, categorizes every file, flags potential
issues, and generates a clean Markdown and/or HTML report with summary stats and
recommendations.

## Live Demo
[View the sample report](https://greatepee.github.io/file_organizer/)

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
  - Stale files that haven't been modified in a long time (default 365 days, configurable)
  - Confusing file names: copies (`logo_copy.png`, `Report (2).pdf`), messy versions
    (`final_FINAL_v2.docx`), leftover temporary files (`~$report.docx`, `.bak`), extra
    spaces and very long names
- **Generates reports** in Markdown, HTML (supports light and dark mode) and CSV.
  The CSV has one row per file with all its issues, ready to sort and filter in Excel.
- **Desktop app** with buttons, a results table and one-click report opening,
  which can be packaged as a double-click `.exe`.
- No external libraries needed. Uses only the Python standard library.

## Requirements

- Python 3.8 or newer

## Project Structure

```
file-organizer/
├── organizer.py              # scanning, analysis and report logic (command line)
├── app.py                    # desktop app (window with buttons)
├── tests/
│   └── test_organizer.py     # automated tests (pytest)
├── pytest.ini                # pytest settings
├── requirements-dev.txt      # tools needed for development (pytest)
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

### Option 1: Desktop app (easiest)
```bash
python app.py
```
1. Click **Browse...** and select the folder to scan.
2. Optionally change the size limit or report formats.
3. Click **Scan Folder**. The results appear in the window, with an
   **Issues** tab and a **Recommendations** tab.
4. Use **Open HTML Report**, **Open Markdown Report** or **Open Reports Folder**.

### Option 2: Interactive command line (pick folders with a window)
```bash
python organizer.py
```
1. A folder picker window opens. Select the folder you want to scan.
2. The report is generated in the `reports/` folder.
3. You are asked `Scan another folder? (y/n)`. Type `y` to pick another folder,
   or `n` to quit.

If no window can open, the script asks you to type the folder path instead.

### Option 3: Command line (scan one folder directly)
```bash
python organizer.py sample_project
python organizer.py "D:\MyProject"
```

Reports are saved as `reports/report_<folder name>.md`, `.html` and `.csv`, so
scanning several folders never overwrites an earlier report.

> On Windows, use `py` instead of `python` if `python` is not recognized.

## CSV Columns

| Column | Meaning |
|---|---|
| `path` | Location inside the scanned folder |
| `name`, `extension`, `category` | File name, its extension and its category |
| `size_bytes` | Size as a plain number (use this column to sort by size) |
| `size` | Size in readable form, like `11.4 MB` |
| `last_modified` | Date and time the file was last changed |
| `duplicate_group` | Files with the same number are identical copies |
| `issues` | Every problem found for the file, separated by `;` (empty = no problems) |

Files and folders that couldn't be read also get a row, with `Skipped:` and the reason
in the `issues` column.

## Building the .exe (Windows)

Turn the desktop app into a program anyone can double-click, without installing Python:
```bash
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name FileOrganizer app.py
```
The program is created at `dist/FileOrganizer.exe`. Reports are saved in a
`reports` folder next to the `.exe`.

- `--onefile` packs everything into a single `.exe`
- `--windowed` hides the black terminal window

Windows may show a "Windows protected your PC" warning because the program isn't
signed. Click **More info → Run anyway**.

## Command-Line Options

| Option | Description | Default |
|---|---|---|
| `folder` | Folder to scan. Leave it out for interactive mode | — |
| `-f`, `--format` | `md`, `html`, `csv`, `both` (md + html) or `all` | `both` |
| `-o`, `--output` | Custom output file name without extension | `reports/report_<folder>` |
| `--max-size` | Size limit in MB for the oversized check | `10` |
| `--stale-days` | Flag files not modified for this many days | `365` |

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
| Loose root file | `Screenshot (2).png` |
| Stale files | `data/budget.csv` (2 years old), `misc/old_assets.zip` (3 years old) |
| Bad file names | `images/logo_copy.png`, `Screenshot (2).png`, `docs/proposal_final_FINAL_v2.docx` |

## Running the Tests

The project has automated tests that check the scanning, duplicate detection, size
checks, skipped files, report generation and the sample folder results.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```
All tests should pass. Add `-v` to see each test by name.

## Customizing

Edit the configuration section at the top of `organizer.py`:
- `CATEGORIES` to add file extensions or new categories
- `EXPECTED_CATEGORIES` to change which asset types are checked as "missing"
- `DEFAULT_STALE_DAYS`, `MAX_NAME_LENGTH` and `VERSION_WORDS` to tune the stale and naming checks
- `IGNORE_DIRS` / `IGNORE_FILES` to skip folders like `.git` or `node_modules`