"""Tab tra cứu định mức BOM theo DG Case (logic check_bom)."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import pandas as pd

from core.bom_service import BomLookupService
from core.ol_reader import OlReaderService
from core.utils import normalize_dg_case, normalize_text
from ui.theme import COLORS, FONT_BODY, FONT_SMALL


class BomPanel(ctk.CTkFrame):
    def __init__(self, master, ol_data_provider: callable, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.ol_data_provider = ol_data_provider
        self.service = BomLookupService()
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(
            self,
            text="Tra cứu định mức (BOM)",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 4))
        ctk.CTkLabel(
            self,
            text="Quét thư mục phần theo khách · tìm DG Case trong Excel (A1:B9) · cache mapping",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=12, pady=(0, 8))

        card = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        card.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(card, text="DG Case / Số O:", font=FONT_BODY).grid(row=0, column=0, padx=12, pady=12, sticky="w")
        self.dg_var = ctk.StringVar()
        ctk.CTkEntry(card, textvariable=self.dg_var, width=200).grid(row=0, column=1, padx=6, pady=12, sticky="w")

        ctk.CTkLabel(card, text="Khách hàng:", font=FONT_BODY).grid(row=0, column=2, padx=(20, 6), pady=12)
        self.customer_combo = ctk.CTkComboBox(card, width=280, values=self._customer_combo_values())
        self.customer_combo.grid(row=0, column=3, padx=6, pady=12)

        ctk.CTkButton(
            card,
            text="Lấy từ dòng OL đang lọc",
            width=160,
            command=self._fill_from_ol,
        ).grid(row=0, column=4, padx=8, pady=12)

        ctk.CTkButton(
            card,
            text="Tìm định mức",
            width=140,
            fg_color=COLORS["accent"][1],
            command=self._search_async,
        ).grid(row=1, column=1, padx=6, pady=(0, 12), sticky="w")

        ctk.CTkButton(
            card,
            text="Tải dòng BOM",
            width=120,
            command=self._load_bom_lines_async,
        ).grid(row=1, column=2, padx=6, pady=(0, 12), sticky="w")

        self.status = ctk.CTkLabel(self, text="Sẵn sàng.", font=FONT_SMALL, anchor="w")
        self.status.pack(fill="x", padx=16, pady=4)

        self.result_box = ctk.CTkTextbox(self, height=120, font=("Consolas", 11))
        self.result_box.pack(fill="x", padx=12, pady=8)
        self.result_box.configure(state="disabled")

        bom_frame = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        bom_frame.pack(fill="both", expand=True, padx=12, pady=8)

        ctk.CTkLabel(bom_frame, text="Chi tiết định mức (ma NPL / SLDM1 / SL)", font=FONT_BODY).pack(
            anchor="w", padx=12, pady=8
        )
        self.bom_table = ctk.CTkScrollableFrame(bom_frame, fg_color="transparent")
        self.bom_table.pack(fill="both", expand=True, padx=8, pady=8)

        self._last_resolve = None
        self._bom_df: pd.DataFrame | None = None

    def _customer_combo_values(self) -> list[str]:
        items = []
        for c in self.service.list_customers():
            items.append(f"{c.id} | {c.name} | {c.code} | {c.folder_link}")
        return items if items else ["(chưa có khách — thêm trong Check BOM)"]

    def _parse_customer_folder(self) -> str:
        text = self.customer_combo.get()
        parts = [p.strip() for p in text.split("|")]
        if len(parts) >= 4:
            return parts[-1]
        return ""

    def _fill_from_ol(self) -> None:
        df = self.ol_data_provider()
        if df is None or df.empty:
            messagebox.showinfo("BOM", "Chưa có dữ liệu OL. Đọc OL trước.")
            return
        dg_filter = normalize_dg_case(self.dg_var.get())
        if dg_filter:
            sub = OlReaderService().find_by_dg_case(df, dg_filter)
        else:
            sub = df.head(1)
        if sub.empty:
            messagebox.showinfo("BOM", "Không tìm thấy dòng OL.")
            return
        row = sub.iloc[0]
        self.dg_var.set(normalize_text(row.get("dg_case", "")))
        cust = self.service.auto_customer_folder(
            normalize_text(row.get("production_no", "")),
            normalize_text(row.get("customer", "")),
        )
        if cust:
            combo = f"{cust.id} | {cust.name} | {cust.code} | {cust.folder_link}"
            self.customer_combo.set(combo)
        info = (
            f"Order: {row.get('order_no', '')}\n"
            f"Prod: {row.get('production_no', '')}\n"
            f"Khách OL: {row.get('customer', '')}"
        )
        self._set_result_text(info)

    def _set_result_text(self, text: str) -> None:
        self.result_box.configure(state="normal")
        self.result_box.delete("1.0", "end")
        self.result_box.insert("1.0", text)
        self.result_box.configure(state="disabled")

    def _search_async(self) -> None:
        dg = self.dg_var.get().strip()
        folder = self._parse_customer_folder()
        if not dg:
            messagebox.showwarning("BOM", "Nhập DG Case.")
            return
        if not folder or not Path(folder).exists():
            messagebox.showwarning("BOM", "Chọn khách hàng có thư mục phần hợp lệ.")
            return

        self.status.configure(text="Đang quét file Excel trong thư mục khách…")

        def worker() -> None:
            try:
                def progress(msg: str) -> None:
                    self.after(0, lambda: self.status.configure(text=msg))

                result = self.service.resolve_bom_for_dg_case(dg, folder, progress_cb=progress)
                self.after(0, lambda: self._on_resolved(result))
            except Exception as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_resolved(self, result) -> None:
        self._last_resolve = result
        self.status.configure(text=result.message)
        text = (
            f"DG Case: {result.dg_case}\n"
            f"File: {result.file_path}\n"
            f"Sheet: {result.sheet_name}\n"
            f"Ô: {result.cell}\n"
            f"Mã khách: {result.customer_code}\n"
            f"Mã SP (item): {result.item_code}\n"
            f"Thư mục: {result.customer_folder}"
        )
        self._set_result_text(text)

    def _load_bom_lines_async(self) -> None:
        if not self._last_resolve:
            messagebox.showinfo("BOM", "Tìm định mức trước.")
            return

        def worker() -> None:
            try:
                df = self.service.load_bom_sheet_lines(
                    self._last_resolve.file_path,
                    self._last_resolve.sheet_name,
                )
                self.after(0, lambda: self._show_bom_df(df))
            except Exception as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_bom_df(self, df: pd.DataFrame) -> None:
        self._bom_df = df
        for w in self.bom_table.winfo_children():
            w.destroy()
        hdr = ctk.CTkFrame(self.bom_table, fg_color=("gray85", "gray25"))
        hdr.pack(fill="x")
        for label, w in [("ma_npl", 200), ("sldm1_h", 90), ("so_luong_i", 90), ("dvt_excel", 70)]:
            ctk.CTkLabel(hdr, text=label, width=w, font=("Segoe UI", 11, "bold")).pack(side="left", padx=4, pady=4)
        for _, row in df.head(200).iterrows():
            line = ctk.CTkFrame(self.bom_table, fg_color="transparent")
            line.pack(fill="x", pady=1)
            for key, w in [("ma_npl", 200), ("sldm1_h", 90), ("so_luong_i", 90), ("dvt_excel", 70)]:
                ctk.CTkLabel(line, text=str(row.get(key, "")), width=w, font=FONT_SMALL, anchor="w").pack(
                    side="left", padx=4
                )
        self.status.configure(text=f"Đã tải {len(df)} dòng định mức.")

    def _on_error(self, msg: str) -> None:
        self.status.configure(text=f"Lỗi: {msg}")
        messagebox.showerror("BOM", msg)
