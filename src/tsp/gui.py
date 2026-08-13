"""Tkinter desktop front end for TSP.

The worker runs on a background thread and reports through a queue, so the
window keeps redrawing while long PDFs process and the Cancel button responds
straight away.

Copyright (C) 2026 Daga D.
Licensed under the GNU General Public License v3.0 or later. See LICENSE.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from .core import MODES, Result, Settings, process_pdf, tesseract_available

APP_NAME = "TSP - Token Saving Protocol"

INK = "#0f172a"
PAPER = "#f5f6f8"
CARD = "#ffffff"
ACCENT = "#2f6f6b"
ACCENT_DARK = "#25574f"
MUTED = "#5b6472"
GOOD = "#2f7a4f"
WARN = "#a5701c"
BAD = "#a33a34"

# Replaced by resolve_fonts() once a Tk root exists, which is the earliest
# point at which the platform's own UI font can be read.
FONT = ("sans-serif", 10)
FONT_BOLD = ("sans-serif", 10, "bold")
FONT_SMALL = ("sans-serif", 9)
FONT_TITLE = ("sans-serif", 15, "bold")


def resolve_fonts() -> None:
    """Adopt whichever font the desktop uses for its own interface."""
    global FONT, FONT_BOLD, FONT_SMALL, FONT_TITLE
    try:
        family = tkfont.nametofont("TkDefaultFont").cget("family")
    except (tk.TclError, RuntimeError):
        return
    FONT = (family, 10)
    FONT_BOLD = (family, 10, "bold")
    FONT_SMALL = (family, 9)
    FONT_TITLE = (family, 15, "bold")


@dataclass
class QueueItem:
    path: Path
    mode: tk.StringVar
    tables: tk.BooleanVar
    figures: tk.BooleanVar
    row: tk.Frame
    state: tk.Label | None = None
    report: Result | None = None


def find_icon() -> Path | None:
    """Look for the icon beside the package, in a PyInstaller bundle, and in
    the repository layout."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "assets",
        here.parent.parent / "assets",
        Path(getattr(sys, "_MEIPASS", here)) / "assets",
        Path.cwd() / "assets",
        Path.cwd(),
    ]
    names = ["icon.png", "icon.ico"]
    for folder in candidates:
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.items: list[QueueItem] = []
        self.cancel_flag = threading.Event()
        self.messages: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        root.title(APP_NAME)
        root.geometry("640x560")
        root.minsize(560, 460)
        root.configure(bg=PAPER)
        self._set_icon()
        self._build()

    # -- window furniture -------------------------------------------------

    def _set_icon(self) -> None:
        icon = find_icon()
        if not icon:
            return
        try:
            if icon.suffix == ".png":
                self._icon_image = tk.PhotoImage(file=str(icon))
                self.root.iconphoto(True, self._icon_image)
            else:
                self.root.iconbitmap(default=str(icon))
        except Exception:
            pass

    def _build(self) -> None:
        header = tk.Frame(self.root, bg=PAPER)
        header.pack(fill="x", padx=20, pady=(18, 6))
        tk.Label(
            header,
            text="Token Saving Protocol",
            font=FONT_TITLE,
            bg=PAPER,
            fg=INK,
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Add PDFs, pick how much of each page counts as a picture, "
            "then process.",
            font=FONT,
            bg=PAPER,
            fg=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        toolbar = tk.Frame(self.root, bg=PAPER)
        toolbar.pack(fill="x", padx=20, pady=(8, 4))

        self.btn_add = tk.Button(
            toolbar,
            text="Add files",
            command=self.add_files,
            font=FONT_BOLD,
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
        )
        self.btn_add.pack(side="left")

        self.btn_clear = tk.Button(
            toolbar,
            text="Clear",
            command=self.clear_queue,
            font=FONT,
            bg=PAPER,
            fg=MUTED,
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )
        self.btn_clear.pack(side="left", padx=(8, 0))

        self.ocr_var = tk.BooleanVar(value=False)
        self.ocr_ready = tesseract_available()
        ocr_box = tk.Checkbutton(
            toolbar,
            text="Read scans (OCR)" if self.ocr_ready else "Read scans (needs Tesseract)",
            variable=self.ocr_var,
            command=self._stale_all,
            state="normal" if self.ocr_ready else "disabled",
            bg=PAPER,
            fg=MUTED if self.ocr_ready else "#a8b0bb",
            font=FONT_SMALL,
            activebackground=PAPER,
            selectcolor=PAPER,
            relief="flat",
            highlightthickness=0,
            cursor="hand2" if self.ocr_ready else "arrow",
        )
        ocr_box.pack(side="left", padx=(14, 0))

        self.dpi_var = tk.StringVar(value="144 dpi")
        dpi_box = ttk.Combobox(
            toolbar,
            textvariable=self.dpi_var,
            values=["96 dpi", "144 dpi", "200 dpi", "300 dpi"],
            state="readonly",
            width=9,
        )
        dpi_box.pack(side="right")
        dpi_box.bind("<<ComboboxSelected>>", lambda _e: self._stale_all())
        tk.Label(
            toolbar, text="Image quality", font=FONT_SMALL, bg=PAPER, fg=MUTED
        ).pack(side="right", padx=(0, 6))

        # One control for every row. Eight documents otherwise means eight of
        # each, which is what the browser build was told about first.
        bulk = tk.Frame(self.root, bg=PAPER)
        bulk.pack(fill="x", padx=20, pady=(4, 0))
        tk.Label(
            bulk, text="Set every file", font=FONT_SMALL, bg=PAPER, fg=MUTED
        ).pack(side="left", padx=(0, 8))

        self.bulk_mode = tk.StringVar(value="")
        self.bulk_box = ttk.Combobox(
            bulk,
            textvariable=self.bulk_mode,
            values=list(MODES),
            state="readonly",
            width=24,
        )
        self.bulk_box.pack(side="left")
        self.bulk_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_mode_to_all())

        self.bulk_tables = tk.BooleanVar(value=False)
        self.bulk_figures = tk.BooleanVar(value=False)
        for text, variable, setter in (
            ("Tables", self.bulk_tables, "tables"),
            ("Figures", self.bulk_figures, "figures"),
        ):
            tk.Checkbutton(
                bulk,
                text=text,
                variable=variable,
                command=lambda v=variable, f=setter: self._apply_flag_to_all(f, v.get()),
                bg=PAPER,
                fg=MUTED,
                font=FONT_SMALL,
                activebackground=PAPER,
                selectcolor=PAPER,
                relief="flat",
                highlightthickness=0,
                cursor="hand2",
            ).pack(side="left", padx=(10, 0))

        holder = tk.Frame(self.root, bg=CARD, highlightbackground="#d8dce3", highlightthickness=1)
        holder.pack(fill="both", expand=True, padx=20, pady=8)

        self.canvas = tk.Canvas(holder, bg=CARD, highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.rows = tk.Frame(self.canvas, bg=CARD)

        self.rows.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.window_id = self.canvas.create_window((0, 0), window=self.rows, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.window_id, width=e.width),
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

        self.empty_hint = tk.Label(
            self.rows,
            text="No files yet.",
            font=FONT,
            bg=CARD,
            fg="#9aa2ae",
            pady=24,
        )
        self.empty_hint.pack()

        footer = tk.Frame(self.root, bg=PAPER)
        footer.pack(fill="x", padx=20, pady=(4, 16))

        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 8))

        self.status = tk.Label(
            footer, text="Waiting for files.", font=FONT_SMALL, bg=PAPER, fg=MUTED
        )
        self.status.pack(anchor="w")

        buttons = tk.Frame(footer, bg=PAPER)
        buttons.pack(fill="x", pady=(10, 0))

        self.btn_process = tk.Button(
            buttons,
            text="Process 0 files",
            command=self.start,
            state="disabled",
            font=FONT_BOLD,
            bg=INK,
            fg="white",
            activebackground="#1d2634",
            activeforeground="white",
            relief="flat",
            padx=22,
            pady=9,
            cursor="hand2",
        )
        self.btn_process.pack(side="left")

        self.btn_cancel = tk.Button(
            buttons,
            text="Cancel",
            command=self.cancel,
            state="disabled",
            font=FONT,
            bg=PAPER,
            fg=BAD,
            relief="flat",
            padx=12,
            pady=9,
            cursor="hand2",
        )
        self.btn_cancel.pack(side="left", padx=(8, 0))

    def _on_wheel(self, event) -> None:
        delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")

    # -- queue ------------------------------------------------------------

    def add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select PDFs", filetypes=[("PDF files", "*.pdf")]
        )
        known = {os.path.normcase(os.path.realpath(i.path)) for i in self.items}
        added = 0
        for raw in paths:
            key = os.path.normcase(os.path.realpath(raw))
            if key in known:
                continue
            known.add(key)
            self._add_row(Path(raw))
            added += 1
        if added:
            self.empty_hint.pack_forget()
        self._refresh()

    def _add_row(self, path: Path) -> None:
        container = tk.Frame(self.rows, bg=CARD)
        container.pack(fill="x")
        row = tk.Frame(container, bg=CARD, pady=6, padx=8)
        row.pack(fill="x")
        tk.Frame(container, bg="#eef0f4", height=1).pack(fill="x")

        name = path.name if len(path.name) <= 40 else path.name[:37] + "..."
        tk.Label(row, text=name, bg=CARD, fg=INK, font=FONT, anchor="w", width=34).pack(
            side="left"
        )

        mode = tk.StringVar(value=next(iter(MODES)))
        ttk.Combobox(
            row,
            textvariable=mode,
            values=list(MODES),
            state="readonly",
            width=24,
        ).pack(side="left", padx=6)

        tables = tk.BooleanVar(value=False)
        state = tk.Label(
            row, text="ready", bg=CARD, fg=MUTED, font=FONT_SMALL, width=13,
            anchor="e",
        )

        figures = tk.BooleanVar(value=False)

        tk.Checkbutton(
            row,
            text="Tables",
            variable=tables,
            bg=CARD,
            fg=MUTED,
            font=FONT_SMALL,
            activebackground=CARD,
            selectcolor=CARD,
            relief="flat",
            highlightthickness=0,
            cursor="hand2",
        ).pack(side="left", padx=(2, 0))

        tk.Checkbutton(
            row,
            text="Figures",
            variable=figures,
            bg=CARD,
            fg=MUTED,
            font=FONT_SMALL,
            activebackground=CARD,
            selectcolor=CARD,
            relief="flat",
            highlightthickness=0,
            cursor="hand2",
        ).pack(side="left")

        item = QueueItem(
            path=path, mode=mode, tables=tables, figures=figures,
            row=container, state=state
        )
        state.pack(side="left", padx=(8, 0))
        mode.trace_add("write", lambda *_: self._mark_stale(item))
        tables.trace_add("write", lambda *_: self._mark_stale(item))
        figures.trace_add("write", lambda *_: self._mark_stale(item))
        tk.Button(
            row,
            text="Remove",
            command=lambda: self.remove(item),
            bg=CARD,
            fg=MUTED,
            font=FONT_SMALL,
            relief="flat",
            cursor="hand2",
        ).pack(side="right")
        self.items.append(item)

    def remove(self, item: QueueItem) -> None:
        item.row.destroy()
        self.items = [i for i in self.items if i is not item]
        if not self.items:
            self.empty_hint.pack()
        self._refresh()

    def clear_queue(self) -> None:
        for item in self.items:
            item.row.destroy()
        self.items.clear()
        for child in self.rows.winfo_children():
            child.destroy()
        self.empty_hint = tk.Label(
            self.rows, text="No files yet.", font=FONT, bg=CARD, fg="#9aa2ae", pady=24
        )
        self.empty_hint.pack()
        self.progress["value"] = 0
        self.status.config(text="Waiting for files.", fg=MUTED)
        self._refresh()

    def _apply_mode_to_all(self) -> None:
        chosen = self.bulk_mode.get()
        if chosen not in MODES:
            return
        for item in self.items:
            item.mode.set(chosen)

    def _apply_flag_to_all(self, field: str, wanted: bool) -> None:
        for item in self.items:
            getattr(item, field).set(wanted)

    def _mark_stale(self, item: QueueItem) -> None:
        """A changed setting makes an earlier result out of date."""
        item.report = None
        if item.state is not None:
            item.state.config(text="ready", fg=MUTED)
        self._refresh()

    def _stale_all(self) -> None:
        for item in self.items:
            self._mark_stale(item)

    def _refresh(self) -> None:
        count = len(self.items)
        done = sum(1 for item in self.items if item.report is not None)
        if not count:
            self.btn_process.config(state="disabled", text="Process files")
        elif done == count:
            self.btn_process.config(state="normal", text="Process again")
        else:
            waiting = count - done
            self.btn_process.config(
                state="normal",
                text=f"Process {waiting} file{'s' if waiting != 1 else ''}",
            )

    # -- work -------------------------------------------------------------

    def start(self) -> None:
        if not self.items or (self.worker and self.worker.is_alive()):
            return

        try:
            dpi = int(self.dpi_var.get().split()[0])
        except (ValueError, IndexError):
            dpi = 144

        jobs = [
            (
                item.path,
                Settings(
                    image_threshold=MODES[item.mode.get()],
                    render_zoom=dpi / 72.0,
                    render_visual_pages=MODES[item.mode.get()] <= 1.0,
                    extract_tables=item.tables.get(),
                    chart_regions=item.figures.get(),
                    ocr=self.ocr_var.get() and self.ocr_ready,
                ),
            )
            for item in self.items
        ]

        for item in self.items:
            if item.state is not None:
                item.state.config(text="waiting", fg=MUTED)

        self.cancel_flag.clear()
        self.btn_add.config(state="disabled")
        self.btn_clear.config(state="disabled")
        self.btn_process.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress.config(maximum=len(jobs) * 100, value=0)

        self.worker = threading.Thread(target=self._run, args=(jobs,), daemon=True)
        self.worker.start()
        self.root.after(80, self._drain)

    def _run(self, jobs) -> None:
        results: list[Result] = []
        for index, (path, settings) in enumerate(jobs):
            if self.cancel_flag.is_set():
                break
            self.messages.put(("file", index, len(jobs), path.name))

            def progress(done: int, total: int, i=index) -> None:
                self.messages.put(("page", i, done, total))

            result = process_pdf(
                path,
                settings,
                progress=progress,
                is_cancelled=self.cancel_flag.is_set,
            )
            results.append(result)
        self.messages.put(("done", results))

    def _drain(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                kind = message[0]
                if kind == "file":
                    _, index, total, name = message
                    self.status.config(
                        text=f"{index + 1} of {total}: {name}", fg="#1f5fa8"
                    )
                elif kind == "page":
                    _, index, done, total = message
                    share = (done / total * 100) if total else 0
                    self.progress["value"] = index * 100 + share
                elif kind == "done":
                    self._finish(message[1])
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _finish(self, results: list[Result]) -> None:
        self.btn_add.config(state="normal")
        self.btn_clear.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self._refresh()

        good = [r for r in results if r.ok]
        bad = [r for r in results if not r.ok]
        tokens = sum(r.tokens_out for r in good)
        removed = sum(r.tokens_in - r.tokens_out for r in good)
        self.progress["value"] = self.progress["maximum"]

        if self.cancel_flag.is_set():
            self.status.config(text=f"Cancelled after {len(good)} files.", fg=WARN)
            return

        for item in self.items:
            item.row.destroy()
        self.items.clear()
        self.empty_hint.pack()
        self._refresh()

        by_path = {r.source: r for r in results}
        for item in self.items:
            report = by_path.get(item.path)
            if report is None:
                continue
            item.report = report if report.ok else None
            if item.state is None:
                continue
            if report.ok:
                bits = [f"{report.pages}p"]
                if report.images_saved:
                    bits.append(f"{report.images_saved} img")
                if report.tables_found:
                    bits.append(f"{report.tables_found} tbl")
                item.state.config(text=", ".join(bits), fg=GOOD)
            else:
                item.state.config(text="failed", fg=BAD)
        self._refresh()

        unread = sum(r.scanned_pages for r in good if r.needs_ocr)
        summary = (
            f"{len(good)} of {len(results)} files done. "
            f"About {tokens:,} tokens of text, {removed:,} trimmed."
        )
        if unread:
            self.status.config(text=summary, fg=WARN)
            offer = (
                f"{unread} pages hold an image and no text layer, so they came "
                f"out empty.\n\n"
            )
            if self.ocr_ready:
                offer += "Tick 'Read scans (OCR)' and run those files again."
            else:
                offer += (
                    "Install Tesseract 5 to read them here, or run OCRmyPDF "
                    "over the files first:\nhttps://ocrmypdf.readthedocs.io"
                )
            messagebox.showwarning("Scanned pages found", offer)
        if bad:
            self.status.config(text=summary, fg=WARN)
            detail = "\n".join(f"{r.source.name}: {r.message}" for r in bad)
            messagebox.showwarning(
                "Finished with errors",
                f"{summary}\n\nOutput sits in a _TSP folder beside each PDF.\n\n"
                f"These files failed:\n{detail}",
            )
        else:
            self.status.config(text=summary, fg=GOOD)
            messagebox.showinfo(
                "Finished",
                f"{summary}\n\nOutput sits in a _TSP folder beside each PDF.",
            )

    def cancel(self) -> None:
        self.cancel_flag.set()
        self.status.config(text="Stopping after the current page.", fg=WARN)
        self.btn_cancel.config(state="disabled")


def main() -> int:
    root = tk.Tk()
    resolve_fonts()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    App(root)
    try:
        root.eval("tk::PlaceWindow . center")
    except tk.TclError:
        pass
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
