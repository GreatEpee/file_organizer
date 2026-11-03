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

import organize
import organizer

# Save reports next to the app. Works both for "python app.py" and for the .exe
if getattr(sys, "frozen", False):          # running as a PyInstaller .exe
    APP_DIR = Path(sys.executable).parent
else:                                      # running as a normal Python script
    APP_DIR = Path(__file__).resolve().parent
REPORTS_DIR = APP_DIR / "reports"

WARN_COLOR = "#c2410c"   # orange: a problem was found
OK_COLOR = "#15803d"     # green: no problems

# Button colors: (normal, when the mouse is over it)
BLUE = ("#2563eb", "#1d4ed8")
GREEN = ("#16a34a", "#15803d")
RED = ("#dc2626", "#b91c1c")
DISABLED_BG = "#b4b4b4"


def open_path(path):
    """Open a file or folder with the computer's default program."""
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        subprocess.run(["xdg-open", str(path)])


class ColorButton(tk.Button):
    """A colored button. ttk buttons ignore colors on Windows, so this uses a classic tk.Button.
    Use set_enabled() instead of config(state=...) so the color turns gray when disabled."""

    def __init__(self, parent, colors, **kwargs):
        self.color, self.hover = colors
        super().__init__(parent, fg="white", activeforeground="white", disabledforeground="#f2f2f2",
                         activebackground=self.hover, relief="flat", bd=0, padx=14, pady=6,
                         font=("Segoe UI", 10, "bold"), cursor="hand2", **kwargs)
        self.bind("<Enter>", self.on_hover)
        self.bind("<Leave>", self.on_leave)
        self.set_enabled(kwargs.get("state") != "disabled")

    def set_enabled(self, enabled):
        self.config(state="normal" if enabled else "disabled",
                    bg=self.color if enabled else DISABLED_BG,
                    cursor="hand2" if enabled else "arrow")

    def on_hover(self, event):
        if self["state"] != "disabled":
            self.config(bg=self.hover)

    def on_leave(self, event):
        if self["state"] != "disabled":
            self.config(bg=self.color)


def make_table(parent, columns):
    """A table (Treeview) with a scrollbar. columns = [(id, title, width), ...]"""
    frame = ttk.Frame(parent)
    table = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=8)
    for col, title, width in columns:
        table.heading(col, text=title)
        table.column(col, width=width, anchor="w")
    scroll = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
    table.configure(yscrollcommand=scroll.set)
    table.pack(side="left", fill="both", expand=True)
    scroll.pack(side="left", fill="y")
    return frame, table


