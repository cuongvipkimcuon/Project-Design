"""Bảng hiển thị dữ liệu OL dùng chung."""

from __future__ import annotations

import customtkinter as ctk
import pandas as pd

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


class OlTableWidget(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self._render_header()

    def _render_header(self) -> None:
        for w in self.winfo_children():
            w.destroy()
        row = ctk.CTkFrame(self, fg_color=("gray85", "gray25"), height=32)
        row.pack(fill="x", pady=(0, 2))
        for _key, label, width in DISPLAY_COLS:
            ctk.CTkLabel(
                row,
                text=label,
                width=width,
                font=("Segoe UI", 11, "bold"),
                anchor="w",
            ).pack(side="left", padx=2, pady=4)

    def render(self, df: pd.DataFrame | None, *, max_rows: int = 500) -> None:
        self._render_header()
        if df is None or df.empty:
            ctk.CTkLabel(self, text="Không có dòng.", font=FONT_BODY).pack(pady=16)
            return
        show = df.head(max_rows)
        for _, r in show.iterrows():
            row = ctk.CTkFrame(self, fg_color="transparent", height=28)
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
                self,
                text=f"… {max_rows}/{len(df)} dòng",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(pady=6)
