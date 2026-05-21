"""Tab Setup — tài khoản, OL, khách hàng, BOM, EMG JSON."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from check_bom import DatabaseManager as BomDatabaseManager
from core.app_state import AppState
from core.bom_ke_reader import BomKeReaderService
from core.utils import normalize_text
from ui.theme import COLORS, FONT_BODY, FONT_SMALL, FONT_SUB

_SHOW_CUSTOMER_UI = False


class SetupPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, state: AppState, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self.bom_db = BomDatabaseManager()
        self.bom_ke_service = BomKeReaderService(state.db)
        self._build()

    def _section(self, title: str) -> ctk.CTkFrame:
        box = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        box.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(box, text=title, font=("Segoe UI", 15, "bold")).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=(0, 14))
        return inner

    def _build(self) -> None:
        ctk.CTkLabel(
            self,
            text="Setup",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 4))

        # --- Tài khoản ---
        acc = self._section("Tài khoản — tên hiển thị")
        ctk.CTkLabel(acc, text=f"Username: {self.state.user.username}", font=FONT_SMALL).pack(anchor="w")
        row = ctk.CTkFrame(acc, fg_color="transparent")
        row.pack(fill="x", pady=8)
        ctk.CTkLabel(row, text="Tên hiển thị:", font=FONT_BODY).pack(side="left")
        self.display_var = ctk.StringVar(value=self.state.user.display_name)
        ctk.CTkEntry(row, textvariable=self.display_var, width=280).pack(side="left", padx=8)
        ctk.CTkButton(row, text="Lưu", width=80, command=self._save_display_name).pack(side="left")

        # --- Đọc OL hàng ngày ---
        ol = self._section("Đọc Order List (OL) hàng ngày")
        self.ol_path_var = ctk.StringVar(value=self.state.db.get_setup("ol_file_path", ""))
        ctk.CTkEntry(ol, textvariable=self.ol_path_var, placeholder_text="Đường dẫn file OL .xlsx").pack(
            fill="x", pady=4
        )
        brow = ctk.CTkFrame(ol, fg_color="transparent")
        brow.pack(fill="x", pady=8)
        ctk.CTkButton(brow, text="Chọn file", width=100, command=self._pick_ol).pack(side="left")
        ctk.CTkButton(
            brow,
            text="Đọc",
            width=100,
            fg_color=COLORS["accent"][1],
            command=self._read_ol,
        ).pack(side="left", padx=8)
        self.ol_status_label = ctk.CTkLabel(brow, text="—", font=FONT_BODY)
        self.ol_status_label.pack(side="left", padx=12)
        self._refresh_ol_status()

        # --- Bảng kê Check BOM ---
        bom = self._section("Link bảng kê (Check BOM)")
        self.bom_link_var = ctk.StringVar(value=self.bom_db.get_setup_value("bom_link"))
        ctk.CTkEntry(bom, textvariable=self.bom_link_var, placeholder_text="Đường dẫn file bảng kê").pack(
            fill="x", pady=4
        )
        brow2 = ctk.CTkFrame(bom, fg_color="transparent")
        brow2.pack(fill="x", pady=6)
        ctk.CTkButton(brow2, text="Chọn file", width=100, command=self._pick_bom).pack(side="left")
        ctk.CTkButton(brow2, text="Lưu link", width=100, command=self._save_bom_link).pack(side="left", padx=8)
        ctk.CTkButton(
            brow2,
            text="Đọc",
            width=100,
            fg_color=COLORS["accent"][1],
            command=self._read_bom_ke,
        ).pack(side="left", padx=8)
        self.bom_status_label = ctk.CTkLabel(brow2, text="—", font=FONT_BODY)
        self.bom_status_label.pack(side="left", padx=12)
        self._refresh_bom_status()

        if _SHOW_CUSTOMER_UI:
            self._build_customer_section()

        # --- EMG Scanner JSON ---
        emg = self._section("EMG Scanner — file JSON")
        default_emg = str(Path(__file__).resolve().parents[1] / "emg_scanner_export.json")
        saved = self.state.db.get_setup("emg_scanner_json_path", default_emg)
        self.emg_path_var = ctk.StringVar(value=saved)
        ctk.CTkEntry(emg, textvariable=self.emg_path_var, placeholder_text="emg_scanner_export.json").pack(
            fill="x", pady=4
        )
        erow = ctk.CTkFrame(emg, fg_color="transparent")
        erow.pack(fill="x", pady=6)
        ctk.CTkButton(erow, text="Chọn file", width=100, command=self._pick_emg).pack(side="left")
        ctk.CTkButton(erow, text="Lưu link", width=100, command=self._save_emg).pack(side="left", padx=8)
        self.emg_status = ctk.CTkLabel(erow, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.emg_status.pack(side="left", padx=8)
        self._check_emg_path()

    def _build_customer_section(self) -> None:
        kh = self._section("Khách hàng & thư mục phần (Check BOM)")
        ctk.CTkLabel(
            kh,
            text="Danh sách lưu trong check_bom.db — dùng chung với Check BOM.",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(0, 6))
        self.customer_list = ctk.CTkTextbox(kh, height=140, font=("Consolas", 11))
        self.customer_list.pack(fill="x", pady=4)
        self.customer_list.configure(state="disabled")
        cbtn = ctk.CTkFrame(kh, fg_color="transparent")
        cbtn.pack(fill="x", pady=6)
        ctk.CTkButton(cbtn, text="Thêm KH", width=90, command=self._add_customer).pack(side="left")
        ctk.CTkButton(cbtn, text="Sửa KH", width=90, command=self._edit_customer).pack(side="left", padx=6)
        ctk.CTkButton(cbtn, text="Xóa KH", width=90, command=self._delete_customer).pack(side="left", padx=6)
        ctk.CTkButton(cbtn, text="↻", width=36, command=self._reload_customers).pack(side="left", padx=8)
        self._selected_customer_id: int | None = None
        self._reload_customers()

    def _refresh_bom_status(self) -> None:
        a6_hash = self.state.db.get_setup("bom_ke_a6_hash", "")
        a6_text = self.state.db.get_setup("bom_ke_a6_text", "")
        meta = self.state.db.get_bom_ke_dataset(a6_hash) if a6_hash else None
        if self.state.bom_ke_ok and meta:
            short = a6_text[:42] + "…" if len(a6_text) > 42 else a6_text
            self.bom_status_label.configure(
                text=f"✓ OK — {meta['row_count']} dòng | A6: {short}",
                text_color=COLORS["success"][1],
            )
        elif meta:
            short = a6_text[:42] + "…" if len(a6_text) > 42 else a6_text
            self.bom_status_label.configure(
                text=f"✓ Cache — {meta['row_count']} dòng | A6: {short}",
                text_color=COLORS["success"][1],
            )
        else:
            self.bom_status_label.configure(
                text="Chưa đọc bảng kê",
                text_color=COLORS["warning"][1],
            )

    def _refresh_ol_status(self) -> None:
        today = date.today().strftime("%Y-%m-%d")
        meta = self.state.db.get_snapshot_meta(today)
        if self.state.ol_ok and meta:
            self.ol_status_label.configure(
                text=f"✓ OK — {meta[5]} dòng ({today})",
                text_color=COLORS["success"][1],
            )
        elif meta:
            self.ol_status_label.configure(
                text=f"✓ Đã có snapshot {today} ({meta[5]} dòng)",
                text_color=COLORS["success"][1],
            )
        else:
            self.ol_status_label.configure(
                text="Chưa đọc OK hôm nay",
                text_color=COLORS["warning"][1],
            )

    def _save_display_name(self) -> None:
        name = self.display_var.get().strip()
        if not name:
            messagebox.showwarning("Setup", "Tên hiển thị không được trống.")
            return
        self.state.db.update_user_display_name(self.state.user.id, name)
        self.state.user.display_name = name
        messagebox.showinfo("Setup", "Đã lưu tên hiển thị.")

    def _pick_ol(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if p:
            self.ol_path_var.set(p)

    def _read_ol(self) -> None:
        path = self.ol_path_var.get().strip()
        if not path:
            messagebox.showwarning("OL", "Chọn file OL trước.")
            return
        self.ol_status_label.configure(text="Đang đọc…", text_color=COLORS["muted"][1])
        self.state.db.set_setup("ol_file_path", path)

        def worker() -> None:
            try:
                result = self.state.ol_service.load_for_today(path, force=False)
                self.after(0, lambda: self._on_ol_done(result))
            except Exception as exc:
                self.after(0, lambda: self._on_ol_fail(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ol_done(self, result) -> None:
        self.state.set_ol_result(result)
        self._refresh_ol_status()
        messagebox.showinfo("OL", result.message)

    def _on_ol_fail(self, msg: str) -> None:
        self.state.set_ol_error(msg)
        self.ol_status_label.configure(text=f"✗ {msg}", text_color="#e57373")
        messagebox.showerror("OL", msg)

    def _pick_bom(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if p:
            self.bom_link_var.set(p)

    def _save_bom_link(self) -> None:
        path = self.bom_link_var.get().strip()
        if not path:
            messagebox.showwarning("Setup", "Chọn file bảng kê.")
            return
        self.bom_db.set_setup_value("bom_link", path)
        self.state.db.set_setup("bom_ke_file_path", path)
        messagebox.showinfo("Setup", "Đã lưu link bảng kê.")

    def _read_bom_ke(self) -> None:
        path = self.bom_link_var.get().strip()
        if not path:
            messagebox.showwarning("Bảng kê", "Chọn file bảng kê trước.")
            return
        self.bom_status_label.configure(text="Đang đọc…", text_color=COLORS["muted"][1])
        self.bom_db.set_setup_value("bom_link", path)

        def worker() -> None:
            try:
                result = self.bom_ke_service.load(path, force=False)
                self.after(0, lambda: self._on_bom_done(result))
            except Exception as exc:
                self.after(0, lambda: self._on_bom_fail(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_bom_done(self, result) -> None:
        self.state.set_bom_ke_result(result)
        self._refresh_bom_status()
        messagebox.showinfo("Bảng kê", result.message)

    def _on_bom_fail(self, msg: str) -> None:
        self.state.set_bom_ke_error(msg)
        self.bom_status_label.configure(text=f"✗ {msg}", text_color="#e57373")
        messagebox.showerror("Bảng kê", msg)

    def _reload_customers(self) -> None:
        rows = self.bom_db.get_customers()
        lines = []
        for r in rows:
            lines.append(f"[{r[0]}] {r[1]} | mã:{r[2]} | {r[3]}")
        self.customer_list.configure(state="normal")
        self.customer_list.delete("1.0", "end")
        self.customer_list.insert("1.0", "\n".join(lines) if lines else "(chưa có khách)")
        self.customer_list.configure(state="disabled")
        self._customer_rows = rows

    def _parse_selected_customer_line(self) -> int | None:
        try:
            text = self.customer_list.get("sel.first", "sel.last").strip()
        except Exception:
            text = ""
        if not text and hasattr(self, "_customer_rows"):
            return None
        if text.startswith("["):
            try:
                return int(text.split("]")[0][1:])
            except ValueError:
                pass
        return None

    def _add_customer(self) -> None:
        name = simpledialog.askstring("Khách hàng", "Tên khách:")
        if not name:
            return
        code = simpledialog.askstring("Khách hàng", "Mã khách:") or ""
        folder = simpledialog.askstring("Khách hàng", "Thư mục phần (folder link):") or ""
        if not folder:
            return
        self.bom_db.add_customer(name, code, folder)
        self._reload_customers()

    def _edit_customer(self) -> None:
        cid = simpledialog.askinteger("Sửa KH", "ID khách (xem trong danh sách):")
        if cid is None:
            return
        rows = {r[0]: r for r in self.bom_db.get_customers()}
        if cid not in rows:
            messagebox.showwarning("Setup", "ID không tồn tại.")
            return
        r = rows[cid]
        name = simpledialog.askstring("Sửa", "Tên:", initialvalue=r[1]) or r[1]
        code = simpledialog.askstring("Sửa", "Mã:", initialvalue=r[2]) or r[2]
        folder = simpledialog.askstring("Sửa", "Folder:", initialvalue=r[3]) or r[3]
        self.bom_db.update_customer(cid, name, code, folder)
        self._reload_customers()

    def _delete_customer(self) -> None:
        cid = simpledialog.askinteger("Xóa KH", "ID khách cần xóa:")
        if cid is None:
            return
        if messagebox.askyesno("Xác nhận", f"Xóa khách id={cid}?"):
            self.bom_db.delete_customer(cid)
            self._reload_customers()

    def _pick_emg(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if p:
            self.emg_path_var.set(p)

    def _save_emg(self) -> None:
        path = self.emg_path_var.get().strip()
        self.state.db.set_setup("emg_scanner_json_path", path)
        self._check_emg_path()
        messagebox.showinfo("Setup", "Đã lưu link EMG JSON.")

    def _check_emg_path(self) -> None:
        p = Path(self.emg_path_var.get().strip())
        if p.is_file():
            self.emg_status.configure(text=f"✓ File tồn tại ({p.stat().st_size // 1024} KB)")
        else:
            self.emg_status.configure(text="✗ File không tồn tại")
