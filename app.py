#this file is the desktop app (a window with buttons) for the file organizer

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import organizer

# Save reports next to the app. Works both for "python app.py" and for the .exe
if getattr(sys, "frozen", False):          # running as a PyInstaller .exe
    APP_DIR = Path(sys.executable).parent
else:                                      # running as a normal Python script
    APP_DIR = Path(__file__).resolve().parent
REPORTS_DIR = APP_DIR / "reports"

WARN_COLOR = "#c2410c"   # orange: a problem was found
OK_COLOR = "#15803d"     # green: no problems


def open_path(path):
    """Open a file or folder with the computer's default program."""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


class OrganizerApp:
    def __init__(self, root):
        self.root = root
        self.folder = tk.StringVar()
        self.max_size = tk.StringVar(value="10")
        self.stale_days = tk.StringVar(value=str(organizer.DEFAULT_STALE_DAYS))
        self.want_html = tk.BooleanVar(value=True)
        self.want_md = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Choose a folder to get started.")
        self.results = queue.Queue()   # the background scan puts its result here
        self.report_paths = []

        root.title("File & Asset Organizer")
        root.geometry("940x680")
        root.minsize(700, 540)
        self.build_ui()

    # ------------------------------------------------------------------
    # Building the window
    # ------------------------------------------------------------------

    def build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="File & Asset Organizer", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(main, text="Scan a folder to find duplicates, oversized files and other issues.",
                  foreground="gray").pack(anchor="w", pady=(0, 12))

        # Step 1: choose a folder
        step1 = ttk.LabelFrame(main, text=" 1. Choose a folder ", padding=10)
        step1.pack(fill="x")
        ttk.Entry(step1, textvariable=self.folder, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(step1, text="Browse...", command=self.choose_folder).pack(side="left", padx=(8, 0))

        # Step 2: options
        step2 = ttk.LabelFrame(main, text=" 2. Options ", padding=10)
        step2.pack(fill="x", pady=10)
        ttk.Label(step2, text="Flag files larger than").pack(side="left")
        ttk.Spinbox(step2, from_=1, to=100000, width=7, textvariable=self.max_size).pack(side="left", padx=4)
        ttk.Label(step2, text="MB").pack(side="left")
        ttk.Separator(step2, orient="vertical").pack(side="left", fill="y", padx=16)
        ttk.Label(step2, text="Stale after").pack(side="left")
        ttk.Spinbox(step2, from_=1, to=10000, width=6, textvariable=self.stale_days).pack(side="left", padx=4)
        ttk.Label(step2, text="days").pack(side="left")
        ttk.Separator(step2, orient="vertical").pack(side="left", fill="y", padx=16)
        ttk.Label(step2, text="Report format:").pack(side="left")
        ttk.Checkbutton(step2, text="HTML", variable=self.want_html).pack(side="left", padx=4)
        ttk.Checkbutton(step2, text="Markdown", variable=self.want_md).pack(side="left")

        # Step 3: scan button, progress bar and status text
        step3 = ttk.Frame(main)
        step3.pack(fill="x")
        self.scan_btn = ttk.Button(step3, text="3. Scan Folder", command=self.start_scan, state="disabled")
        self.scan_btn.pack(side="left", ipadx=10, ipady=4)
        self.progress = ttk.Progressbar(step3, mode="indeterminate", length=160)
        self.progress.pack(side="left", padx=12)
        ttk.Label(step3, textvariable=self.status).pack(side="left")

        # Buttons to open the reports (packed first so they always stay visible)
        actions = ttk.Frame(main)
        actions.pack(side="bottom", fill="x", pady=(10, 0))  # pinned to the bottom
        self.open_html_btn = ttk.Button(actions, text="Open HTML Report", state="disabled",
                                        command=lambda: self.open_report(".html"))
        self.open_html_btn.pack(side="left")
        self.open_md_btn = ttk.Button(actions, text="Open Markdown Report", state="disabled",
                                      command=lambda: self.open_report(".md"))
        self.open_md_btn.pack(side="left", padx=8)
        ttk.Button(actions, text="Open Reports Folder", command=self.open_reports_folder).pack(side="left")

        # Results area
        results = ttk.LabelFrame(main, text=" Results ", padding=10)
        results.pack(fill="both", expand=True, pady=(12, 0))

        # Summary numbers in a row
        stats_row = ttk.Frame(results)
        stats_row.pack(fill="x")
        self.stat_labels = {}
        for i, name in enumerate(["Files scanned", "Total size", "Duplicate groups", "Oversized",
                                  "Empty", "Stale", "Bad names", "Skipped"]):
            box = ttk.Frame(stats_row, padding=(0, 0, 20, 0))
            box.grid(row=0, column=i, sticky="w")
            value = ttk.Label(box, text="-", font=("Segoe UI", 14, "bold"))
            value.pack(anchor="w")
            ttk.Label(box, text=name, foreground="gray").pack(anchor="w")
            self.stat_labels[name] = value

        # Two tabs: a table of issues, and the recommendations
        self.tabs = ttk.Notebook(results)
        self.tabs.pack(fill="both", expand=True, pady=(10, 0))
        table_frame = ttk.Frame(self.tabs, padding=4)
        recs_frame = ttk.Frame(self.tabs, padding=4)
        self.tabs.add(table_frame, text="Issues")
        self.tabs.add(recs_frame, text="Recommendations")
        self.table = ttk.Treeview(table_frame, columns=("issue", "item", "details"),
                                  show="headings", height=8)
        for col, title, width in [("issue", "Issue", 130), ("item", "File / Item", 360),
                                  ("details", "Details", 280)]:
            self.table.heading(col, text=title)
            self.table.column(col, width=width, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")

        # Recommendations: a read-only text box with a scrollbar, so long lists never get cut off
        bg = ttk.Style().lookup("TFrame", "background")
        self.recs_text = tk.Text(recs_frame, wrap="word", height=6, relief="flat", background=bg,
                                 font=("Segoe UI", 10), padx=4, pady=4, spacing3=8)
        recs_scroll = ttk.Scrollbar(recs_frame, orient="vertical", command=self.recs_text.yview)
        self.recs_text.configure(yscrollcommand=recs_scroll.set)
        self.recs_text.pack(side="left", fill="both", expand=True)
        recs_scroll.pack(side="left", fill="y")
        self.set_recommendations(["Run a scan to see recommendations."])

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select a folder to scan")
        if folder:
            self.folder.set(str(Path(folder)))   # Path() shows Windows-style backslashes on Windows
            self.scan_btn.config(state="normal")
            self.status.set("Ready to scan.")

    def start_scan(self):
        formats = [f for f, on in (("html", self.want_html.get()), ("md", self.want_md.get())) if on]
        if not formats:
            messagebox.showwarning("No report format", "Please tick at least one report format.")
            return
        try:
            max_size = float(self.max_size.get())
            if max_size <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid size", "Please enter a size limit greater than 0.")
            return
        try:
            stale_days = int(self.stale_days.get())
            if stale_days <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid days", "Please enter a whole number of days greater than 0.")
            return

        self.set_busy(True)
        # Scan in a background thread so the window doesn't freeze on big folders
        threading.Thread(target=self.scan_worker, args=(self.folder.get(), formats, max_size, stale_days),
                         daemon=True).start()
        self.root.after(100, self.check_results)

    def scan_worker(self, folder, formats, max_size, stale_days):
        """Runs in the background thread. Never touches the window directly."""
        try:
            result = organizer.generate_reports(folder, formats, max_size, reports_dir=REPORTS_DIR,
                                                stale_days=stale_days)
            self.results.put(("ok", result))
        except Exception as err:
            self.results.put(("error", err))

    def check_results(self):
        """Runs on the main thread every 100 ms until the scan has finished."""
        try:
            kind, payload = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self.check_results)
            return
        self.set_busy(False)
        if kind == "error":
            self.status.set("Scan failed.")
            messagebox.showerror("Scan failed", str(payload))
        else:
            self.show_results(*payload)

    def set_busy(self, busy):
        if busy:
            self.progress.config(mode="indeterminate", value=0)
            self.progress.start(12)
            self.scan_btn.config(state="disabled")
            self.status.set("Scanning... this can take a while for big folders.")
        else:
            self.progress.stop()
            self.progress.config(mode="determinate", value=100)   # show a full bar when finished
            self.scan_btn.config(state="normal")

    def show_results(self, a, recs, paths):
        human = organizer.human_size
        counts = {
            "Files scanned": (a["total_files"], None),
            "Total size": (human(a["total_size"]), None),
            "Duplicate groups": (len(a["duplicates"]), len(a["duplicates"])),
            "Oversized": (len(a["oversized"]), len(a["oversized"])),
            "Empty": (len(a["empty"]), len(a["empty"])),
            "Stale": (len(a["stale"]), len(a["stale"])),
            "Bad names": (len(a["bad_names"]), len(a["bad_names"])),
            "Skipped": (len(a["skipped"]), len(a["skipped"])),
        }
        for name, (text, problems) in counts.items():
            color = "" if problems is None else (WARN_COLOR if problems else OK_COLOR)
            self.stat_labels[name].config(text=str(text), foreground=color)

        # Fill the issues table
        self.table.delete(*self.table.get_children())
        rows = []
        for group in a["duplicates"]:
            rows.append(("Duplicate", ", ".join(f["rel"] for f in group),
                         f"{len(group)} copies, {human(group[0]['size'])} each"))
        rows += [("Oversized", f["rel"], human(f["size"])) for f in a["oversized"]]
        rows += [("Empty file", f["rel"], "0 bytes") for f in a["empty"]]
        rows += [("Unknown type", f["rel"], f"Extension: {f['ext']}") for f in a["unknown"]]
        rows += [("Stale", f["rel"], f"Last modified {f['modified']:%Y-%m-%d}") for f in a["stale"]]
        rows += [("Bad name", f["rel"], "; ".join(f["problems"])) for f in a["bad_names"]]
        rows += [("Missing type", c, "No files of this type found") for c in a["missing"]]
        rows += [("Skipped", x["rel"], x["reason"]) for x in a["skipped"]]
        issue_count = len(rows)
        if not rows:
            rows.append(("No issues", "-", "The folder looks well organized"))
        for row in rows:
            self.table.insert("", "end", values=row)

        self.set_recommendations([f"\u2022 {r}" for r in recs])
        self.tabs.tab(0, text=f"Issues ({issue_count})")
        self.tabs.tab(1, text=f"Recommendations ({len(recs)})")

        self.report_paths = paths
        has = {p.suffix for p in paths}
        self.open_html_btn.config(state="normal" if ".html" in has else "disabled")
        self.open_md_btn.config(state="normal" if ".md" in has else "disabled")
        self.status.set("Done! Report saved.")

    def set_recommendations(self, lines):
        self.recs_text.config(state="normal")      # unlock to change the text
        self.recs_text.delete("1.0", "end")
        self.recs_text.insert("1.0", "\n".join(lines))
        self.recs_text.config(state="disabled")    # lock again so users can't type in it

    def open_report(self, suffix):
        path = next((p for p in self.report_paths if p.suffix == suffix), None)
        if not path:
            return
        if suffix == ".html":
            webbrowser.open(path.as_uri())       # opens in the default browser
            return
        try:
            open_path(path)
        except OSError:
            # Windows has no default app for .md files, so fall back to Notepad
            if sys.platform.startswith("win"):
                subprocess.Popen(["notepad", str(path)])
            else:
                messagebox.showinfo("Report location", f"The report is saved at:\n{path}")

    def open_reports_folder(self):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        open_path(REPORTS_DIR)


def main():
    # Sharp (not blurry) text on Windows screens with display scaling
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    OrganizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()