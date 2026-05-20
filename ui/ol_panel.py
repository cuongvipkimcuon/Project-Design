"""Tab đọc Order List (OL) với cache theo ngày."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk
import pandas as pd

from core.database import HubDatabase
from core.ol_reader import OlReaderService
from ui.theme import COLORS, FONT_BODY, FONT_SMALL

DISPLAY_COLS = [
    ("order_date_str", "Order date", 100),
    ("order_no", "Order no", 110),
    ("dg_case", "DG Case", 110),
    ("customer", "Customer", 80),
    ("qty", "Qty", 50),
    ("production_no", "Prod No", 140),
    ("production_name", "Prod Name", 160),
    ("supplier", "Supplier", 90),
    ("cutting_str", "Cutting", 90),
    ("stock_str", "Stock", 90),
    ("estimate_delivery_str", "Est. delivery", 100),
]


class OlPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.db = HubDatabase()
        self.service = OlReaderService(self.db)
        self.current_df: pd.DataFrame | None = None
        self._build()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(8, 4))
        ctk.CTkLabel(
            header,
            text="Order List (OL)",
            font=("Segoe UI", 18, "bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text="Sheet 1 · chỉ dòng có DG Case · cache 1 lần/ngày · hash file",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(side="left", padx=16)

        toolbar = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        toolbar.pack(fill="x", padx=8, pady=8)

        self.file_var = ctk.StringVar(value=self.db.get_setup("ol_file_path", ""))
        ctk.CTkEntry(toolbar, textvariable=self.file_var, width=520, placeholder_text="Đường dẫn file OL (.xlsx)").grid(
            row=0, column=0, columnspan=4, padx=12, pady=(12, 6), sticky="ew"
        )
        toolbar.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(toolbar, text="Chọn file OL", width=120, command=self._pick_file).grid(
            row=1, column=0, padx=12, pady=6, sticky="w"
        )
        ctk.CTkButton(
            toolbar,
            text="Đọc / cập nhật hôm nay",
            width=160,
            fg_color=COLORS["accent"][1],
            command=lambda: self._load_async(force=False),
        ).grid(row=1, column=1, padx=6, pady=6)
        ctk.CTkButton(
            toolbar,
            text="Đọc lại (bỏ cache)",
            width=130,
            fg_color=COLORS["warning"][1],
            command=lambda: self._load_async(force=True),
        ).grid(row=1, column=2, padx=6, pady=6)

        ctk.CTkLabel(toolbar, text="Xem snapshot:", font=FONT_SMALL).grid(row=1, column=3, padx=(20, 6), pady=6)
        self.snapshot_combo = ctk.CTkComboBox(
            toolbar,
            width=140,
            values=self._snapshot_values(),
            command=self._on_snapshot_selected,
        )
        self.snapshot_combo.grid(row=1, column=4, padx=6, pady=6)
        ctk.CTkButton(toolbar, text="↻", width=36, command=self._refresh_snapshots).grid(row=1, column=5, padx=6, pady=6)

        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(fill="x", padx=8, pady=(0, 4))
        ctk.CTkLabel(filter_row, text="Lọc DG Case:", font=FONT_BODY).pack(side="left", padx=(8, 6))
        self.filter_var = ctk.StringVar()
        self.filter_entry = ctk.CTkEntry(filter_row, textvariable=self.filter_var, width=180)
        self.filter_entry.pack(side="left")
        self.filter_entry.bind("<KeyRelease>", lambda e: self._apply_filter())
        ctk.CTkButton(filter_row, text="Xóa lọc", width=80, command=self._clear_filter).pack(side="left", padx=8)

        self.status_label = ctk.CTkLabel(
            self,
            text="Chưa có dữ liệu OL.",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=12, pady=4)

        table_frame = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        table_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.table = ctk.CTkScrollableFrame(table_frame, fg_color="transparent")
        self.table.pack(fill="both", expand=True, padx=4, pady=4)
        self._render_header()

        today = date.today().strftime("%Y-%m-%d")
        if today in self.db.list_snapshot_dates():
            self.snapshot_combo.set(today)
            self._load_snapshot_sync(today)

    def _snapshot_values(self) -> list[str]:
        dates = self.db.list_snapshot_dates()
        return dates if dates else ["(chưa có)"]

    def _refresh_snapshots(self) -> None:
        vals = self._snapshot_values()
        self.snapshot_combo.configure(values=vals)
        if vals and vals[0] != "(chưa có)":
            self.snapshot_combo.set(vals[0])

    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn file Order List",
            filetypes=[("Excel", "*.xlsx *.xls"), ("All", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for w in (self.filter_entry, self.snapshot_combo):
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _load_async(self, *, force: bool) -> None:
        path = self.file_var.get().strip()
        if not path:
            messagebox.showwarning("OL", "Chọn file OL trước.")
            return

        self.status_label.configure(text="Đang đọc OL…")
        self._set_busy(True)

        def worker() -> None:
            try:
                result = self.service.load_for_today(path, force=force)
                self.after(0, lambda: self._on_loaded(result.message, result.df, result.snapshot_date))
            except Exception as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, message: str, df: pd.DataFrame, snap_date: str) -> None:
        self.current_df = df
        self.status_label.configure(text=message)
        self._set_busy(False)
        self._refresh_snapshots()
        self.snapshot_combo.set(snap_date)
        self._render_rows(df)
        self.db.set_setup("ol_file_path", self.file_var.get().strip())

    def _on_error(self, msg: str) -> None:
        self.status_label.configure(text=f"Lỗi: {msg}")
        self._set_busy(False)
        messagebox.showerror("OL", msg)

    def _on_snapshot_selected(self, choice: str) -> None:
        if not choice or choice.startswith("("):
            return
        self._load_snapshot_sync(choice)

    def _load_snapshot_sync(self, snap_date: str) -> None:
        result = self.service.load_snapshot(snap_date)
        if result:
            self.current_df = result.df
            self.status_label.configure(text=result.message)
            self._render_rows(result.df)

    def _clear_filter(self) -> None:
        self.filter_var.set("")
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self.current_df is None:
            return
        text = self.filter_var.get().strip()
        if not text:
            self._render_rows(self.current_df)
            return
        sub = self.service.find_by_dg_case(self.current_df, text)
        self._render_rows(sub)

    def _render_header(self) -> None:
        for w in self.table.winfo_children():
            w.destroy()
        row = ctk.CTkFrame(self.table, fg_color=("gray85", "gray25"), height=32)
        row.pack(fill="x", pady=(0, 2))
        for _key, label, width in DISPLAY_COLS:
            ctk.CTkLabel(
                row,
                text=label,
                width=width,
                font=("Segoe UI", 11, "bold"),
                anchor="w",
            ).pack(side="left", padx=2, pady=4)

    def _render_rows(self, df: pd.DataFrame) -> None:
        self._render_header()
        if df is None or df.empty:
            ctk.CTkLabel(self.table, text="Không có dòng phù hợp.", font=FONT_BODY).pack(pady=20)
            return
        max_rows = 500
        show = df.head(max_rows)
        for _, r in show.iterrows():
            row = ctk.CTkFrame(self.table, fg_color="transparent", height=28)
            row.pack(fill="x", pady=1)
            for key, _label, width in DISPLAY_COLS:
                val = r.get(key, "")
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    val = ""
                ctk.CTkLabel(
                    row,
                    text=str(val),
                    width=width,
                    font=FONT_SMALL,
                    anchor="w",
                ).pack(side="left", padx=2)
        if len(df) > max_rows:
            ctk.CTkLabel(
                self.table,
                text=f"… hiển thị {max_rows}/{len(df)} dòng đầu",
                text_color=COLORS["muted"],
            ).pack(pady=8)

    def get_current_df(self) -> pd.DataFrame | None:
        return self.current_df