class OrganizerApp:
    def __init__(self, root):
        self.root = root
        self.folder = tk.StringVar()
        self.max_size = tk.StringVar(value="10")
        self.stale_days = tk.StringVar(value=str(organizer.DEFAULT_STALE_DAYS))
        self.want_html = tk.BooleanVar(value=True)
        self.want_md = tk.BooleanVar(value=True)
        self.want_csv = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Choose a folder to get started.")
        self.report_paths = []
        self.last_root = None       # folder of the last scan (used by organize mode)
        self.last_analysis = None   # results of the last scan

        root.title("File & Asset Organizer")
        root.geometry("940x700")
        root.minsize(760, 560)
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

        # Step 2: options (two rows so nothing gets cut off)
        step2 = ttk.LabelFrame(main, text=" 2. Options ", padding=10)
        step2.pack(fill="x", pady=10)
        limits = ttk.Frame(step2)
        limits.pack(fill="x")
        ttk.Label(limits, text="Flag files larger than").pack(side="left")
        ttk.Spinbox(limits, from_=1, to=100000, width=7, textvariable=self.max_size).pack(side="left", padx=4)
        ttk.Label(limits, text="MB").pack(side="left")
        ttk.Separator(limits, orient="vertical").pack(side="left", fill="y", padx=16)
        ttk.Label(limits, text="Stale after").pack(side="left")
        ttk.Spinbox(limits, from_=1, to=10000, width=6, textvariable=self.stale_days).pack(side="left", padx=4)
        ttk.Label(limits, text="days").pack(side="left")

        formats_row = ttk.Frame(step2)
        formats_row.pack(fill="x", pady=(8, 0))
        ttk.Label(formats_row, text="Report formats:").pack(side="left")
        ttk.Checkbutton(formats_row, text="HTML", variable=self.want_html).pack(side="left", padx=4)
        ttk.Checkbutton(formats_row, text="Markdown", variable=self.want_md).pack(side="left", padx=4)
        ttk.Checkbutton(formats_row, text="CSV (Excel)", variable=self.want_csv).pack(side="left", padx=4)

        # Step 3: scan button, progress bar and status text
        step3 = ttk.Frame(main)
        step3.pack(fill="x")
        self.scan_btn = ColorButton(step3, BLUE, text="3. Scan Folder", command=self.start_scan,
                                    state="disabled")
        self.scan_btn.pack(side="left")
        self.progress = ttk.Progressbar(step3, mode="determinate", value=0, length=160)  # empty until a scan
        self.progress.pack(side="left", padx=12)
        ttk.Label(step3, textvariable=self.status).pack(side="left")

        # Bottom buttons (packed before the results so they always stay visible)
        actions = ttk.Frame(main)
        actions.pack(side="bottom", fill="x", pady=(10, 0))
        self.open_html_btn = ttk.Button(actions, text="Open HTML Report", state="disabled",
                                        command=lambda: self.open_report(".html"))
        self.open_html_btn.pack(side="left")
        self.open_md_btn = ttk.Button(actions, text="Open Markdown", state="disabled",
                                      command=lambda: self.open_report(".md"))
        self.open_md_btn.pack(side="left", padx=8)
        self.open_csv_btn = ttk.Button(actions, text="Open CSV (Excel)", state="disabled",
                                       command=lambda: self.open_report(".csv"))
        self.open_csv_btn.pack(side="left")
        ttk.Button(actions, text="Reports Folder", command=self.open_reports_folder).pack(side="left", padx=8)
        self.undo_btn = ColorButton(actions, RED, text="Undo Last Organize", state="disabled",
                                    command=self.undo_organize)
        self.undo_btn.pack(side="right")
        self.organize_btn = ColorButton(actions, GREEN, text="Organize...", state="disabled",
                                        command=lambda: OrganizeDialog(self))
        self.organize_btn.pack(side="right", padx=8)

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
        table_frame, self.table = make_table(self.tabs, [("issue", "Issue", 130), ("item", "File / Item", 360),
                                                         ("details", "Details", 280)])
        recs_frame = ttk.Frame(self.tabs, padding=4)
        self.tabs.add(table_frame, text="Issues")
        self.tabs.add(recs_frame, text="Recommendations")

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
    # Running work in the background
    # ------------------------------------------------------------------

    def run_in_background(self, work, on_done, busy_text):
        """Run work() in a background thread so the window never freezes, then call
        on_done(ok, result) on the main thread. Only the main thread may touch the window,
        because tkinter isn't thread-safe, so the thread hands its result over in a queue."""
        results = queue.Queue()

        def worker():
            try:
                results.put((True, work()))
            except Exception as err:
                results.put((False, err))

        def check():   # runs on the main thread every 100 ms until the work is finished
            try:
                ok, payload = results.get_nowait()
            except queue.Empty:
                self.root.after(100, check)
                return
            self.set_busy(False)
            on_done(ok, payload)

        self.set_busy(True, busy_text)
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, check)

    def set_busy(self, busy, text=""):
        if busy:
            self.progress.config(mode="indeterminate", value=0)
            self.progress.start(12)
            self.status.set(text)
            for btn in (self.scan_btn, self.organize_btn, self.undo_btn):
                btn.set_enabled(False)
        else:
            self.progress.stop()
            self.progress.config(mode="determinate", value=100)   # show a full bar when finished
            self.refresh_buttons()

    def refresh_buttons(self):
        """Enable each button only when it can actually be used."""
        folder = self.folder.get()
        self.scan_btn.set_enabled(bool(folder))
        self.organize_btn.set_enabled(bool(self.last_analysis))
        self.undo_btn.set_enabled(bool(folder) and organize.has_undo(folder))

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Select a folder to scan")
        if folder:
            self.folder.set(str(Path(folder)))   # Path() shows Windows-style backslashes on Windows
            self.last_analysis = None             # old results belong to a different folder
            self.refresh_buttons()
            self.status.set("Ready to scan.")

    def start_scan(self):
        formats = [f for f, on in (("html", self.want_html.get()), ("md", self.want_md.get()),
                                   ("csv", self.want_csv.get())) if on]
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

        folder = self.folder.get()
        self.run_in_background(
            lambda: organizer.generate_reports(folder, formats, max_size, reports_dir=REPORTS_DIR,
                                               stale_days=stale_days),
            self.on_scan_done, "Scanning... this can take a while for big folders.")

    def on_scan_done(self, ok, payload):
        if not ok:
            self.status.set("Scan failed.")
            messagebox.showerror("Scan failed", str(payload))
            return
        self.last_root = Path(self.folder.get()).resolve()
        self.show_results(*payload)
        self.refresh_buttons()

    def show_results(self, a, recs, paths):
        self.last_analysis = a
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
        self.open_csv_btn.config(state="normal" if ".csv" in has else "disabled")
        self.status.set("Done! Report saved.")

    def set_recommendations(self, lines):
        self.recs_text.config(state="normal")      # unlock to change the text
        self.recs_text.delete("1.0", "end")
        self.recs_text.insert("1.0", "\n".join(lines))
        self.recs_text.config(state="disabled")    # lock again so users can't type in it

    # ------------------------------------------------------------------
    # Organize mode and undo
    # ------------------------------------------------------------------

    def on_organize_done(self, ok, result):
        if not ok:
            messagebox.showerror("Organize failed", str(result))
            return
        lines = [f"{len(result['done'])} change(s) applied."]
        if result["failed"]:
            lines.append(f"\n{len(result['failed'])} change(s) were skipped to keep your files safe:")
            lines += [f"\u2022 {item['src']}: {reason}" for item, reason in result["failed"][:10]]
        if result["done"]:
            lines.append("\nYou can put everything back with 'Undo Last Organize'.")
        messagebox.showinfo("Organize finished", "\n".join(lines))
        self.start_scan()   # rescan so the results show the tidied folder

    def undo_organize(self):
        folder = self.folder.get()
        if not messagebox.askyesno("Undo last organize?",
                                   "Put every file moved by the last organize back where it was?"):
            return
        self.run_in_background(lambda: organize.undo_last(folder), self.on_undo_done, "Undoing...")

    def on_undo_done(self, ok, result):
        if not ok:
            messagebox.showerror("Undo failed", str(result))
            return
        lines = [f"Restored {result['restored']} file(s)."]
        if result["failed"]:
            lines.append("\nSome files could not be restored:")
            lines += [f"\u2022 {move['from']}: {reason}" for move, reason in result["failed"][:10]]
        messagebox.showinfo("Undo finished", "\n".join(lines))
        self.start_scan()

    # ------------------------------------------------------------------
    # Opening reports
    # ------------------------------------------------------------------

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
            # No default program for this file type (common for .md), so fall back to Notepad
            if sys.platform.startswith("win"):
                subprocess.Popen(["notepad", str(path)])
            else:
                messagebox.showinfo("Report location", f"The report is saved at:\n{path}")

    def open_reports_folder(self):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        open_path(REPORTS_DIR)


