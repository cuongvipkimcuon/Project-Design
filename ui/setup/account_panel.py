"""Setup → Tài khoản: tên hiển thị, đổi mật khẩu, link đọc file."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from check_bom import DatabaseManager as BomDatabaseManager
from core.app_state import AppState
from core.bom_ke_reader import BomKeReaderService
from core.permissions import MOD_SETUP_ACCOUNT
from core.shared_dataset_service import SharedDatasetService
from core.supplier_excel_export import (
    DEFAULT_TEMPLATE_PATH,
    SETUP_KEY_TEMPLATE_PATH,
)
from core.supabase_config import supabase_enabled
from core.utils import normalize_text
from ui.theme import COLORS, FONT_BODY, FONT_SMALL

_SHOW_CUSTOMER_UI = False


class SetupAccountPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, state: AppState, auth, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self.auth = auth
        self.bom_db = BomDatabaseManager()
        self.bom_ke_service = BomKeReaderService(state.db)
        self.shared = SharedDatasetService(state.db)
        self._can_write = state.user.can_write(MOD_SETUP_ACCOUNT)
        self._is_admin = state.user.role == "admin"
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
        role_hint = ""
        if not self._can_write:
            role_hint = " (chỉ xem — role của bạn không được ghi Setup)"

        acc = self._section("Tài khoản")
        ctk.CTkLabel(acc, text=f"Username: {self.state.user.username}", font=FONT_SMALL).pack(anchor="w")
        ctk.CTkLabel(
            acc,
            text=f"Role: {self.state.user.role}",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(0, 6))

        row = ctk.CTkFrame(acc, fg_color="transparent")
        row.pack(fill="x", pady=8)
        ctk.CTkLabel(row, text="Tên hiển thị:", font=FONT_BODY).pack(side="left")
        self.display_var = ctk.StringVar(value=self.state.user.display_name)
        ctk.CTkEntry(row, textvariable=self.display_var, width=280).pack(side="left", padx=8)
        ctk.CTkButton(
            row,
            text="Lưu",
            width=80,
            command=self._save_display_name,
            state="normal" if self._can_write else "disabled",
        ).pack(side="left")

        pwd = self._section("Đổi mật khẩu")
        self.old_pass = ctk.CTkEntry(pwd, width=280, show="•", placeholder_text="Mật khẩu hiện tại")
        self.old_pass.pack(fill="x", pady=4)
        self.new_pass = ctk.CTkEntry(pwd, width=280, show="•", placeholder_text="Mật khẩu mới (≥6 ký tự)")
        self.new_pass.pack(fill="x", pady=4)
        self.new_pass2 = ctk.CTkEntry(pwd, width=280, show="•", placeholder_text="Nhập lại mật khẩu mới")
        self.new_pass2.pack(fill="x", pady=4)
        ctk.CTkButton(
            pwd,
            text="Đổi mật khẩu",
            command=self._change_password,
            state="normal" if self._can_write else "disabled",
        ).pack(anchor="w", pady=8)

        ol = self._section(f"Đọc Order List (OL) hàng ngày{role_hint}")
        self.ol_path_var = ctk.StringVar(value=self.state.db.get_setup("ol_file_path", ""))
        ctk.CTkEntry(ol, textvariable=self.ol_path_var, placeholder_text="Đường dẫn file OL .xlsx").pack(
            fill="x", pady=4
        )
        brow = ctk.CTkFrame(ol, fg_color="transparent")
        brow.pack(fill="x", pady=8)
        btn_state = "normal" if self._can_write else "disabled"
        ctk.CTkButton(brow, text="Chọn file", width=100, command=self._pick_ol, state=btn_state).pack(
            side="left"
        )
        ctk.CTkButton(
            brow,
            text="Đọc",
            width=100,
            fg_color=COLORS["accent"][1],
            command=self._read_ol,
            state=btn_state,
        ).pack(side="left", padx=8)
        self.ol_status_label = ctk.CTkLabel(brow, text="—", font=FONT_BODY)
        self.ol_status_label.pack(side="left", padx=12)
        self._refresh_ol_status()

        bom = self._section(f"Link bảng kê (Check BOM){role_hint}")
        bom_saved = self.state.db.get_setup("bom_link", "") or self.bom_db.get_setup_value("bom_link")
        self.bom_link_var = ctk.StringVar(value=bom_saved)
        ctk.CTkEntry(bom, textvariable=self.bom_link_var, placeholder_text="Đường dẫn file bảng kê").pack(
            fill="x", pady=4
        )
        brow2 = ctk.CTkFrame(bom, fg_color="transparent")
        brow2.pack(fill="x", pady=6)
        ctk.CTkButton(brow2, text="Chọn file", width=100, command=self._pick_bom, state=btn_state).pack(
            side="left"
        )
        ctk.CTkButton(brow2, text="Lưu link", width=100, command=self._save_bom_link, state=btn_state).pack(
            side="left", padx=8
        )
        ctk.CTkButton(
            brow2,
            text="Đọc",
            width=100,
            fg_color=COLORS["accent"][1],
            command=self._read_bom_ke,
            state=btn_state,
        ).pack(side="left", padx=8)
        self.bom_status_label = ctk.CTkLabel(brow2, text="—", font=FONT_BODY)
        self.bom_status_label.pack(side="left", padx=12)
        self._refresh_bom_status()

        tpl = self._section(f"Template phiếu Supplier (Excel){role_hint}")
        tpl_default = str(DEFAULT_TEMPLATE_PATH) if DEFAULT_TEMPLATE_PATH.is_file() else ""
        tpl_saved = self.state.db.get_setup(SETUP_KEY_TEMPLATE_PATH, tpl_default)
        self.supplier_tpl_var = ctk.StringVar(value=tpl_saved)
        ctk.CTkLabel(
            tpl,
            text="File mẫu in phiếu xác nhận tem/nhãn. Admin lưu file → tự đẩy lên cloud; user tải về hoặc app tự đồng bộ khi đăng nhập.",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkEntry(
            tpl,
            textvariable=self.supplier_tpl_var,
            placeholder_text="template.xlsx — PHIẾU XÁC NHẬN ĐÃ NHẬN TEM, NHÃN",
        ).pack(fill="x", pady=4)
        trow = ctk.CTkFrame(tpl, fg_color="transparent")
        trow.pack(fill="x", pady=6)
        ctk.CTkButton(
            trow,
            text="Chọn file",
            width=100,
            command=self._pick_supplier_template,
            state=btn_state,
        ).pack(side="left")
        ctk.CTkButton(
            trow,
            text="Lưu link",
            width=100,
            command=self._save_supplier_template,
            state=btn_state,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            trow,
            text="Dùng mặc định",
            width=110,
            fg_color="transparent",
            border_width=1,
            command=self._reset_supplier_template,
            state=btn_state,
        ).pack(side="left", padx=(0, 8))
        self.supplier_tpl_status = ctk.CTkLabel(trow, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.supplier_tpl_status.pack(side="left", padx=8)
        self._check_supplier_template_path()

        if supabase_enabled():
            self._build_shared_section(btn_state)

        emg = self._section(f"EMG Scanner — file JSON{role_hint}")
        default_emg = str(Path(__file__).resolve().parents[2] / "emg_scanner_export.json")
        saved = self.state.db.get_setup("emg_scanner_json_path", default_emg)
        self.emg_path_var = ctk.StringVar(value=saved)
        ctk.CTkEntry(emg, textvariable=self.emg_path_var, placeholder_text="emg_scanner_export.json").pack(
            fill="x", pady=4
        )
        erow = ctk.CTkFrame(emg, fg_color="transparent")
        erow.pack(fill="x", pady=6)
        ctk.CTkButton(erow, text="Chọn file", width=100, command=self._pick_emg, state=btn_state).pack(
            side="left"
        )
        ctk.CTkButton(erow, text="Lưu link", width=100, command=self._save_emg, state=btn_state).pack(
            side="left", padx=8
        )
        self.emg_status = ctk.CTkLabel(erow, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.emg_status.pack(side="left", padx=8)
        self._check_emg_path()

    def _build_shared_section(self, btn_state: str) -> None:
        cloud = self._section("Dữ liệu dùng chung (Supabase)")
        ctk.CTkLabel(
            cloud,
            text=(
                "Admin đọc/chọn file → tự đẩy cloud. «Đồng bộ tất cả» tải OL, bảng kê, template, "
                "quy tắc, EMG + plan/phiếu/tồn team. Thay đổi Design tự đẩy cloud (~2s)."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        self.team_ol_label = ctk.CTkLabel(cloud, text="OL: —", font=FONT_SMALL, anchor="w")
        self.team_ol_label.pack(anchor="w", pady=2)
        self.team_bom_label = ctk.CTkLabel(cloud, text="Bảng kê: —", font=FONT_SMALL, anchor="w")
        self.team_bom_label.pack(anchor="w", pady=2)
        self.team_tpl_label = ctk.CTkLabel(cloud, text="Template phiếu: —", font=FONT_SMALL, anchor="w")
        self.team_tpl_label.pack(anchor="w", pady=2)
        self.team_rules_label = ctk.CTkLabel(cloud, text="Quy tắc Detail: —", font=FONT_SMALL, anchor="w")
        self.team_rules_label.pack(anchor="w", pady=2)
        self.team_emg_label = ctk.CTkLabel(cloud, text="EMG scanner: —", font=FONT_SMALL, anchor="w")
        self.team_emg_label.pack(anchor="w", pady=2)
        self.team_ops_label = ctk.CTkLabel(
            cloud, text="Plan / phiếu / tồn: —", font=FONT_SMALL, anchor="w"
        )
        self.team_ops_label.pack(anchor="w", pady=(2, 10))

        brow = ctk.CTkFrame(cloud, fg_color="transparent")
        brow.pack(fill="x", pady=4)
        ctk.CTkButton(
            brow,
            text="Đồng bộ tất cả từ cloud",
            width=180,
            fg_color=COLORS["accent"][1],
            command=self._pull_all_team,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            brow,
            text="Đồng bộ plan/phiếu/tồn",
            width=170,
            fg_color="transparent",
            border_width=1,
            command=self._pull_team_ops,
        ).pack(side="left", padx=(0, 8))

        if self._is_admin:
            ctk.CTkButton(
                brow,
                text="Chia sẻ lại (admin)",
                width=130,
                fg_color="transparent",
                border_width=1,
                command=self._publish_all_team,
                state=btn_state,
            ).pack(side="left")

        self._refresh_team_status()

    def _refresh_team_status(self) -> None:
        if not supabase_enabled() or not hasattr(self, "team_ol_label"):
            return
        if not self.shared.cloud_enabled:
            msg = "Cloud: cần đăng nhập Supabase (UUID user)"
            self.team_ol_label.configure(text=f"OL: {msg}", text_color=COLORS["warning"][1])
            self.team_bom_label.configure(text=f"Bảng kê: {msg}", text_color=COLORS["warning"][1])
            self.team_tpl_label.configure(text=f"Template phiếu: {msg}", text_color=COLORS["warning"][1])
            self.team_rules_label.configure(text=f"Quy tắc Detail: {msg}", text_color=COLORS["warning"][1])
            self.team_emg_label.configure(text=f"EMG scanner: {msg}", text_color=COLORS["warning"][1])
            self.team_ops_label.configure(text=f"Plan / phiếu / tồn: {msg}", text_color=COLORS["warning"][1])
            return
        ol = self.shared.get_team_info("ol")
        bom = self.shared.get_team_info("bom_ke")
        tpl = self.shared.get_team_info("supplier_template")
        rules = self.shared.get_team_info("supplier_detail_rules")
        emg = self.shared.get_team_info("emg_scanner")
        if ol:
            when = (ol.published_at or "")[:16].replace("T", " ")
            self.team_ol_label.configure(
                text=f"OL: ✓ {ol.row_count} dòng — {ol.publisher_name}, {when}",
                text_color=COLORS["success"][1],
            )
        else:
            self.team_ol_label.configure(
                text="OL: chưa có bản chia sẻ",
                text_color=COLORS["warning"][1],
            )
        if bom:
            when = (bom.published_at or "")[:16].replace("T", " ")
            fmt = (bom.meta or {}).get("excel_gzip_bytes")
            extra = ""
            if fmt:
                extra = f" · file ~{int(fmt) // 1024} KB gzip"
            elif (bom.meta or {}).get("excel_size_bytes"):
                extra = f" · file ~{int(bom.meta['excel_size_bytes']) // (1024 * 1024)} MB"
            self.team_bom_label.configure(
                text=f"Bảng kê: ✓ {bom.row_count:,} dòng{extra} — {bom.publisher_name}, {when}",
                text_color=COLORS["success"][1],
            )
        else:
            self.team_bom_label.configure(
                text="Bảng kê: chưa có bản chia sẻ",
                text_color=COLORS["warning"][1],
            )
        if tpl:
            when = (tpl.published_at or "")[:16].replace("T", " ")
            kb = int((tpl.meta or {}).get("excel_size_bytes", 0) or 0) // 1024
            extra = f" · {kb} KB" if kb else ""
            self.team_tpl_label.configure(
                text=f"Template phiếu: ✓ {tpl.file_name}{extra} — {tpl.publisher_name}, {when}",
                text_color=COLORS["success"][1],
            )
        else:
            self.team_tpl_label.configure(
                text="Template phiếu: chưa có bản chia sẻ",
                text_color=COLORS["warning"][1],
            )
        if rules:
            when = (rules.published_at or "")[:16].replace("T", " ")
            self.team_rules_label.configure(
                text=f"Quy tắc Detail: ✓ {rules.row_count} quy tắc — {rules.publisher_name}, {when}",
                text_color=COLORS["success"][1],
            )
        else:
            self.team_rules_label.configure(
                text="Quy tắc Detail: chưa có bản chia sẻ",
                text_color=COLORS["warning"][1],
            )
        if emg:
            when = (emg.published_at or "")[:16].replace("T", " ")
            kb = int((emg.meta or {}).get("excel_size_bytes", 0) or 0) // 1024
            extra = f" · {kb} KB" if kb else ""
            self.team_emg_label.configure(
                text=f"EMG scanner: ✓ {emg.file_name}{extra} — {emg.publisher_name}, {when}",
                text_color=COLORS["success"][1],
            )
        else:
            self.team_emg_label.configure(
                text="EMG scanner: chưa có bản chia sẻ",
                text_color=COLORS["warning"][1],
            )
        from core.team_ops_sync import get_team_ops_status

        ops = get_team_ops_status(self.state.db)
        local_v = int(ops.get("local_version") or 0)
        remote_v = int(ops.get("remote_version") or 0)
        if local_v > 0 or ops.get("has_remote"):
            when = normalize_text(ops.get("synced_at"))[:16].replace("T", " ")
            who = normalize_text(ops.get("remote_updated_by"))
            if not when and ops.get("remote_updated_at"):
                when = normalize_text(ops["remote_updated_at"])[:16].replace("T", " ")
            detail = f"v{local_v}" if local_v else "—"
            if remote_v and remote_v != local_v:
                detail = f"v{local_v} (cloud v{remote_v})"
            extra = f" — {who}, {when}" if who and when else (f" — {when}" if when else "")
            self.team_ops_label.configure(
                text=f"Plan / phiếu / tồn: ✓ {detail}{extra}",
                text_color=COLORS["success"][1],
            )
        else:
            self.team_ops_label.configure(
                text="Plan / phiếu / tồn: chưa đồng bộ (tự đẩy khi lưu plan/phiếu/tồn)",
                text_color=COLORS["warning"][1],
            )

    def _publish_all_team(self) -> None:
        if not self._is_admin:
            return
        msgs = self.shared.publish_all_team_data(publisher_name=self._publisher_name())
        self._refresh_team_status()
        messagebox.showinfo("Chia sẻ cloud", "\n".join(msgs), parent=self.winfo_toplevel())

    def _publisher_name(self) -> str:
        return self.state.user.display_name or self.state.user.username

    def _auto_publish_if_admin(self, dataset_type: str) -> None:
        if not self._is_admin or not self.shared.cloud_enabled:
            return

        def worker() -> None:
            err: str | None = None
            try:
                if dataset_type == "ol":
                    self.shared.publish_ol(publisher_name=self._publisher_name())
                elif dataset_type == "supplier_template":
                    self.shared.publish_supplier_template(publisher_name=self._publisher_name())
                elif dataset_type == "supplier_detail_rules":
                    self.shared.publish_detail_rules(publisher_name=self._publisher_name())
                elif dataset_type == "emg_scanner":
                    self.shared.publish_emg_scanner(publisher_name=self._publisher_name())
                else:
                    self.shared.publish_bom_ke(publisher_name=self._publisher_name())
            except Exception as exc:
                err = str(exc)
                print(f"[SharedDataset] auto publish {dataset_type}: {exc}")

            def done() -> None:
                self._refresh_team_status()
                if err:
                    messagebox.showwarning(
                        "Chia sẻ cloud",
                        f"Tự chia sẻ {dataset_type} thất bại:\n{err}",
                        parent=self.winfo_toplevel(),
                    )

            self.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _pull_all_team(self) -> None:
        self.team_ol_label.configure(text="OL: đang đồng bộ…", text_color=COLORS["muted"][1])
        self.team_bom_label.configure(text="Bảng kê: đang đồng bộ…", text_color=COLORS["muted"][1])
        self.team_tpl_label.configure(text="Template phiếu: đang đồng bộ…", text_color=COLORS["muted"][1])
        self.team_rules_label.configure(text="Quy tắc Detail: đang đồng bộ…", text_color=COLORS["muted"][1])
        self.team_emg_label.configure(text="EMG scanner: đang đồng bộ…", text_color=COLORS["muted"][1])
        self.team_ops_label.configure(text="Plan / phiếu / tồn: đang đồng bộ…", text_color=COLORS["muted"][1])

        def worker() -> None:
            try:
                result = self.shared.pull_all_team_data(skip_missing=True)
                self.after(0, lambda: self._on_pull_all_done(result))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_team_pull_fail("Đồng bộ cloud", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _pull_team_ops(self) -> None:
        self.team_ops_label.configure(
            text="Plan / phiếu / tồn: đang đồng bộ…", text_color=COLORS["muted"][1]
        )

        def worker() -> None:
            try:
                from core.team_ops_sync import TeamOpsSyncService

                ops = TeamOpsSyncService(self.state.db).sync_bidirectional(
                    actor_name=self._publisher_name(),
                )
                self.after(0, lambda: self._on_team_ops_done(ops))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_team_pull_fail("Plan/phiếu/tồn", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_team_ops_done(self, result) -> None:
        if getattr(result, "needs_overwrite_confirm", False):
            if messagebox.askyesno("Đồng bộ cloud", result.message, parent=self.winfo_toplevel()):
                from core.team_ops_sync import TeamOpsSyncService

                retry = TeamOpsSyncService(self.state.db).push(
                    actor_name=self._publisher_name(),
                    force=True,
                )
                result = retry
            else:
                messagebox.showinfo(
                    "Plan / phiếu / tồn",
                    "Chưa đẩy — cloud có bản mới hơn.",
                    parent=self.winfo_toplevel(),
                )
                return
        self._refresh_team_status()
        if getattr(result, "pulled", False) or getattr(result, "pushed", False):
            self.state.notify()
        msg = getattr(result, "message", "") or "Xong."
        if getattr(result, "errors", None):
            msg += "\n\n" + "\n".join(result.errors)
        messagebox.showinfo("Plan / phiếu / tồn", msg, parent=self.winfo_toplevel())

    def _on_pull_all_done(self, result) -> None:
        if result.ol_result:
            self.state.set_ol_result(result.ol_result)
            self._refresh_ol_status()
        if result.bom_result:
            self.state.set_bom_ke_result(result.bom_result)
            self._refresh_bom_status()
        saved_tpl = self.state.db.get_setup(SETUP_KEY_TEMPLATE_PATH, "")
        if saved_tpl:
            self.supplier_tpl_var.set(saved_tpl)
            self._check_supplier_template_path()
        saved_emg = self.state.db.get_setup("emg_scanner_json_path", "")
        if saved_emg:
            self.emg_path_var.set(saved_emg)
            self._check_emg_path()
        self._refresh_team_status()
        if getattr(result, "ops_pulled", False) or getattr(result, "ops_pushed", False):
            self.state.notify()
        lines = result.messages or ["Không có mục nào tải được."]
        if result.errors:
            lines.append("")
            lines.append("Bỏ qua:")
            lines.extend(result.errors)
        messagebox.showinfo("Đồng bộ cloud", "\n".join(lines), parent=self.winfo_toplevel())

    def _pull_team_template(self) -> None:
        self.team_tpl_label.configure(text="Template phiếu: đang tải…", text_color=COLORS["muted"][1])

        def worker() -> None:
            try:
                msg = self.shared.pull_supplier_template()
                self.after(0, lambda: self._on_team_template_done(msg))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_team_pull_fail("Template phiếu", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_team_template_done(self, msg: str) -> None:
        saved = self.state.db.get_setup(SETUP_KEY_TEMPLATE_PATH, "")
        if saved:
            self.supplier_tpl_var.set(saved)
        self._check_supplier_template_path()
        self._refresh_team_status()
        messagebox.showinfo("Dữ liệu dùng chung", msg, parent=self.winfo_toplevel())

    def _pull_team_ol(self) -> None:
        self.team_ol_label.configure(text="OL: đang tải…", text_color=COLORS["muted"][1])

        def worker() -> None:
            try:
                result = self.shared.pull_ol()
                self.after(0, lambda: self._on_team_ol_done(result))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_team_pull_fail("OL", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _pull_team_bom(self) -> None:
        self.team_bom_label.configure(text="Bảng kê: đang tải…", text_color=COLORS["muted"][1])

        def worker() -> None:
            try:
                result = self.shared.pull_bom_ke()
                self.after(0, lambda: self._on_team_bom_done(result))
            except Exception as exc:
                err = str(exc)
                self.after(0, lambda msg=err: self._on_team_pull_fail("Bảng kê", msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_team_ol_done(self, result) -> None:
        self.state.set_ol_result(result)
        self._refresh_ol_status()
        self._refresh_team_status()
        messagebox.showinfo("Dữ liệu dùng chung", result.message, parent=self.winfo_toplevel())

    def _on_team_bom_done(self, result) -> None:
        self.state.set_bom_ke_result(result)
        self._refresh_bom_status()
        self._refresh_team_status()
        messagebox.showinfo("Dữ liệu dùng chung", result.message, parent=self.winfo_toplevel())

    def _on_team_pull_fail(self, label: str, msg: str) -> None:
        self._refresh_team_status()
        messagebox.showerror(label, msg, parent=self.winfo_toplevel())

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
        if not self._can_write:
            return
        name = self.display_var.get().strip()
        if not name:
            messagebox.showwarning("Setup", "Tên hiển thị không được trống.")
            return
        try:
            self.auth.update_display_name(self.state.user.id, name)
            self.state.user.display_name = name
            messagebox.showinfo("Setup", "Đã lưu tên hiển thị.")
        except Exception as exc:
            messagebox.showerror("Setup", str(exc))

    def _change_password(self) -> None:
        if not self._can_write:
            return
        old = self.old_pass.get()
        new = self.new_pass.get()
        new2 = self.new_pass2.get()
        if new != new2:
            messagebox.showwarning("Setup", "Mật khẩu mới không khớp.")
            return
        try:
            self.auth.change_password(self.state.user.id, old, new)
            self.old_pass.delete(0, "end")
            self.new_pass.delete(0, "end")
            self.new_pass2.delete(0, "end")
            messagebox.showinfo("Setup", "Đã đổi mật khẩu.")
        except Exception as exc:
            messagebox.showerror("Setup", str(exc))

    def _pick_ol(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if p:
            self.ol_path_var.set(p)

    def _read_ol(self) -> None:
        if not self._can_write:
            return
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
        self._auto_publish_if_admin("ol")
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
        if not self._can_write:
            return
        path = self.bom_link_var.get().strip()
        if not path:
            messagebox.showwarning("Setup", "Chọn file bảng kê.")
            return
        self.bom_db.set_setup_value("bom_link", path)
        self.state.db.set_setup("bom_ke_file_path", path)
        messagebox.showinfo("Setup", "Đã lưu link bảng kê.")

    def _read_bom_ke(self) -> None:
        if not self._can_write:
            return
        path = self.bom_link_var.get().strip()
        if not path:
            messagebox.showwarning("Bảng kê", "Chọn file bảng kê trước.")
            return
        self.bom_status_label.configure(text="Đang đọc…", text_color=COLORS["muted"][1])
        self.bom_db.set_setup_value("bom_link", path)
        self.state.db.set_setup("bom_link", path)

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
        self._auto_publish_if_admin("bom_ke")
        messagebox.showinfo("Bảng kê", result.message)

    def _on_bom_fail(self, msg: str) -> None:
        self.state.set_bom_ke_error(msg)
        self.bom_status_label.configure(text=f"✗ {msg}", text_color="#e57373")
        messagebox.showerror("Bảng kê", msg)

    def _pick_supplier_template(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if p:
            self.supplier_tpl_var.set(p)

    def _save_supplier_template(self) -> None:
        if not self._can_write:
            return
        path = self.supplier_tpl_var.get().strip()
        if not path:
            messagebox.showwarning("Setup", "Chọn file template hoặc bấm «Dùng mặc định».")
            return
        if not Path(path).is_file():
            messagebox.showerror("Setup", f"File không tồn tại:\n{path}")
            return
        self.state.db.set_setup(SETUP_KEY_TEMPLATE_PATH, path)
        self.state.db.set_setup("supplier_template_file_name", Path(path).name)
        self._check_supplier_template_path()
        self._auto_publish_if_admin("supplier_template")
        messagebox.showinfo("Setup", "Đã lưu template phiếu Supplier.")

    def _reset_supplier_template(self) -> None:
        if not self._can_write:
            return
        if DEFAULT_TEMPLATE_PATH.is_file():
            self.supplier_tpl_var.set(str(DEFAULT_TEMPLATE_PATH))
            self.state.db.set_setup(SETUP_KEY_TEMPLATE_PATH, str(DEFAULT_TEMPLATE_PATH))
            self.state.db.set_setup("supplier_template_file_name", DEFAULT_TEMPLATE_PATH.name)
        else:
            self.supplier_tpl_var.set("")
            self.state.db.set_setup(SETUP_KEY_TEMPLATE_PATH, "")
            self.state.db.set_setup("supplier_template_file_name", "")
        self._check_supplier_template_path()
        messagebox.showinfo("Setup", "Đã đặt lại template mặc định trong app.")

    def _check_supplier_template_path(self) -> None:
        if not hasattr(self, "supplier_tpl_status"):
            return
        raw = self.supplier_tpl_var.get().strip()
        p = Path(raw) if raw else DEFAULT_TEMPLATE_PATH
        if p.is_file():
            self.supplier_tpl_status.configure(
                text=f"✓ {p.name} ({p.stat().st_size // 1024} KB)",
                text_color=COLORS["muted"][1],
            )
        elif raw:
            self.supplier_tpl_status.configure(text="✗ File không tồn tại", text_color="#e57373")
        elif DEFAULT_TEMPLATE_PATH.is_file():
            self.supplier_tpl_status.configure(
                text=f"✓ Mặc định: {DEFAULT_TEMPLATE_PATH.name}",
                text_color=COLORS["muted"][1],
            )
        else:
            self.supplier_tpl_status.configure(text="✗ Chưa có template", text_color="#e57373")

    def _pick_emg(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json"), ("All", "*.*")])
        if p:
            self.emg_path_var.set(p)

    def _save_emg(self) -> None:
        if not self._can_write:
            return
        path = self.emg_path_var.get().strip()
        self.state.db.set_setup("emg_scanner_json_path", path)
        self._check_emg_path()
        self._auto_publish_if_admin("emg_scanner")
        messagebox.showinfo("Setup", "Đã lưu link EMG JSON.")

    def _check_emg_path(self) -> None:
        p = Path(self.emg_path_var.get().strip())
        if p.is_file():
            self.emg_status.configure(text=f"✓ File tồn tại ({p.stat().st_size // 1024} KB)")
        else:
            self.emg_status.configure(text="✗ File không tồn tại")
