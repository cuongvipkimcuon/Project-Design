"""Design → Supplier Management."""

from __future__ import annotations

import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core import supplier_db
from core.app_state import AppState
from core.permissions import MOD_DESIGN_SUPPLIER
from core.supplier_excel_export import export_slip_to_excel
from core.supplier_service import (
    DEFAULT_REASON,
    build_lines_from_plans,
    default_export_filename,
    display_check_date,
    slip_status_label,
)
from core.utils import normalize_text
from ui.dialog_utils import configure_dialog, create_dialog_layout, show_dialog
from ui.theme import COLORS, FONT_BODY, FONT_SMALL

# (title, min_width) — grid uniform giữ header và dòng thẳng cột
CellPad = {"padx": 6, "pady": 8}


def _configure_table_grid(
    frame: ctk.CTkFrame,
    columns: tuple[tuple[str, int], ...],
    *,
    uniform: str = "tblcol",
) -> None:
    for i, (_, width) in enumerate(columns):
        frame.grid_columnconfigure(i, weight=1, uniform=uniform, minsize=width)


def _place_table_row(
    frame: ctk.CTkFrame,
    columns: tuple[tuple[str, int], ...],
    cells: list[str],
    *,
    header: bool = False,
    font=FONT_SMALL,
) -> list[ctk.CTkLabel]:
    _configure_table_grid(frame, columns)
    labels: list[ctk.CTkLabel] = []
    for i, ((title, width), raw) in enumerate(zip(columns, cells)):
        text = title if header else str(raw or "")
        lbl = ctk.CTkLabel(
            frame,
            text=text,
            width=width,
            anchor="w",
            font=("Segoe UI", 11, "bold") if header else font,
        )
        lbl.grid(row=0, column=i, sticky="ew", **CellPad)
        labels.append(lbl)
    return labels