class OrganizeDialog:
    """A preview window: shows every planned change and only applies them after confirmation."""

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("Organize Folder")
        self.win.geometry("880x500")
        self.win.transient(app.root)   # stays on top of the main window
        self.win.grab_set()            # main window can't be clicked while this is open

        self.duplicates = tk.BooleanVar(value=True)
        self.empty = tk.BooleanVar(value=True)
        self.loose = tk.BooleanVar(value=True)
        self.plan = []

        body = ttk.Frame(self.win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Preview changes", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(body, foreground="gray", wraplength=840, justify="left",
                  text=f"Nothing is deleted permanently. Removed files are moved into the "
                       f"'{organize.BACKUP_DIR}' folder inside the scanned folder, and you can undo "
                       f"everything with 'Undo Last Organize'.").pack(anchor="w", pady=(2, 10))

        choices = ttk.Frame(body)
        choices.pack(fill="x")
        for text, var in [("Remove duplicate copies (keep one)", self.duplicates),
                          ("Remove empty files", self.empty),
                          ("Move loose files into folders", self.loose)]:
            ttk.Checkbutton(choices, text=text, variable=var,
                            command=self.refresh).pack(side="left", padx=(0, 16))

        # Buttons first, at the bottom, so they always stay visible
        buttons = ttk.Frame(body)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        self.summary = ttk.Label(buttons, text="")
        self.summary.pack(side="left")
        self.apply_btn = ttk.Button(buttons, text="Apply Changes", command=self.apply)
        self.apply_btn.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.win.destroy).pack(side="right", padx=8)

        table_frame, self.table = make_table(body, [("action", "Change", 140), ("file", "File", 320),
                                                    ("result", "What happens", 380)])
        table_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.refresh()

    def refresh(self):
        """Rebuild the plan whenever a checkbox changes. Nothing on disk is touched here."""
        self.plan = organize.plan_changes(self.app.last_root, self.app.last_analysis,
                                          duplicates=self.duplicates.get(), empty=self.empty.get(),
                                          loose=self.loose.get())
        self.table.delete(*self.table.get_children())
        for item in self.plan:
            if item["action"] == organize.MOVE_LOOSE:
                result = f"Moved to {item['dst']}"
            else:
                result = f"Moved to backup ({item['reason']})"
            self.table.insert("", "end", values=(item["action"], item["src"], result))
        count = len(self.plan)
        self.summary.config(text=f"{count} change(s) will be made." if count else "Nothing to change.")
        self.apply_btn.config(state="normal" if count else "disabled",
                              text=f"Apply {count} Change(s)" if count else "Apply Changes")

    def apply(self):
        count = len(self.plan)
        if not messagebox.askyesno("Apply changes?",
                                   f"Apply {count} change(s) to this folder?\n\n{self.app.last_root}\n\n"
                                   "Removed files go into the backup folder, and you can undo this.",
                                   parent=self.win):
            return
        plan, root = self.plan, self.app.last_root
        self.win.destroy()
        self.app.run_in_background(lambda: organize.apply_changes(root, plan),
                                   self.app.on_organize_done, "Organizing...")


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