"""Window that SHOWS results (tables like browser history, file lists, or long text)."""
from __future__ import annotations

import webbrowser
from tkinter import ttk

import customtkinter as ctk


class ResultsWindow(ctk.CTkToplevel):
    def __init__(self, master, title: str, columns: list[str], rows: list[list], text: str) -> None:
        super().__init__(master)
        self.title(f"ROVEN — {title}")
        self.geometry("1000x620")
        self.attributes("-topmost", True)
        self.after(1500, lambda: self.attributes("-topmost", False))
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(head, text=title, font=ctk.CTkFont("Segoe UI", 16, "bold")).pack(side="left")
        ctk.CTkButton(head, text="Copy all", width=90, command=lambda: self._copy(columns, rows, text)).pack(side="right")
        if rows:
            ctk.CTkLabel(head, text=f"{len(rows)} items", text_color="#9aa1ad").pack(side="right", padx=12)
            self._table(columns or [f"Column {i + 1}" for i in range(max(len(r) for r in rows))], rows)
        else:
            box = ctk.CTkTextbox(self, font=ctk.CTkFont("Segoe UI", 13), wrap="word")
            box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
            box.insert("1.0", text)
            box.configure(state="disabled")

    def _table(self, columns, rows):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("R.Treeview", background="#1b1e24", fieldbackground="#1b1e24", foreground="#eceef2",
                        rowheight=26, borderwidth=0)
        style.configure("R.Treeview.Heading", background="#2b2f3a", foreground="#eceef2", relief="flat")
        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        tree = ttk.Treeview(frame, columns=columns, show="headings", style="R.Treeview")
        for c in columns:
            tree.heading(c, text=c, command=lambda c=c: self._sort(tree, c))
            tree.column(c, width=max(90, min(420, 900 // len(columns))), anchor="w")
        for row in rows:
            tree.insert("", "end", values=[("" if v is None else str(v)) for v in row])
        ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xs = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        tree.bind("<Double-1>", lambda e: self._open_link(tree))

    @staticmethod
    def _sort(tree, col, reverse=[False]):  # noqa: B006  (toggle state kept on the function)
        items = [(tree.set(k, col), k) for k in tree.get_children("")]
        reverse[0] = not reverse[0]
        items.sort(reverse=reverse[0])
        for i, (_, k) in enumerate(items):
            tree.move(k, "", i)

    @staticmethod
    def _open_link(tree):
        sel = tree.selection()
        if not sel:
            return
        for v in tree.item(sel[0], "values"):
            if str(v).startswith(("http://", "https://")):
                webbrowser.open(str(v))
                return

    def _copy(self, columns, rows, text):
        if rows:
            lines = ["\t".join(columns)] + ["\t".join("" if v is None else str(v) for v in r) for r in rows]
            text = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text)