class SupplierPanel(ctk.CTkFrame):
    TABLE_HEADERS = (
        ("STT", 100),
        ("Supplier", 200),
        ("Check Date", 110),
        ("Status", 90),
    )

    def __init__(self, master, state: AppState, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self._can_write = state.user.can_write(MOD_DESIGN_SUPPLIER)
        self._is_admin = state.user.role == "admin"
        self._slips: list[dict] = []
        self._selected_id: int | None = None
        self._row_widgets: dict[int, ctk.CTkFrame] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    def _build(self) -> None:
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        ctk.CTkLabel(toolbar, text="Supplier Management", font=("Segoe UI", 16, "bold")).pack(
            side="left"
        )
        btn_state = "normal" if self._can_write else "disabled"
        ctk.CTkButton(
            toolbar,
            text="Create Phiếu",
            fg_color=COLORS["accent"][1],
            command=self._create_slip,
            state=btn_state,
        ).pack(side="right", padx=4)
        ctk.CTkButton(toolbar, text="Refresh", command=self._reload).pack(side="right", padx=4)

        filt = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=8)
        filt.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        self.f_supplier = ctk.StringVar()
        self.f_product = ctk.StringVar()
        self.f_dg = ctk.StringVar()
        for label, var, w in [
            ("Supplier", self.f_supplier, 160),
            ("Product code", self.f_product, 140),
            ("DG case", self.f_dg, 120),
        ]:
            ctk.CTkLabel(filt, text=label, font=FONT_SMALL).pack(side="left", padx=(12, 4), pady=8)
            e = ctk.CTkEntry(filt, textvariable=var, width=w, height=30)
            e.pack(side="left", padx=(0, 8))
            e.bind("<Return>", lambda _e: self._reload())
        ctk.CTkButton(filt, text="Search", width=80, command=self._reload).pack(side="left", padx=4, pady=8)

        self.table_wrap = ctk.CTkScrollableFrame(self, fg_color=COLORS["card"], corner_radius=10)
        self.table_wrap.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        self.grid_rowconfigure(2, weight=1)

        head = ctk.CTkFrame(self.table_wrap, fg_color=("gray88", "gray28"))
        head.pack(fill="x", padx=8, pady=(8, 0))
        _place_table_row(
            head,
            self.TABLE_HEADERS,
            [t for t, _ in self.TABLE_HEADERS],
            header=True,
        )

        self.rows_frame = ctk.CTkFrame(self.table_wrap, fg_color="transparent")
        self.rows_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self._reload()

    def _reload(self) -> None:
        self._slips = supplier_db.list_supplier_slips(
            self.state.db,
            supplier_filter=self.f_supplier.get().strip(),
            product_filter=self.f_product.get().strip(),
            dg_filter=self.f_dg.get().strip(),
        )
        self._row_widgets.clear()
        for w in self.rows_frame.winfo_children():
            w.destroy()
        if not self._slips:
            ctk.CTkLabel(
                self.rows_frame,
                text="Chưa có phiếu — bấm Create Phiếu.",
                text_color=COLORS["muted"],
            ).pack(pady=24)
            return
        for idx, slip in enumerate(self._slips):
            self._render_row(slip, idx)

    def _render_row(self, slip: dict, row_idx: int) -> None:
        sid = int(slip["id"])
        selected = self._selected_id == sid
        bg = COLORS["accent"] if selected else (
            ("gray95", "gray26") if row_idx % 2 == 0 else ("gray90", "gray22")
        )
        row = ctk.CTkFrame(self.rows_frame, fg_color=bg, corner_radius=6)
        row.pack(fill="x", pady=2)
        self._row_widgets[sid] = row
        cells: list[str] = []
        for title, _w in self.TABLE_HEADERS:
            if title == "STT":
                cells.append(normalize_text(slip.get("slip_code")) or str(sid))
            elif title == "Supplier":
                cells.append(normalize_text(slip.get("supplier")))
            elif title == "Check Date":
                cells.append(display_check_date(slip))
            else:
                cells.append(slip_status_label(slip.get("status", "")))
        labels = _place_table_row(row, self.TABLE_HEADERS, cells)
        for lbl in labels:
            lbl.bind("<Double-Button-1>", lambda _e, s=sid: self._on_row_double(sid))
            lbl.bind("<Button-1>", lambda _e, s=sid: self._select(sid))
        row.bind("<Double-Button-1>", lambda _e, s=sid: self._on_row_double(sid))
        row.bind("<Button-1>", lambda _e, s=sid: self._select(sid))

    def _select(self, slip_id: int) -> None:
        if self._selected_id == slip_id:
            return
        self._selected_id = slip_id
        self._refresh_row_highlights()

    def _refresh_row_highlights(self) -> None:
        for idx, slip in enumerate(self._slips):
            sid = int(slip["id"])
            row = self._row_widgets.get(sid)
            if row is None:
                continue
            if sid == self._selected_id:
                row.configure(fg_color=COLORS["accent"])
            else:
                row.configure(
                    fg_color=("gray95", "gray26") if idx % 2 == 0 else ("gray90", "gray22")
                )

    def _on_row_double(self, slip_id: int) -> None:
        self._selected_id = slip_id
        self._refresh_row_highlights()
        self._open_detail(slip_id)

    def _create_slip(self) -> None:
        CreateSlipDialog(self.winfo_toplevel(), state=self.state, on_saved=self._reload)

    def _open_detail(self, slip_id: int) -> None:
        slip = supplier_db.get_supplier_slip(self.state.db, slip_id)
        if not slip:
            messagebox.showerror("Supplier", "Không tìm thấy phiếu.")
            return
        SlipDetailDialog(
            self.winfo_toplevel(),
            state=self.state,
            slip=slip,
            on_changed=self._reload,
            can_write=self._can_write,
            is_admin=self._is_admin,
        )


def _plan_summary(p: dict) -> str:
    return (
        f"{p.get('plan_date') or p.get('plan_date_iso', '')} · "
        f"GC {p.get('customer_code', '')} · {p.get('item_code', '')} · "
        f"DG {p.get('dg_case', '')} · {p.get('supplier', '')} · Qty {p.get('quantity', '')}"
    )


class CreateSlipDialog(ctk.CTkToplevel):
    def __init__(self, master, *, state: AppState, on_saved) -> None:
        super().__init__(master)
        self.state = state
        self.on_saved = on_saved
        self.queue_ids: list[int] = []
        self.reason_var = ctk.StringVar(value=DEFAULT_REASON)
        self.f_gc = ctk.StringVar()
        self.f_code = ctk.StringVar()
        self.f_date = ctk.StringVar()
        self.f_dg = ctk.StringVar()
        self.filtered_plans: list[dict] = []
        self.pick_vars: dict[int, ctk.BooleanVar] = {}

        self.title("Create Phiếu — chọn Plan chưa giao")
        top = master.winfo_toplevel() if hasattr(master, "winfo_toplevel") else master
        configure_dialog(self, width=1020, height=640, min_width=900, min_height=520, parent=top)
        self.transient(top)
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            body,
            text="Lọc plan → chọn vào queue → xác nhận tạo phiếu (cùng một Supplier).",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=960,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        filt = ctk.CTkFrame(body, fg_color=COLORS["card"], corner_radius=8)
        filt.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for label, var, w in [
            ("GC", self.f_gc, 100),
            ("Mã", self.f_code, 110),
            ("Ngày", self.f_date, 100),
            ("DG case", self.f_dg, 110),
        ]:
            ctk.CTkLabel(filt, text=label, font=FONT_SMALL).pack(side="left", padx=(12, 4), pady=8)
            ent = ctk.CTkEntry(filt, textvariable=var, width=w, height=30)
            ent.pack(side="left", padx=(0, 6))
            ent.bind("<Return>", lambda _e: self._apply_filters())
        ctk.CTkButton(filt, text="Lọc", width=70, command=self._apply_filters).pack(
            side="left", padx=4, pady=8
        )

        panes = ctk.CTkFrame(body, fg_color="transparent")
        panes.grid(row=2, column=0, sticky="nsew")
        panes.grid_columnconfigure(0, weight=1)
        panes.grid_columnconfigure(1, weight=1)
        panes.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(panes, fg_color=COLORS["card"], corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(left, text="Plan khả dụng", font=FONT_BODY).grid(
            row=0, column=0, sticky="w", padx=10, pady=(8, 4)
        )
        self.avail_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.avail_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        avail_btns = ctk.CTkFrame(left, fg_color="transparent")
        avail_btns.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ctk.CTkButton(
            avail_btns, text="→ Thêm đã chọn", width=120, command=self._add_picked
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            avail_btns, text="→ Thêm tất cả (lọc)", width=140, command=self._add_all_filtered
        ).pack(side="left")

        right = ctk.CTkFrame(panes, fg_color=COLORS["card"], corner_radius=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        self.queue_title = ctk.CTkLabel(right, text="Queue (0)", font=FONT_BODY)
        self.queue_title.grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))
        self.queue_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.queue_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        queue_btns = ctk.CTkFrame(right, fg_color="transparent")
        queue_btns.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ctk.CTkButton(
            queue_btns, text="← Xóa chọn", width=100, command=self._remove_picked_queue
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(queue_btns, text="Xóa hết queue", width=110, command=self._clear_queue).pack(
            side="left"
        )

        foot = ctk.CTkFrame(body, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(foot, text="Lý do", font=FONT_SMALL).pack(side="left", padx=(0, 8))
        ctk.CTkEntry(foot, textvariable=self.reason_var, width=320, height=34).pack(
            side="left", fill="x", expand=True, padx=(0, 12)
        )
        ctk.CTkButton(foot, text="Hủy", fg_color="transparent", command=self.destroy).pack(
            side="right", padx=4
        )
        self.create_btn = ctk.CTkButton(
            foot,
            text="Tạo phiếu",
            fg_color=COLORS["success"][1],
            command=self._submit,
        )
        self.create_btn.pack(side="right")

        self._apply_filters()
        show_dialog(self, top)

    def _apply_filters(self) -> None:
        self.filtered_plans = supplier_db.list_plans_unchecked(
            self.state.db,
            customer_code=self.f_gc.get().strip(),
            item_code=self.f_code.get().strip(),
            plan_date=self.f_date.get().strip(),
            dg_case=self.f_dg.get().strip(),
        )
        self._render_available()
        self._render_queue()

    def _queue_set(self) -> set[int]:
        return set(self.queue_ids)

    def _plan_by_id(self, pid: int) -> dict | None:
        for p in self.filtered_plans:
            if int(p["id"]) == pid:
                return p
        conn = self.state.db._connect()
        import sqlite3

        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM planning_entries WHERE id = ? AND is_deleted = 0",
            (pid,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def _render_available(self) -> None:
        for w in self.avail_scroll.winfo_children():
            w.destroy()
        self.pick_vars.clear()
        in_queue = self._queue_set()
        shown = [p for p in self.filtered_plans if int(p["id"]) not in in_queue]
        if not shown:
            ctk.CTkLabel(
                self.avail_scroll,
                text="Không còn plan (đổi bộ lọc hoặc xóa khỏi queue).",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(anchor="w", padx=8, pady=12)
            return
        for p in shown:
            pid = int(p["id"])
            var = ctk.BooleanVar(value=False)
            self.pick_vars[pid] = var
            ctk.CTkCheckBox(
                self.avail_scroll,
                text=_plan_summary(p),
                variable=var,
                font=FONT_SMALL,
            ).pack(anchor="w", padx=6, pady=3)

    def _render_queue(self) -> None:
        for w in self.queue_scroll.winfo_children():
            w.destroy()
        self.queue_title.configure(text=f"Queue ({len(self.queue_ids)})")
        self.create_btn.configure(text=f"Tạo phiếu ({len(self.queue_ids)} plan)")
        if not self.queue_ids:
            ctk.CTkLabel(
                self.queue_scroll,
                text="Chưa có plan trong queue.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(anchor="w", padx=8, pady=12)
            return
        self.queue_remove_vars: dict[int, ctk.BooleanVar] = {}
        for pid in self.queue_ids:
            p = self._plan_by_id(pid)
            if not p:
                continue
            var = ctk.BooleanVar(value=False)
            self.queue_remove_vars[pid] = var
            row = ctk.CTkFrame(self.queue_scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkCheckBox(row, text=_plan_summary(p), variable=var, font=FONT_SMALL).pack(
                side="left", anchor="w"
            )
            ctk.CTkButton(
                row,
                text="Xóa",
                width=50,
                height=24,
                fg_color="transparent",
                border_width=1,
                command=lambda i=pid: self._remove_from_queue(i),
            ).pack(side="right", padx=4)

    def _add_to_queue(self, ids: list[int]) -> None:
        in_q = self._queue_set()
        added = 0
        for pid in ids:
            if pid in in_q:
                continue
            in_q.add(pid)
            self.queue_ids.append(pid)
            added += 1
        if added:
            self._render_available()
            self._render_queue()

    def _add_picked(self) -> None:
        ids = [pid for pid, var in self.pick_vars.items() if var.get()]
        if not ids:
            messagebox.showwarning("Queue", "Chọn plan bên trái trước.", parent=self)
            return
        self._add_to_queue(ids)

    def _add_all_filtered(self) -> None:
        in_q = self._queue_set()
        ids = [int(p["id"]) for p in self.filtered_plans if int(p["id"]) not in in_q]
        if not ids:
            messagebox.showinfo("Queue", "Không còn plan để thêm.", parent=self)
            return
        self._add_to_queue(ids)

    def _remove_from_queue(self, plan_id: int) -> None:
        self.queue_ids = [i for i in self.queue_ids if i != plan_id]
        self._render_available()
        self._render_queue()

    def _remove_picked_queue(self) -> None:
        if not hasattr(self, "queue_remove_vars"):
            return
        ids = [pid for pid, var in self.queue_remove_vars.items() if var.get()]
        if not ids:
            messagebox.showwarning("Queue", "Chọn dòng trong queue để xóa.", parent=self)
            return
        self.queue_ids = [i for i in self.queue_ids if i not in set(ids)]
        self._render_available()
        self._render_queue()

    def _clear_queue(self) -> None:
        if not self.queue_ids:
            return
        if messagebox.askyesno("Queue", "Xóa hết queue?", parent=self):
            self.queue_ids.clear()
            self._render_available()
            self._render_queue()

    def _submit(self) -> None:
        ids = list(self.queue_ids)
        if not ids:
            messagebox.showwarning("Create", "Thêm ít nhất một plan vào queue.", parent=self)
            return
        ol_df = self.state.get_active_ol_df()
        bom_df = self.state.get_active_bom_ke_df()
        try:
            lines, supplier = build_lines_from_plans(
                self.state.db, ids, ol_df=ol_df, bom_df=bom_df
            )
            supplier_db.create_supplier_slip(
                self.state.db,
                supplier=supplier,
                proposed_by=self.state.user.display_name or self.state.user.username,
                reason=self.reason_var.get().strip() or DEFAULT_REASON,
                lines=lines,
                actor_user_id=self.state.user.numeric_id(),
            )
        except Exception as exc:
            messagebox.showerror("Create", str(exc), parent=self)
            return
        messagebox.showinfo("Create", f"Đã tạo phiếu ({len(lines)} dòng).", parent=self)
        self.on_saved()
        self.destroy()


class SlipDetailDialog(ctk.CTkToplevel):
    LINE_HEADERS = (
        ("STT", 40),
        ("Material", 100),
        ("Pro code", 110),
        ("DG case", 100),
        ("Color", 80),
        ("Logo", 80),
        ("Qty", 60),
        ("Detail", 120),
    )

    def __init__(
        self,
        master,
        *,
        state: AppState,
        slip: dict,
        on_changed,
        can_write: bool,
        is_admin: bool,
    ) -> None:
        super().__init__(master)
        self.state = state
        self.slip = slip
        self.on_changed = on_changed
        self.can_write = can_write
        self.is_admin = is_admin
        self.readonly = normalize_text(slip.get("status")) == "done"

        self.title(f"Phiếu {slip.get('slip_code', '')}")
        top = master if isinstance(master, ctk.CTk) else master.winfo_toplevel()
        configure_dialog(self, width=920, height=640, min_width=800, min_height=500, parent=top)
        self.transient(top)
        self.grab_set()

        _, header, content, footer = create_dialog_layout(self)
        ctk.CTkLabel(header, text="Thông tin phiếu", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        info = (
            f"Người đề xuất: {slip.get('proposed_by')} · Supplier: {slip.get('supplier')} · "
            f"Ngày tạo: {slip.get('created_at', '')[:10]} · "
            f"Tình trạng: {slip_status_label(slip.get('status'))} · "
            f"Lý do: {slip.get('reason') or DEFAULT_REASON}"
        )
        if slip.get("checked_at"):
            info += f" · Check: {display_check_date(slip)} ({slip.get('checked_by')})"
        ctk.CTkLabel(header, text=info, font=FONT_SMALL, wraplength=860, justify="left").pack(
            anchor="w", pady=6
        )

        table = ctk.CTkScrollableFrame(content, fg_color=COLORS["card"])
        table.grid(row=0, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)

        hrow = ctk.CTkFrame(table, fg_color=("gray88", "gray28"))
        hrow.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        _place_table_row(
            hrow,
            self.LINE_HEADERS,
            [t for t, _ in self.LINE_HEADERS],
            header=True,
        )

        lines_body = ctk.CTkFrame(table, fg_color="transparent")
        lines_body.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 4))
        lines_body.grid_columnconfigure(0, weight=1)
        for line_idx, line in enumerate(slip.get("lines") or []):
            bg = ("gray95", "gray26") if line_idx % 2 == 0 else ("gray90", "gray22")
            lrow = ctk.CTkFrame(lines_body, fg_color=bg, corner_radius=4)
            lrow.pack(fill="x", pady=1)
            vals = [
                str(line.get("line_no") or ""),
                str(line.get("material_code") or ""),
                str(line.get("product_code") or ""),
                str(line.get("dg_case") or ""),
                str(line.get("color") or ""),
                str(line.get("logo") or ""),
                str(line.get("quantity") or ""),
                str(line.get("detail") or ""),
            ]
            _place_table_row(lrow, self.LINE_HEADERS, vals)

        if not self.readonly and self.can_write:
            ctk.CTkButton(
                footer,
                text="Check (Done)",
                fg_color=COLORS["success"][1],
                command=self._check,
            ).pack(side="right", padx=4)
        if self.readonly and self.is_admin:
            ctk.CTkButton(
                footer,
                text="Gỡ check (admin)",
                fg_color="#c62828",
                command=self._uncheck,
            ).pack(side="right", padx=4)
        ctk.CTkButton(footer, text="Export Excel", command=self._export).pack(side="right", padx=4)
        ctk.CTkButton(footer, text="Close", fg_color="transparent", command=self.destroy).pack(
            side="right"
        )
        show_dialog(self, top)

    def _check(self) -> None:
        actor = self.state.user.display_name or self.state.user.username
        supplier_db.check_supplier_slip(
            self.state.db,
            int(self.slip["id"]),
            actor=actor,
            actor_user_id=self.state.user.numeric_id(),
        )
        messagebox.showinfo("Supplier", "Đã check phiếu.", parent=self)
        self.on_changed()
        self.destroy()

    def _uncheck(self) -> None:
        if not messagebox.askyesno("Admin", "Gỡ check phiếu này? (ghi log)", parent=self):
            return
        actor = self.state.user.display_name or self.state.user.username
        supplier_db.uncheck_supplier_slip(
            self.state.db,
            int(self.slip["id"]),
            actor=actor,
            actor_user_id=self.state.user.numeric_id(),
        )
        messagebox.showinfo("Supplier", "Đã gỡ check.", parent=self)
        self.on_changed()
        self.destroy()

    def _export(self) -> None:
        default_name = default_export_filename(self.slip)
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Lưu phiếu Excel",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel", "*.xlsx")],
        )
        if not path:
            return

        def worker() -> None:
            try:
                export_slip_to_excel(self.slip, path, db=self.state.db)
                self.after(0, lambda: messagebox.showinfo("Export", f"Đã lưu:\n{path}", parent=self))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Export", str(exc), parent=self))

        threading.Thread(target=worker, daemon=True).start()
