"""Planning tab — monthly calendar with plan management."""

from __future__ import annotations

import calendar
from datetime import date
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core import supplier_db
from core.app_state import AppState
from core.permissions import MOD_DESIGN_PLANNING
from core.planning_service import (
    DEFAULT_EXCEL_MAP,
    PlanningValidationError,
    audit_action_label,
    check_status_label,
    day_all_confirmed,
    day_has_miss,
    describe_duplicate_plan,
    effective_check_status,
    effective_prepare_status,
    format_audit_log_line,
    format_check_display,
    format_check_timestamp,
    format_plan_change_line,
    format_plan_date_display,
    format_prepare_display,
    import_plans_from_excel,
    iso_in_days,
    iso_today,
    load_excel_mapping,
    plan_needs_delivery_date,
    prepare_status_label,
    save_excel_mapping,
    validate_plan_payload,
)
from core.utils import format_date_dd_mm_yyyy, normalize_text, parse_date_dd_mm_yyyy
from ui.dialog_utils import configure_dialog, create_dialog_layout, show_dialog
from ui.table_pager import TablePager, TablePagerBar
from ui.theme import COLORS, FONT_BODY, FONT_SMALL

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SESSION_OPTIONS = ["—", "Morning", "Afternoon"]

# Calendar palette — light / dark
CAL_EMPTY = ("#eef1f6", "#23262e")
CAL_PLANNED = ("#c7ddff", "#2a4a6b")
CAL_VERIFIED = ("#c8efd3", "#255038")
CAL_MISS = ("#ffb3b3", "#7a1f1f")
CAL_TODAY = COLORS["accent"][1]
CAL_SELECTED_BORDER = COLORS["accent"][1]
CELL_MIN_H = 78
CELL_MIN_W = 108
PLAN_DATE_PICK_KEYS = frozenset({"plan_date", "verify_date"})
OL_AUTOFILL_TO_FORM = {
    "production_no": "item_code",
    "supplier": "supplier",
    "quantity": "quantity",
}


def confirm_duplicate_plan(master, db, dg_case: str, *, exclude_id: int | None = None) -> bool:
    dup = db.find_planning_duplicate(dg_case, exclude_id=exclude_id)
    if not dup:
        return True
    msg = (
        "Đã có plan active cho DG Case này:\n\n"
        f"{describe_duplicate_plan(dup)}\n\n"
        "Mỗi DG Case là độc lập — bạn có chắc vẫn tạo/sửa thành plan trùng?"
    )
    return messagebox.askyesno("Cảnh báo plan trùng", msg, parent=master)


class DatePickerDialog(ctk.CTkToplevel):
    """Small calendar popup — returns dd-mm-yyyy via callback."""

    def __init__(
        self,
        master,
        *,
        title: str = "Select Date",
        initial: date | None = None,
        on_select,
    ):
        super().__init__(master)
        self.on_select = on_select
        self.title(title)
        configure_dialog(self, width=360, height=380, min_width=360, min_height=380, resizable=False, parent=master)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        today = date.today()
        start = initial or today
        self.view_year = start.year
        self.view_month = start.month
        self._selected = initial

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=14)

        nav = ctk.CTkFrame(body, fg_color="transparent")
        nav.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(nav, text="◀", width=32, height=28, command=self._prev).pack(side="left")
        self.month_label = ctk.CTkLabel(nav, text="", font=("Segoe UI", 14, "bold"))
        self.month_label.pack(side="left", expand=True)
        ctk.CTkButton(nav, text="▶", width=32, height=28, command=self._next).pack(side="right")

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        for i, name in enumerate(WEEKDAYS):
            head.grid_columnconfigure(i, weight=1)
            ctk.CTkLabel(head, text=name, font=("Segoe UI", 10, "bold"), text_color=COLORS["muted"]).grid(
                row=0, column=i, padx=2, pady=2
            )

        self.grid_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True, pady=(4, 0))
        for r in range(6):
            self.grid_frame.grid_rowconfigure(r, weight=1)
        for c in range(7):
            self.grid_frame.grid_columnconfigure(c, weight=1)

        ctk.CTkButton(body, text="Today", width=80, height=28, command=self._pick_today).pack(pady=(8, 0))
        self._render()

    def _prev(self) -> None:
        if self.view_month == 1:
            self.view_month, self.view_year = 12, self.view_year - 1
        else:
            self.view_month -= 1
        self._render()

    def _next(self) -> None:
        if self.view_month == 12:
            self.view_month, self.view_year = 1, self.view_year + 1
        else:
            self.view_month += 1
        self._render()

    def _pick_today(self) -> None:
        self._choose(date.today())

    def _choose(self, picked: date) -> None:
        self.on_select(format_date_dd_mm_yyyy(picked))
        self.destroy()

    def _render(self) -> None:
        self.month_label.configure(text=date(self.view_year, self.view_month, 1).strftime("%B %Y"))
        for w in self.grid_frame.winfo_children():
            w.destroy()

        today = date.today()
        for r, week in enumerate(calendar.monthcalendar(self.view_year, self.view_month)):
            for c, day_num in enumerate(week):
                if day_num == 0:
                    ctk.CTkFrame(self.grid_frame, fg_color="transparent", height=36).grid(
                        row=r, column=c, padx=2, pady=2, sticky="nsew"
                    )
                    continue
                d = date(self.view_year, self.view_month, day_num)
                is_today = d == today
                is_sel = self._selected == d
                btn = ctk.CTkButton(
                    self.grid_frame,
                    text=str(day_num),
                    width=36,
                    height=36,
                    fg_color=COLORS["accent"][1] if is_sel else ("gray85", "gray32"),
                    text_color=("white" if is_sel else ("#111", "#eee")),
                    border_width=2 if is_today else 0,
                    border_color=CAL_TODAY,
                    command=lambda dd=d: self._choose(dd),
                )
                btn.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")


class AddPlanDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        db,
        on_save,
        on_import_batch,
        initial_plan_date: str = "",
        lookup_from_ol=None,
    ):
        super().__init__(master)
        self.db = db
        self.on_save = on_save
        self.on_import_batch = on_import_batch
        self.lookup_from_ol = lookup_from_ol
        self.title("Add Plan")
        configure_dialog(self, width=640, height=680, min_width=600, min_height=620, resizable=True, parent=master)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)
        body.grid_rowconfigure(1, weight=1)
        body.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(head, text="Add Production Plan", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            head,
            text="Enter manually or import rows from Excel with configurable columns.",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(4, 12))

        tabs_wrap = ctk.CTkFrame(body, fg_color="transparent")
        tabs_wrap.grid(row=1, column=0, sticky="nsew")
        tabs_wrap.grid_rowconfigure(0, weight=1)
        tabs_wrap.grid_columnconfigure(0, weight=1)
        tabs = ctk.CTkTabview(tabs_wrap)
        tabs.grid(row=0, column=0, sticky="nsew")
        tabs.add("Manual Entry")
        tabs.add("Import Excel")

        self._build_manual_tab(tabs.tab("Manual Entry"), initial_plan_date)
        self._build_excel_tab(tabs.tab("Import Excel"))

    def _build_manual_tab(self, parent, initial_plan_date: str) -> None:
        self.vars = {
            "dg_case": ctk.StringVar(),
            "item_code": ctk.StringVar(),
            "supplier": ctk.StringVar(),
            "quantity": ctk.StringVar(),
            "plan_date": ctk.StringVar(value=initial_plan_date),
            "verify_date": ctk.StringVar(value=format_date_dd_mm_yyyy(date.today())),
            "session": ctk.StringVar(value="—"),
        }
        fields = [
            ("DG Case", "dg_case", "e.g. O-1249-01"),
            ("Production No", "item_code", "e.g. mã SP đầy đủ từ OL"),
            ("Supplier", "supplier", "e.g. NCC ABC — giao cho ai"),
            ("Quantity", "quantity", "e.g. 160"),
            ("Hạn giao tem", "plan_date", "để trống nếu chưa biết"),
            ("Ngày lập KH", "verify_date", "mặc định hôm nay"),
        ]
        for label, key, placeholder in fields:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=7)
            ctk.CTkLabel(row, text=label, width=110, anchor="w", font=FONT_BODY).pack(side="left")
            if key in PLAN_DATE_PICK_KEYS:
                ctk.CTkEntry(
                    row,
                    textvariable=self.vars[key],
                    placeholder_text=placeholder,
                    height=34,
                    state="readonly",
                ).pack(side="left", fill="x", expand=True, padx=(0, 6))
                ctk.CTkButton(
                    row,
                    text="Pick",
                    width=64,
                    height=34,
                    command=lambda k=key, lbl=label: self._pick_date(k, lbl),
                ).pack(side="left", padx=(0, 4))
                if key == "plan_date":
                    ctk.CTkButton(
                        row,
                        text="Clear",
                        width=64,
                        height=34,
                        fg_color="transparent",
                        border_width=1,
                        command=lambda k=key: self.vars[k].set(""),
                    ).pack(side="left")
            else:
                entry = ctk.CTkEntry(
                    row, textvariable=self.vars[key], placeholder_text=placeholder, height=34
                )
                entry.pack(side="left", fill="x", expand=True)
                if key == "dg_case":
                    entry.bind("<FocusOut>", lambda _e: self._autofill_from_ol())
                    entry.bind("<Return>", lambda _e: self._autofill_from_ol())

        srow = ctk.CTkFrame(parent, fg_color="transparent")
        srow.pack(fill="x", pady=7)
        ctk.CTkLabel(srow, text="Session", width=110, anchor="w", font=FONT_BODY).pack(side="left")
        ctk.CTkComboBox(
            srow,
            values=SESSION_OPTIONS,
            variable=self.vars["session"],
            state="readonly",
            width=180,
            height=34,
        ).pack(side="left")

        ctk.CTkButton(
            parent,
            text="Save Plan",
            height=36,
            fg_color=COLORS["accent"][1],
            command=self._save_manual,
        ).pack(anchor="e", pady=(18, 4))

    def _pick_date(self, key: str, label: str) -> None:
        initial: date | None = None
        parsed = parse_date_dd_mm_yyyy(self.vars[key].get())
        if parsed is not None:
            initial = parsed.date()
        DatePickerDialog(
            self,
            title=f"Select {label}",
            initial=initial,
            on_select=lambda value: self.vars[key].set(value),
        )

    def _build_excel_tab(self, parent) -> None:
        mapping = load_excel_mapping(self.db)
        self.map_vars = {k: ctk.StringVar(value=v) for k, v in mapping.items()}
        self.xls_path_var = ctk.StringVar()

        file_row = ctk.CTkFrame(parent, fg_color="transparent")
        file_row.pack(fill="x", pady=(4, 10))
        ctk.CTkEntry(file_row, textvariable=self.xls_path_var, placeholder_text="Excel file path…", height=34).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        ctk.CTkButton(file_row, text="Browse", width=90, height=34, command=self._browse_excel).pack(side="left")

        map_box = ctk.CTkFrame(parent, fg_color=COLORS["card"], corner_radius=8)
        map_box.pack(fill="x", pady=4)
        ctk.CTkLabel(
            map_box,
            text="Column mapping (Excel letters or 1-based numbers)",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", padx=12, pady=(10, 6))

        labels = [
            ("DG Case", "dg_case"),
            ("Production No", "item_code"),
            ("Supplier", "supplier"),
            ("Quantity", "quantity"),
            ("Hạn giao tem", "plan_date"),
            ("Ngày lập KH (opt.)", "verify_date"),
            ("Session (opt.)", "session"),
            ("Start row", "start_row"),
        ]
        grid = ctk.CTkFrame(map_box, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 12))
        for i, (label, key) in enumerate(labels):
            r, c = divmod(i, 2)
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=r, column=c, sticky="ew", padx=6, pady=4)
            grid.grid_columnconfigure(c, weight=1)
            ctk.CTkLabel(cell, text=label, width=100, anchor="w", font=FONT_SMALL).pack(side="left")
            ctk.CTkEntry(cell, textvariable=self.map_vars[key], width=70, height=30).pack(side="left")

        ctk.CTkLabel(
            parent,
            text="Tip: row 1 can be headers. Data import starts at Start row.",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(8, 4))

        btn_row = ctk.CTkFrame(parent, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(
            btn_row,
            text="Save Mapping",
            width=120,
            height=34,
            fg_color="transparent",
            border_width=1,
            command=self._save_mapping,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row,
            text="Import Plans",
            width=120,
            height=34,
            fg_color=COLORS["accent"][1],
            command=self._import_excel,
        ).pack(side="right")

    def _browse_excel(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("Excel", "*.xlsx *.xls"), ("All", "*.*")],
        )
        if path:
            self.xls_path_var.set(path)

    def _save_mapping(self) -> None:
        mapping = {k: v.get().strip() for k, v in self.map_vars.items()}
        save_excel_mapping(self.db, mapping)
        messagebox.showinfo("Import Excel", "Column mapping saved.", parent=self)

    def _autofill_from_ol(self) -> None:
        if self.lookup_from_ol is None:
            return
        found = self.lookup_from_ol(self.vars["dg_case"].get())
        if not found:
            return
        for ol_key, form_key in OL_AUTOFILL_TO_FORM.items():
            value = normalize_text(found.get(ol_key))
            if value and not normalize_text(self.vars[form_key].get()):
                self.vars[form_key].set(value)

    def _save_manual(self) -> None:
        try:
            payload = validate_plan_payload(
                dg_case=self.vars["dg_case"].get(),
                item_code=self.vars["item_code"].get(),
                supplier=self.vars["supplier"].get(),
                quantity=self.vars["quantity"].get(),
                plan_date=self.vars["plan_date"].get(),
                verify_date=self.vars["verify_date"].get(),
                session=self.vars["session"].get(),
            )
        except PlanningValidationError as exc:
            messagebox.showerror("Add Plan", str(exc), parent=self)
            return
        if not confirm_duplicate_plan(self, self.db, payload["dg_case"]):
            return
        self.on_save(payload)
        self.destroy()

    def _import_excel(self) -> None:
        path = self.xls_path_var.get().strip()
        if not path:
            messagebox.showwarning("Import Excel", "Select an Excel file first.", parent=self)
            return
        mapping = {k: v.get().strip() or DEFAULT_EXCEL_MAP[k] for k, v in self.map_vars.items()}
        save_excel_mapping(self.db, mapping)
        try:
            plans, errors = import_plans_from_excel(path, mapping)
        except (PlanningValidationError, FileNotFoundError, OSError) as exc:
            messagebox.showerror("Import Excel", str(exc), parent=self)
            return
        if not plans:
            messagebox.showwarning("Import Excel", "No valid rows found.", parent=self)
            return
        self.on_import_batch(plans)
        msg = f"Imported {len(plans)} plan(s)."
        if errors:
            msg += f"\n\nSkipped {len(errors)} row(s):\n" + "\n".join(errors[:5])
            if len(errors) > 5:
                msg += f"\n… and {len(errors) - 5} more."
        messagebox.showinfo("Import Excel", msg, parent=self)
        self.destroy()


class PrepareLabelsDialog(ctk.CTkToplevel):
    AUTO_STOCK_LABEL = "— Tự động —"

    TABLE_HEADERS = (
        ("", 36),
        ("Mã NPL", 100),
        ("Tên NPL", 180),
        ("Mô tả", 140),
        ("Quantity", 72),
        ("Gợi ý", 88),
        ("Tồn kho", 148),
    )

    def __init__(
        self,
        master,
        *,
        state: AppState,
        entry_id: int,
        plan: dict,
        on_saved,
    ):
        super().__init__(master)
        self.app_state = state
        self.entry_id = entry_id
        self.plan = plan
        self.on_saved = on_saved
        self.checkbox_vars: dict[str, ctk.BooleanVar] = {}
        self.stock_map_vars: dict[str, ctk.StringVar] = {}
        self.candidates: list[dict] = []
        self._stock_label_to_id: dict[str, int | None] = {self.AUTO_STOCK_LABEL: None}
        self._stock_id_to_label: dict[int, str] = {}
        self._stock_choice_labels: list[str] = [self.AUTO_STOCK_LABEL]

        already = effective_prepare_status(plan) == "prepared"
        self.title("Update Prepare" if already else "Prepare Labels")
        configure_dialog(self, width=1040, height=640, min_width=960, min_height=560, resizable=True, parent=master)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        _, header, content, footer = create_dialog_layout(self)

        dg = normalize_text(plan.get("dg_case"))
        prod = normalize_text(plan.get("item_code"))
        supplier = normalize_text(plan.get("supplier"))
        ctk.CTkLabel(header, text="Prepare — Select Labels", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=f"DG Case {dg} · {prod} · {supplier}",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(4, 4))
        ctk.CTkLabel(
            header,
            text=(
                "Label rows from bảng kê (Số S/O). Cột «Tồn kho»: để Tự động thì check phiếu map theo rule; "
                "chọn loại cụ thể để ghi đè (poly, satin, nhãn lạ…)."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=960,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        toolbar = ctk.CTkFrame(header, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 4))
        ctk.CTkButton(toolbar, text="Select all", width=90, height=30, command=self._select_all).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(toolbar, text="Clear all", width=90, height=30, command=self._clear_all).pack(
            side="left"
        )
        self.summary_label = ctk.CTkLabel(toolbar, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.summary_label.pack(side="right")

        table_wrap = ctk.CTkFrame(content, fg_color=COLORS["card"], corner_radius=10)
        table_wrap.grid(row=0, column=0, sticky="nsew")
        table_wrap.grid_rowconfigure(1, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        col_header = ctk.CTkFrame(table_wrap, fg_color=("gray88", "gray28"), corner_radius=0)
        col_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))
        for title, width in self.TABLE_HEADERS:
            ctk.CTkLabel(
                col_header,
                text=title,
                width=width,
                anchor="center",
                font=("Segoe UI", 11, "bold"),
            ).pack(side="left", padx=4, pady=8)

        self.rows_frame = ctk.CTkScrollableFrame(table_wrap, fg_color="transparent")
        self.rows_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        confirm_text = "Confirm Update" if already else "Confirm Prepare"
        ctk.CTkButton(
            footer,
            text=confirm_text,
            width=150,
            height=36,
            fg_color=COLORS["success"][1],
            command=self._confirm,
        ).pack(side="right")
        ctk.CTkButton(
            footer,
            text="Cancel",
            width=90,
            height=36,
            fg_color="transparent",
            command=self.destroy,
        ).pack(side="right", padx=(0, 8))

        self._load_rows()
        show_dialog(self, master)

    def _init_stock_choices(self) -> None:
        from core.npl_stock_service import NplStockService

        self._stock_label_to_id = {self.AUTO_STOCK_LABEL: None}
        self._stock_id_to_label = {}
        labels = [self.AUTO_STOCK_LABEL]
        for item in NplStockService(self.app_state.db).list_stock_type_choices():
            type_id = int(item["id"])
            unit = normalize_text(item.get("unit_label")) or "pcs"
            label = f"{normalize_text(item.get('name'))} ({unit})"
            if label in self._stock_label_to_id and self._stock_label_to_id[label] != type_id:
                label = f"{label} #{type_id}"
            self._stock_label_to_id[label] = type_id
            self._stock_id_to_label[type_id] = label
            labels.append(label)
        self._stock_choice_labels = labels

    def _load_rows(self) -> None:
        from core.npl_stock_service import suggest_stock_mapping_label
        from core.prepare_service import item_key, list_label_candidates

        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.checkbox_vars.clear()
        self.stock_map_vars.clear()
        self._init_stock_choices()

        bom_df = self.app_state.get_active_bom_ke_df()
        if bom_df is None or bom_df.empty:
            ctk.CTkLabel(
                self.rows_frame,
                text="Chưa đọc bảng kê — vào Setup tab và bấm Đọc bảng kê trước.",
                font=FONT_BODY,
                text_color=COLORS["warning"][1],
            ).pack(pady=24, padx=12)
            self.summary_label.configure(text="0 candidates")
            return

        self.candidates = list_label_candidates(bom_df, str(self.plan.get("dg_case", "")))
        if not self.candidates:
            ctk.CTkLabel(
                self.rows_frame,
                text="Không tìm thấy dòng nhãn nào cho DG Case này trong bảng kê.",
                font=FONT_BODY,
                text_color=COLORS["muted"],
            ).pack(pady=24, padx=12)
            self.summary_label.configure(text="0 candidates")
            return

        saved = self.app_state.db.list_planning_prepare_items(self.entry_id)
        saved_by_key = {
            item_key(str(r.get("ma_npl")), int(r.get("row_index", 0))): r for r in saved
        }
        default_checked = bool(saved_by_key)

        for idx, row in enumerate(self.candidates):
            key = str(row["item_key"])
            var = ctk.BooleanVar(value=key in saved_by_key if default_checked else False)
            self.checkbox_vars[key] = var

            saved_row = saved_by_key.get(key)
            saved_type_id = saved_row.get("npl_stock_type_id") if saved_row else None
            if saved_type_id:
                default_stock_label = self._stock_id_to_label.get(int(saved_type_id), self.AUTO_STOCK_LABEL)
            else:
                default_stock_label = self.AUTO_STOCK_LABEL
            stock_var = ctk.StringVar(value=default_stock_label)
            self.stock_map_vars[key] = stock_var

            auto_hint = suggest_stock_mapping_label(
                self.app_state.db,
                ma_npl=str(row.get("ma_npl", "")),
                ten_npl=str(row.get("ten_npl", "")),
                mo_ta=str(row.get("mo_ta", "")),
            )

            bg = ("gray95", "gray26") if idx % 2 == 0 else ("gray90", "gray22")
            line = ctk.CTkFrame(self.rows_frame, fg_color=bg, corner_radius=6)
            line.pack(fill="x", pady=2)

            ctk.CTkCheckBox(line, text="", variable=var, width=36).pack(side="left", padx=(8, 4), pady=8)
            from core.prepare_service import format_prepare_quantity

            for text, width in [
                (row.get("ma_npl", ""), 100),
                (row.get("ten_npl", ""), 180),
                (row.get("mo_ta", ""), 140),
                (format_prepare_quantity(row.get("quantity")), 72),
            ]:
                ctk.CTkLabel(
                    line,
                    text=str(text),
                    width=width,
                    anchor="w" if width > 100 else "center",
                    font=FONT_SMALL,
                    wraplength=width - 8 if width >= 140 else 0,
                    justify="left",
                ).pack(side="left", padx=4, pady=8)

            ctk.CTkLabel(
                line,
                text=auto_hint,
                width=88,
                anchor="w",
                font=FONT_SMALL,
                text_color=COLORS["muted"],
            ).pack(side="left", padx=4, pady=8)

            ctk.CTkOptionMenu(
                line,
                variable=stock_var,
                values=self._stock_choice_labels,
                width=144,
                height=28,
                font=FONT_SMALL,
            ).pack(side="left", padx=(4, 8), pady=8)

        self.summary_label.configure(text=f"{len(self.candidates)} candidate(s)")

    def _select_all(self) -> None:
        for var in self.checkbox_vars.values():
            var.set(True)

    def _clear_all(self) -> None:
        for var in self.checkbox_vars.values():
            var.set(False)

    def _selected_items(self) -> list[dict]:
        selected: list[dict] = []
        for row in self.candidates:
            key = str(row["item_key"])
            if not self.checkbox_vars.get(key, ctk.BooleanVar(value=False)).get():
                continue
            item = dict(row)
            stock_label = self.stock_map_vars.get(key, ctk.StringVar(value=self.AUTO_STOCK_LABEL)).get()
            type_id = self._stock_label_to_id.get(stock_label)
            if type_id:
                item["npl_stock_type_id"] = type_id
            else:
                item.pop("npl_stock_type_id", None)
            selected.append(item)
        return selected

    def _confirm(self) -> None:
        if not self.candidates:
            messagebox.showwarning("Prepare", "Không có dòng nhãn để chọn.", parent=self)
            return
        selected = self._selected_items()
        if not selected:
            messagebox.showwarning("Prepare", "Chọn ít nhất một dòng nhãn.", parent=self)
            return
        actor = self.app_state.user.display_name or self.app_state.user.username
        self.app_state.db.save_planning_prepare_items(
            self.entry_id,
            selected,
            prepare_by=actor,
            actor_user_id=self.app_state.user.numeric_id(),
        )
        messagebox.showinfo(
            "Prepare",
            f"Đã lưu {len(selected)} dòng nhãn cho bước Làm Phiếu.",
            parent=self,
        )
        self.on_saved()
        self.destroy()


class EditPlanDialog(ctk.CTkToplevel):
    """Sửa plan chưa confirmed."""

    def __init__(self, master, *, db, plan: dict, on_saved, actor: str = "", lookup_from_ol=None) -> None:
        super().__init__(master)
        self.db = db
        self.plan = plan
        self.entry_id = int(plan["id"])
        self.on_saved = on_saved
        self.actor = actor
        self.lookup_from_ol = lookup_from_ol
        self.title("Sửa plan")
        configure_dialog(self, width=560, height=520, min_width=520, min_height=480, parent=master)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)
        ctk.CTkLabel(body, text="Sửa Production Plan", font=("Segoe UI", 16, "bold")).pack(anchor="w")

        self.vars = {
            "dg_case": ctk.StringVar(value=str(plan.get("dg_case") or "")),
            "item_code": ctk.StringVar(value=str(plan.get("item_code") or "")),
            "supplier": ctk.StringVar(value=str(plan.get("supplier") or "")),
            "quantity": ctk.StringVar(value=str(plan.get("quantity") or "")),
            "plan_date": ctk.StringVar(value=str(plan.get("plan_date") or "")),
            "verify_date": ctk.StringVar(value=str(plan.get("verify_date") or "")),
            "session": ctk.StringVar(value=str(plan.get("session") or "—")),
        }
        fields = [
            ("DG Case", "dg_case", ""),
            ("Production No", "item_code", ""),
            ("Supplier", "supplier", ""),
            ("Quantity", "quantity", ""),
            ("Hạn giao tem", "plan_date", "để trống nếu chưa biết"),
            ("Ngày lập KH", "verify_date", "dd-mm-yyyy"),
        ]
        for label, key, placeholder in fields:
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=6)
            ctk.CTkLabel(row, text=label, width=110, anchor="w", font=FONT_BODY).pack(side="left")
            if key in PLAN_DATE_PICK_KEYS:
                ctk.CTkEntry(
                    row, textvariable=self.vars[key], height=34, state="readonly"
                ).pack(side="left", fill="x", expand=True, padx=(0, 6))
                ctk.CTkButton(
                    row,
                    text="Pick",
                    width=64,
                    height=34,
                    command=lambda k=key, lbl=label: self._pick_date(k, lbl),
                ).pack(side="left", padx=(0, 4))
                if key == "plan_date":
                    ctk.CTkButton(
                        row,
                        text="Clear",
                        width=64,
                        height=34,
                        fg_color="transparent",
                        border_width=1,
                        command=lambda k=key: self.vars[k].set(""),
                    ).pack(side="left")
            else:
                ctk.CTkEntry(row, textvariable=self.vars[key], placeholder_text=placeholder, height=34).pack(
                    side="left", fill="x", expand=True
                )

        srow = ctk.CTkFrame(body, fg_color="transparent")
        srow.pack(fill="x", pady=6)
        ctk.CTkLabel(srow, text="Session", width=110, anchor="w", font=FONT_BODY).pack(side="left")
        ctk.CTkComboBox(
            srow,
            values=SESSION_OPTIONS,
            variable=self.vars["session"],
            state="readonly",
            width=180,
            height=34,
        ).pack(side="left")

        brow = ctk.CTkFrame(body, fg_color="transparent")
        brow.pack(fill="x", pady=(16, 0))
        ctk.CTkButton(
            brow,
            text="Lịch sử",
            fg_color="transparent",
            command=self._open_history,
        ).pack(side="left")
        ctk.CTkButton(brow, text="Hủy", fg_color="transparent", command=self.destroy).pack(side="right", padx=4)
        ctk.CTkButton(
            brow, text="Lưu", fg_color=COLORS["success"][1], command=self._save
        ).pack(side="right")
        show_dialog(self, master)

    def _pick_date(self, key: str, label: str) -> None:
        parsed = parse_date_dd_mm_yyyy(self.vars[key].get())
        initial = parsed.date() if parsed is not None else None
        DatePickerDialog(
            self,
            title=label,
            initial=initial,
            on_select=lambda value: self.vars[key].set(value),
        )

    def _open_history(self) -> None:
        PlanHistoryDialog(self, db=self.db, entry_id=self.entry_id, plan=self.plan)

    def _save(self) -> None:
        try:
            payload = validate_plan_payload(
                dg_case=self.vars["dg_case"].get(),
                item_code=self.vars["item_code"].get(),
                supplier=self.vars["supplier"].get(),
                quantity=self.vars["quantity"].get(),
                plan_date=self.vars["plan_date"].get(),
                verify_date=self.vars["verify_date"].get(),
                session=self.vars["session"].get(),
            )
        except PlanningValidationError as exc:
            messagebox.showwarning("Planning", str(exc), parent=self)
            return
        if not confirm_duplicate_plan(self, self.db, payload["dg_case"], exclude_id=self.entry_id):
            return
        actor = self.actor
        try:
            self.db.update_planning_entry(
                self.entry_id,
                dg_case=payload["dg_case"],
                item_code=payload["item_code"],
                supplier=payload["supplier"],
                quantity=payload["quantity"],
                plan_date=payload["plan_date"],
                plan_date_iso=payload["plan_date_iso"],
                verify_date=payload["verify_date"],
                verify_date_iso=payload["verify_date_iso"],
                session=payload["session"],
                actor=actor,
            )
        except Exception as exc:
            messagebox.showerror("Planning", str(exc), parent=self)
            return
        self.on_saved()
        self.destroy()


class PlanHistoryDialog(ctk.CTkToplevel):
    """Lịch sử thay đổi một plan — truy xuất ngày lập KH và các lần sửa."""

    def __init__(self, master, *, db, entry_id: int, plan: dict) -> None:
        super().__init__(master)
        self.db = db
        self.entry_id = entry_id
        self.plan = plan
        self.title("Lịch sử plan")
        configure_dialog(self, width=820, height=520, min_width=720, min_height=420, resizable=True, parent=master)
        self.transient(master.winfo_toplevel())

        _, header, content, footer = create_dialog_layout(self)
        dg = normalize_text(plan.get("dg_case")) or "—"
        ctk.CTkLabel(header, text=f"Lịch sử · {dg}", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=(
                f"Hạn giao {plan.get('plan_date', '—')} · Ngày lập KH {plan.get('verify_date', '—')} · "
                f"{plan.get('item_code', '')}"
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        scroll = ctk.CTkScrollableFrame(content, fg_color=COLORS["card"], corner_radius=10)
        scroll.grid(row=0, column=0, sticky="nsew")

        entries = db.list_planning_entry_history(entry_id)
        if not entries:
            ctk.CTkLabel(
                scroll,
                text="Chưa có lịch sử ghi nhận.",
                font=FONT_BODY,
                text_color=COLORS["muted"],
            ).pack(pady=24)
        else:
            for idx, entry in enumerate(entries):
                self._row(scroll, entry, idx)

        ctk.CTkButton(footer, text="Đóng", width=90, height=36, fg_color="transparent", command=self.destroy).pack(
            side="right"
        )
        show_dialog(self, master)

    def _row(self, parent, entry: dict, row_idx: int) -> None:
        bg = ("gray95", "gray26") if row_idx % 2 == 0 else ("gray90", "gray22")
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=6)
        row.pack(fill="x", padx=10, pady=4)

        line = format_audit_log_line(entry)
        for part in line.split("\n"):
            ctk.CTkLabel(row, text=part.strip(), font=FONT_SMALL, anchor="w", justify="left").pack(
                anchor="w", padx=10, pady=(4 if part == line.split("\n")[0] else 0, 2)
            )
        detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
        snap = detail.get("after") or detail.get("before") or {}
        if snap and str(entry.get("action")) == "created":
            ctk.CTkLabel(
                row,
                text=f"Snapshot: Giao {snap.get('plan_date', '—')} · Lập KH {snap.get('verify_date', '—')}",
                font=FONT_SMALL,
                text_color=COLORS["muted"],
                anchor="w",
            ).pack(anchor="w", padx=10, pady=(0, 6))


class DayDetailDialog(ctk.CTkToplevel):
    TABLE_HEADERS = (
        ("DG Case", 100),
        ("Production No", 118),
        ("Supplier", 96),
        ("Qty", 48),
        ("Hạn giao tem", 88),
        ("Ngày lập KH", 88),
        ("Session", 68),
        ("Check", 92),
        ("Checked At", 132),
        ("Prepare", 100),
    )

    def __init__(
        self,
        master,
        *,
        db,
        day: date,
        on_confirm,
        on_prepare,
        on_remove,
        on_refresh,
        on_add_plan=None,
        can_write: bool = True,
        actor: str = "",
        lookup_from_ol=None,
    ):
        super().__init__(master)
        self.db = db
        self.day = day
        self.on_confirm = on_confirm
        self.on_prepare = on_prepare
        self.on_remove = on_remove
        self.on_refresh = on_refresh
        self.on_add_plan = on_add_plan
        self._can_write = can_write
        self.actor = actor
        self.lookup_from_ol = lookup_from_ol
        self.selected_id: int | None = None
        self._plans: list[dict] = []
        self._pager = TablePager()
        self.title("Day Plan Details")
        configure_dialog(self, width=1180, height=600, min_width=1000, min_height=500, resizable=True, parent=master)
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)

        _, header, content, footer = create_dialog_layout(self, padx=24, pady=20)

        ctk.CTkLabel(
            header,
            text=day.strftime("%A, %d-%m-%Y"),
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="center")
        self.subtitle = ctk.CTkLabel(header, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.subtitle.pack(anchor="center", pady=(4, 12))

        action_bar = ctk.CTkFrame(header, fg_color="transparent")
        action_bar.pack(anchor="center", pady=(0, 8))
        btn_state = "normal" if self._can_write else "disabled"
        ctk.CTkButton(
            action_bar,
            text="Check phiếu (đã lưu)",
            width=160,
            height=34,
            fg_color=COLORS["success"][1],
            command=self._confirm_selected,
            state=btn_state,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            action_bar,
            text="Prepare",
            width=100,
            height=34,
            command=self._prepare_selected,
            state=btn_state,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            action_bar,
            text="Sửa plan",
            width=100,
            height=34,
            command=self._edit_selected,
            state=btn_state,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            action_bar,
            text="Lịch sử",
            width=90,
            height=34,
            command=self._history_selected,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            action_bar,
            text="Remove Plan",
            width=110,
            height=34,
            fg_color="#c62828",
            hover_color="#b71c1c",
            command=self._remove_selected,
            state=btn_state,
        ).pack(side="left", padx=6)
        ctk.CTkLabel(
            action_bar,
            text="Select a row, then click an action",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(side="left", padx=(12, 0))

        table_wrap = ctk.CTkFrame(content, fg_color=COLORS["card"], corner_radius=10)
        table_wrap.grid(row=0, column=0, sticky="nsew")
        table_wrap.grid_rowconfigure(2, weight=1)
        table_wrap.grid_columnconfigure(0, weight=1)

        col_header = ctk.CTkFrame(table_wrap, fg_color=("gray88", "gray28"), corner_radius=0)
        col_header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 0))
        for i, (title, width) in enumerate(self.TABLE_HEADERS):
            col_header.grid_columnconfigure(i, weight=1, uniform="col")
            ctk.CTkLabel(
                col_header,
                text=title,
                width=width,
                anchor="center",
                font=("Segoe UI", 11, "bold"),
            ).grid(row=0, column=i, sticky="nsew", padx=4, pady=8)

        self._pager_bar = TablePagerBar(
            table_wrap,
            self._pager,
            on_change=self._render_plan_page,
            placeholder="Lọc DG, SP, NCC…",
        )
        self._pager_bar.set_filter_handler(self._plan_quick_filter)
        self._pager_bar.grid(row=1, column=0, sticky="ew", padx=12, pady=(6, 0))

        self.rows_frame = ctk.CTkScrollableFrame(table_wrap, fg_color="transparent")
        self.rows_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(0, 12))

        ctk.CTkButton(footer, text="Close", width=90, height=36, fg_color="transparent", command=self._close).pack(
            anchor="center"
        )
        self._reload_rows()
        show_dialog(self, master)

    def _close(self) -> None:
        self.destroy()

    @staticmethod
    def _plan_quick_filter(plan: dict, query: str) -> bool:
        blob = " ".join(
            [
                normalize_text(plan.get("dg_case")),
                normalize_text(plan.get("item_code")),
                normalize_text(plan.get("supplier")),
                normalize_text(plan.get("session")),
                str(plan.get("quantity") or ""),
            ]
        ).lower()
        return query in blob

    def _reload_rows(self) -> None:
        iso = self.day.strftime("%Y-%m-%d")
        self._plans = self.db.list_planning_entries_for_day(iso)
        miss_n = sum(1 for p in self._plans if effective_check_status(p) == "miss")
        confirmed_n = sum(1 for p in self._plans if effective_check_status(p) == "confirmed")
        self.subtitle.configure(
            text=f"{len(self._plans)} item(s) · {confirmed_n} confirmed · {miss_n} miss"
        )
        self._pager.set_items(self._plans, filter_fn=self._plan_quick_filter, reset_page=False)
        self._render_plan_page()

    def _render_plan_page(self) -> None:
        for w in self.rows_frame.winfo_children():
            w.destroy()
        page_items = self._pager.page_items()
        self._pager_bar.refresh_info()
        if not page_items and not self._plans:
            empty = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
            empty.pack(pady=24, padx=12, anchor="center")
            ctk.CTkLabel(
                empty,
                text="No plans scheduled for this day.",
                font=FONT_BODY,
                text_color=COLORS["muted"],
            ).pack(pady=(0, 12))
            if self.on_add_plan is not None:
                ctk.CTkButton(
                    empty,
                    text="+ Add Plan for This Day",
                    fg_color=COLORS["accent"][1],
                    command=self._add_plan,
                ).pack()
            return
        if not page_items:
            ctk.CTkLabel(
                self.rows_frame,
                text="Không có plan khớp bộ lọc.",
                font=FONT_BODY,
                text_color=COLORS["muted"],
            ).pack(pady=20)
            return

        for idx, plan in enumerate(page_items):
            self._render_row(plan, idx)

    def _edit_selected(self) -> None:
        if self.selected_id is None:
            messagebox.showinfo("Day Plans", "Chọn một dòng trước.", parent=self)
            return
        plan = next((p for p in self._plans if int(p["id"]) == self.selected_id), None)
        if not plan:
            return
        if effective_check_status(plan) == "confirmed":
            messagebox.showinfo("Day Plans", "Plan đã lưu — không sửa được.", parent=self)
            return
        EditPlanDialog(
            self,
            db=self.db,
            plan=plan,
            actor=self.actor,
            lookup_from_ol=self.lookup_from_ol,
            on_saved=lambda: (self._reload_rows(), self.on_refresh()),
        )

    def _history_selected(self) -> None:
        if self.selected_id is None:
            messagebox.showinfo("Day Plans", "Chọn một dòng trước.", parent=self)
            return
        plan = next((p for p in self._plans if int(p["id"]) == self.selected_id), None)
        if not plan:
            return
        PlanHistoryDialog(self, db=self.db, entry_id=int(plan["id"]), plan=plan)

    def _select_row(self, entry_id: int) -> None:
        self.selected_id = entry_id
        self._reload_rows()

    def _bind_select_row(self, widget, entry_id: int) -> None:
        def handler(_event, eid: int = entry_id) -> None:
            self._select_row(eid)

        def apply(w: ctk.CTkBaseClass) -> None:
            w.bind("<Button-1>", handler)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
            for child in w.winfo_children():
                apply(child)

        apply(widget)

    def _status_color(self, kind: str, status: str) -> str:
        if kind == "check":
            if status == "confirmed":
                return COLORS["success"][1]
            if status == "miss":
                return "#ef5350"
            if status == "no_date":
                return COLORS["accent"][1]
            return COLORS["warning"][1]
        if status == "prepared":
            return COLORS["success"][1]
        return COLORS["muted"][1]

    def _render_row(self, plan: dict, row_idx: int) -> None:
        pid = int(plan["id"])
        check = effective_check_status(plan)
        prepare = effective_prepare_status(plan)
        session = normalize_text(plan.get("session")) or "—"
        selected = self.selected_id == pid
        if selected:
            bg = COLORS["accent"]
        else:
            bg = ("gray95", "gray26") if row_idx % 2 == 0 else ("gray90", "gray22")

        row = ctk.CTkFrame(self.rows_frame, fg_color=bg, corner_radius=6)
        row.pack(fill="x", pady=2)
        for i in range(len(self.TABLE_HEADERS)):
            row.grid_columnconfigure(i, weight=1, uniform="col")

        check_at = ""
        if check == "confirmed":
            check_at = format_check_timestamp(plan.get("check_at")) or "—"

        values = [
            normalize_text(plan.get("dg_case")),
            normalize_text(plan.get("item_code")),
            normalize_text(plan.get("supplier")) or "—",
            str(plan.get("quantity", "")),
            normalize_text(plan.get("plan_date")) or "—",
            normalize_text(plan.get("verify_date")),
            session,
            format_check_display(plan),
            check_at,
            format_prepare_display(plan),
        ]
        for i, (text, (title, width)) in enumerate(zip(values, self.TABLE_HEADERS)):
            label_kwargs: dict = {
                "text": text,
                "width": width,
                "anchor": "center",
                "justify": "center",
                "font": FONT_SMALL,
            }
            if title == "Check":
                label_kwargs["font"] = ("Segoe UI", 11, "bold")
                label_kwargs["text_color"] = self._status_color("check", check)
            elif title == "Prepare":
                label_kwargs["font"] = ("Segoe UI", 11, "bold")
                label_kwargs["text_color"] = self._status_color("prepare", prepare)
            ctk.CTkLabel(row, **label_kwargs).grid(row=0, column=i, sticky="nsew", padx=4, pady=8)

        self._bind_select_row(row, pid)

    def _confirm_selected(self) -> None:
        if self.selected_id is None:
            messagebox.showinfo("Day Plans", "Select a row first.", parent=self)
            return
        plan = self.db.get_planning_entry(self.selected_id)
        if not plan:
            messagebox.showwarning("Day Plans", "Plan not found.", parent=self)
            return
        if effective_check_status(plan) == "confirmed":
            messagebox.showinfo("Day Plans", "Tem đã lưu (đã check phiếu).", parent=self)
            return
        if plan_needs_delivery_date(plan):
            messagebox.showwarning(
                "Day Plans",
                "Plan chưa có hạn giao tem.\n\nSửa plan và nhập hạn giao trước khi check phiếu.",
                parent=self,
            )
            return
        self.on_confirm(self.selected_id)
        self.on_refresh()
        self._reload_rows()

    def _prepare_selected(self) -> None:
        if self.selected_id is None:
            messagebox.showinfo("Day Plans", "Select a row first.", parent=self)
            return
        self.on_prepare(self.selected_id, self._reload_rows)

    def _remove_selected(self) -> None:
        if self.selected_id is None:
            messagebox.showinfo("Day Plans", "Select a row first.", parent=self)
            return
        plan = self.db.get_planning_entry(self.selected_id)
        if not plan:
            messagebox.showwarning("Day Plans", "Plan not found.", parent=self)
            return
        if int(plan.get("is_deleted") or 0) == 1:
            messagebox.showinfo("Day Plans", "This plan was already removed.", parent=self)
            return
        dg = normalize_text(plan.get("dg_case"))
        item = normalize_text(plan.get("item_code"))
        supplier = normalize_text(plan.get("supplier"))
        if not messagebox.askyesno(
            "Remove Plan",
            f"Remove this plan from the calendar?\n\n{dg} · {item} · {supplier}\n\n"
            "The record is kept in the database and can be reviewed in View Log.",
            parent=self,
        ):
            return
        self.on_remove(self.selected_id)
        self.selected_id = None
        self.on_refresh()
        self._reload_rows()

    def _add_plan(self) -> None:
        if self.on_add_plan is not None:
            self.on_add_plan()
        self._close()


class PlanningPanel(ctk.CTkFrame):
    def __init__(self, master, state: AppState, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self._can_write = state.user.can_write(MOD_DESIGN_PLANNING)
        today = date.today()
        self.view_year = today.year
        self.view_month = today.month
        self.selected_day: date | None = None
        self._plans_by_day: dict[str, list[dict]] = {}
        self._day_cells: dict[date, ctk.CTkFrame] = {}
        self._click_timer: str | None = None
        self._build()
        self._reload_calendar()

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 8))
        ctk.CTkLabel(header, text="Planning", font=("Segoe UI", 22, "bold")).pack(side="left")

        nav = ctk.CTkFrame(header, fg_color="transparent")
        nav.pack(side="right")
        ctk.CTkButton(nav, text="◀", width=36, height=32, command=self._prev_month).pack(side="left", padx=3)
        self.month_label = ctk.CTkLabel(nav, text="", font=("Segoe UI", 16, "bold"), width=168)
        self.month_label.pack(side="left", padx=8)
        ctk.CTkButton(nav, text="▶", width=36, height=32, command=self._next_month).pack(side="left", padx=3)
        ctk.CTkButton(nav, text="Today", width=72, height=32, command=self._go_today).pack(side="left", padx=(10, 0))

        toolbar = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        toolbar.pack(fill="x", padx=20, pady=(0, 10))
        tb = ctk.CTkFrame(toolbar, fg_color="transparent")
        tb.pack(fill="x", padx=14, pady=10)
        write_state = "normal" if self._can_write else "disabled"
        ctk.CTkButton(
            tb,
            text="+ Add Plan",
            width=120,
            height=34,
            fg_color=COLORS["accent"][1],
            command=self._open_add_plan,
            state=write_state,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(tb, text="Check Plan", width=110, height=34, command=self._open_check_plan).pack(side="left", padx=4)
        ctk.CTkButton(tb, text="Reminders", width=110, height=34, command=self._open_reminders).pack(side="left", padx=4)
        ctk.CTkButton(tb, text="View Log", width=100, height=34, command=self._open_planning_log).pack(side="left", padx=4)
        self.summary_label = ctk.CTkLabel(tb, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.summary_label.pack(side="right", padx=4)

        legend = ctk.CTkFrame(toolbar, fg_color="transparent")
        legend.pack(fill="x", padx=14, pady=(0, 10))
        for label, color in [
            ("Empty", CAL_EMPTY[1]),
            ("Scheduled", CAL_PLANNED[1]),
            ("All confirmed", CAL_VERIFIED[1]),
            ("Miss", CAL_MISS[1]),
        ]:
            item = ctk.CTkFrame(legend, fg_color="transparent")
            item.pack(side="left", padx=(0, 16))
            swatch = ctk.CTkFrame(item, width=14, height=14, fg_color=color, corner_radius=4)
            swatch.pack(side="left", padx=(0, 6))
            swatch.pack_propagate(False)
            ctk.CTkLabel(item, text=label, font=FONT_SMALL, text_color=COLORS["muted"]).pack(side="left")
        ctk.CTkLabel(
            legend,
            text="Double-click a day to view plans",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(side="right")

        cal_wrap = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        cal_wrap.pack(fill="both", expand=True, padx=20, pady=(0, 16))
        cal_wrap.grid_columnconfigure(0, weight=1)
        cal_wrap.grid_rowconfigure(1, weight=1)

        weekday_bar = ctk.CTkFrame(cal_wrap, fg_color="transparent")
        weekday_bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))
        for i, name in enumerate(WEEKDAYS):
            weekday_bar.grid_columnconfigure(i, weight=1, uniform="wd")
            ctk.CTkLabel(
                weekday_bar,
                text=name,
                font=("Segoe UI", 12, "bold"),
                text_color=COLORS["muted"],
            ).grid(row=0, column=i, sticky="nsew")

        self.calendar_grid = ctk.CTkFrame(cal_wrap, fg_color="transparent")
        self.calendar_grid.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        for r in range(6):
            self.calendar_grid.grid_rowconfigure(r, weight=1, uniform="cal", minsize=CELL_MIN_H)
        for c in range(7):
            self.calendar_grid.grid_columnconfigure(c, weight=1, uniform="cal", minsize=CELL_MIN_W)

    def _month_title(self) -> str:
        return date(self.view_year, self.view_month, 1).strftime("%B %Y")

    def _prev_month(self) -> None:
        if self.view_month == 1:
            self.view_month = 12
            self.view_year -= 1
        else:
            self.view_month -= 1
        self.selected_day = None
        self._reload_calendar()

    def _next_month(self) -> None:
        if self.view_month == 12:
            self.view_month = 1
            self.view_year += 1
        else:
            self.view_month += 1
        self.selected_day = None
        self._reload_calendar()

    def _go_today(self) -> None:
        today = date.today()
        self.view_year = today.year
        self.view_month = today.month
        self.selected_day = today
        self._reload_calendar()

    def _day_bg(self, plans: list[dict], *, today_iso: str) -> tuple[str, str]:
        if not plans:
            return CAL_EMPTY
        if day_has_miss(plans, today_iso=today_iso):
            return CAL_MISS
        if day_all_confirmed(plans):
            return CAL_VERIFIED
        return CAL_PLANNED

    def _cancel_click_timer(self) -> None:
        if self._click_timer is not None:
            self.after_cancel(self._click_timer)
            self._click_timer = None

    def _on_day_single(self, day: date) -> None:
        self._cancel_click_timer()
        self._click_timer = self.after(280, lambda d=day: self._select_day(d))

    def _on_day_double(self, day: date) -> None:
        self._cancel_click_timer()
        self._open_day_detail(day)

    def _bind_day_cell(self, widget, day: date) -> None:
        def single(_event, d: date = day) -> None:
            self._on_day_single(d)

        def double(_event, d: date = day) -> None:
            self._on_day_double(d)

        def apply(w: ctk.CTkBaseClass) -> None:
            w.bind("<Button-1>", single)
            w.bind("<Double-Button-1>", double)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass
            for child in w.winfo_children():
                apply(child)

        apply(widget)

    def _reload_calendar(self) -> None:
        self.month_label.configure(text=self._month_title())
        today_iso = iso_today()
        self.state.db.sync_planning_miss_flags(today_iso)
        entries = self.state.db.list_planning_entries_for_month(self.view_year, self.view_month)
        needs_date = self.state.db.list_planning_needs_delivery_date()
        self._plans_by_day = {}
        for entry in entries:
            iso = str(entry.get("plan_date_iso", ""))
            if not iso:
                continue
            self._plans_by_day.setdefault(iso, []).append(entry)

        confirmed = sum(1 for e in entries if effective_check_status(e, today_iso=today_iso) == "confirmed")
        miss_n = sum(1 for e in entries if effective_check_status(e, today_iso=today_iso) == "miss")
        open_n = len(entries) - confirmed - miss_n
        needs_n = len(needs_date)
        summary = f"{len(entries)} plan(s) · {confirmed} confirmed · {miss_n} miss · {open_n} open"
        if needs_n:
            summary += f" · {needs_n} chưa có hạn giao"
        self.summary_label.configure(text=summary)
        if needs_n:
            self.summary_label.configure(text_color=COLORS["accent"][1])
        else:
            self.summary_label.configure(text_color=COLORS["muted"])

        for child in self.calendar_grid.winfo_children():
            child.destroy()
        self._day_cells.clear()

        weeks = calendar.monthcalendar(self.view_year, self.view_month)

        for r, week in enumerate(weeks):
            for c, day_num in enumerate(week):
                if day_num == 0:
                    pad = ctk.CTkFrame(self.calendar_grid, fg_color="transparent", height=CELL_MIN_H)
                    pad.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
                    continue

                day = date(self.view_year, self.view_month, day_num)
                iso = day.strftime("%Y-%m-%d")
                plans = self._plans_by_day.get(iso, [])
                is_today = iso == today_iso
                is_selected = self.selected_day == day
                bg = self._day_bg(plans, today_iso=today_iso)

                border_w = 2 if is_selected or is_today else 0
                border_color = CAL_SELECTED_BORDER if is_selected else (CAL_TODAY if is_today else bg[1])

                cell = ctk.CTkFrame(
                    self.calendar_grid,
                    fg_color=bg,
                    corner_radius=10,
                    border_width=border_w,
                    border_color=border_color,
                )
                cell.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
                cell.grid_propagate(False)

                inner = ctk.CTkFrame(cell, fg_color="transparent")
                inner.place(relx=0.5, rely=0.5, anchor="center")

                num_color = ("#1a1a1a", "#f3f4f6") if plans else COLORS["muted"]
                if is_today:
                    num_color = ("#0d47a1", CAL_TODAY)
                ctk.CTkLabel(
                    inner,
                    text=str(day_num),
                    font=("Segoe UI", 15, "bold"),
                    text_color=num_color,
                ).pack()
                self._day_cells[day] = cell
                self._bind_day_cell(cell, day)

    def _update_day_selection(self, old_day: date | None, new_day: date | None) -> None:
        today_iso = iso_today()
        for d in {old_day, new_day}:
            if d is None:
                continue
            cell = self._day_cells.get(d)
            if cell is None:
                continue
            try:
                if not cell.winfo_exists():
                    continue
            except Exception:
                continue
            iso = d.strftime("%Y-%m-%d")
            plans = self._plans_by_day.get(iso, [])
            is_today = iso == today_iso
            is_selected = self.selected_day == d
            bg = self._day_bg(plans, today_iso=today_iso)
            border_w = 2 if is_selected or is_today else 0
            border_color = CAL_SELECTED_BORDER if is_selected else (CAL_TODAY if is_today else bg[1])
            cell.configure(border_width=border_w, border_color=border_color)

    def _select_day(self, day: date) -> None:
        old = self.selected_day
        self.selected_day = day
        self._update_day_selection(old, day)

    def _open_day_detail(self, day: date) -> None:
        self.selected_day = day
        DayDetailDialog(
            self,
            db=self.state.db,
            day=day,
            on_confirm=self._confirm_delivery,
            on_prepare=self._prepare_entry,
            on_remove=self._remove_entry,
            on_refresh=self._reload_calendar,
            on_add_plan=lambda d=day: self._open_add_plan_for_day(d),
            can_write=self._can_write,
            actor=self.state.user.display_name or self.state.user.username,
            lookup_from_ol=self._lookup_from_ol,
        )
        self._reload_calendar()

    def _lookup_from_ol(self, dg_case: str) -> dict[str, str]:
        if self.state.ol_service is None:
            return {}
        ol_df = self.state.get_active_ol_df()
        if ol_df is None or ol_df.empty:
            return {}
        return self.state.ol_service.summarize_for_planning(ol_df, dg_case)

    def _open_add_plan_for_day(self, day: date) -> None:
        AddPlanDialog(
            self,
            db=self.state.db,
            on_save=self._save_plan,
            on_import_batch=self._save_plans_batch,
            initial_plan_date=format_date_dd_mm_yyyy(day),
            lookup_from_ol=self._lookup_from_ol,
        )

    def _initial_plan_date(self) -> str:
        if self.selected_day:
            return format_date_dd_mm_yyyy(self.selected_day)
        return ""

    def _open_add_plan(self) -> None:
        AddPlanDialog(
            self,
            db=self.state.db,
            on_save=self._save_plan,
            on_import_batch=self._save_plans_batch,
            initial_plan_date=self._initial_plan_date(),
            lookup_from_ol=self._lookup_from_ol,
        )

    def _require_write(self) -> bool:
        if self._can_write:
            return True
        messagebox.showwarning(
            "Planning",
            "Role của bạn chỉ được xem/lọc. Cần role Design hoặc Admin để ghi.",
        )
        return False

    def _save_plan(self, payload: dict) -> None:
        if not self._require_write():
            return
        self._insert_plan(payload)
        messagebox.showinfo("Planning", "Plan saved successfully.")

    def _save_plans_batch(self, plans: list[dict]) -> None:
        if not self._require_write():
            return
        added = 0
        skipped = 0
        for payload in plans:
            if self._insert_plan(payload, refresh=False, parent=self):
                added += 1
            else:
                skipped += 1
        self._reload_calendar()
        if skipped:
            messagebox.showinfo(
                "Import Excel",
                f"Đã thêm {added} plan. Bỏ qua {skipped} plan trùng DG Case.",
                parent=self,
            )

    def _insert_plan(self, payload: dict, *, refresh: bool = True, parent=None) -> bool:
        if parent is not None:
            if not confirm_duplicate_plan(parent, self.state.db, payload["dg_case"]):
                return False
        from core.ol_reader import OlReaderService
        from core.utils import extract_customer_code_from_product_code

        actor = self.state.user.display_name or self.state.user.username
        customer_code = ""
        ol_df = self.state.get_active_ol_df()
        item_code = str(payload["item_code"])
        if ol_df is not None and not ol_df.empty:
            ol = OlReaderService(self.state.db).lookup_fields_for_dg_case(
                ol_df, str(payload["dg_case"])
            )
            customer_code = extract_customer_code_from_product_code(
                ol.get("item_code") or item_code
            )
        if not customer_code:
            customer_code = extract_customer_code_from_product_code(item_code)
        self.state.db.add_planning_entry(
            dg_case=str(payload["dg_case"]),
            item_code=item_code,
            supplier=str(payload.get("supplier", "")),
            customer_code=customer_code,
            quantity=float(payload["quantity"]),
            plan_date=str(payload["plan_date"]),
            plan_date_iso=str(payload["plan_date_iso"]),
            verify_date=str(payload["verify_date"]),
            verify_date_iso=str(payload["verify_date_iso"]),
            session=str(payload["session"]),
            created_by=self.state.user.numeric_id(),
            actor=actor,
        )
        iso = str(payload["plan_date_iso"])
        if iso:
            parts = iso.split("-")
            if len(parts) == 3:
                self.view_year = int(parts[0])
                self.view_month = int(parts[1])
                self.selected_day = date(int(parts[0]), int(parts[1]), int(parts[2]))
        if refresh:
            self._reload_calendar()
        return True

    def _open_check_plan(self) -> None:
        entries = self.state.db.list_planning_entries_for_month(self.view_year, self.view_month)
        needs_date = self.state.db.list_planning_needs_delivery_date()
        CheckPlanDialog(
            self,
            entries=entries,
            needs_date=needs_date,
            on_verify=self._verify_entry,
            on_edit_plan=self._edit_unscheduled_plan,
            can_write=self._can_write,
        )

    def _open_reminders(self) -> None:
        needs_date = self.state.db.list_planning_needs_delivery_date()
        reminders = self.state.db.list_planning_reminders(
            from_iso=iso_today(),
            to_iso=iso_in_days(7),
        )
        RemindersDialog(
            self,
            needs_date=needs_date,
            reminders=reminders,
            on_verify=self._verify_entry,
            on_edit_plan=self._edit_unscheduled_plan,
            can_write=self._can_write,
        )

    def _edit_unscheduled_plan(self, entry_id: int, on_done=None) -> None:
        if not self._require_write():
            return
        plan = self.state.db.get_planning_entry(entry_id)
        if not plan:
            return
        EditPlanDialog(
            self,
            db=self.state.db,
            plan=plan,
            actor=self.state.user.display_name or self.state.user.username,
            lookup_from_ol=self._lookup_from_ol,
            on_saved=lambda: self._edit_unscheduled_plan_saved(on_done),
        )

    def _edit_unscheduled_plan_saved(self, on_done=None) -> None:
        self._reload_calendar()
        if on_done:
            on_done()

    def _open_planning_log(self) -> None:
        entries = self.state.db.list_planning_audit_log(
            year=self.view_year,
            month=self.view_month,
            limit=300,
        )
        PlanningLogDialog(
            self,
            entries=entries,
            month_title=self._month_title(),
        )

    def _confirm_delivery(self, entry_id: int) -> bool:
        if not self._require_write():
            return False
        actor = self.state.user.display_name or self.state.user.username
        ok, msg = supplier_db.mark_plan_saved(
            self.state.db,
            entry_id,
            actor=actor,
            actor_user_id=self.state.user.numeric_id(),
        )
        if ok:
            messagebox.showinfo("Planning", msg, parent=self)
            self._reload_calendar()
            self.state.notify()
            return True
        messagebox.showwarning("Planning", msg, parent=self)
        return False

    def _prepare_entry(self, entry_id: int, on_done=None) -> None:
        plan = self.state.db.get_planning_entry(entry_id)
        if not plan:
            messagebox.showwarning("Planning", "Plan not found.", parent=self)
            return
        PrepareLabelsDialog(
            self,
            state=self.state,
            entry_id=entry_id,
            plan=plan,
            on_saved=lambda: self._after_prepare_saved(on_done),
        )

    def _after_prepare_saved(self, on_done=None) -> None:
        self._reload_calendar()
        if on_done is not None:
            on_done()

    def _remove_entry(self, entry_id: int) -> None:
        if not self._require_write():
            return
        actor = self.state.user.display_name or self.state.user.username
        if self.state.db.soft_delete_planning_entry(
            entry_id,
            deleted_by=actor,
            actor_user_id=self.state.user.numeric_id(),
        ):
            messagebox.showinfo("Planning", "Plan removed from calendar.")
        else:
            messagebox.showwarning("Planning", "Could not remove plan.")

    def _verify_entry(self, entry_id: int) -> bool:
        return self._confirm_delivery(entry_id)
        self._reload_calendar()


class CheckPlanDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        entries: list[dict],
        needs_date: list[dict] | None = None,
        on_verify,
        on_edit_plan=None,
        can_write: bool = True,
    ):
        super().__init__(master)
        self.on_verify = on_verify
        self.on_edit_plan = on_edit_plan
        self.can_write = can_write
        self.needs_date = needs_date or []
        self.entries = entries
        self._pager = TablePager()
        self.title("Check Plan")
        configure_dialog(self, width=820, height=580, min_width=720, min_height=480, resizable=True, parent=master)
        self.transient(master.winfo_toplevel())

        _, header, content, footer = create_dialog_layout(self)
        ctk.CTkLabel(header, text="Check Plan — This Month", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=(
                "Review every plan scheduled in the current calendar month. "
                "Đánh dấu «Đã lưu» = check phiếu Supplier (cùng một ý nghĩa)."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(4, 4))
        pending = [e for e in entries if effective_check_status(e) != "confirmed"]
        overdue_count = len(
            [
                e
                for e in pending
                if effective_check_status(e) == "miss"
            ]
        )
        ctk.CTkLabel(
            header,
            text=(
                f"{len(entries)} trong tháng · {len(pending)} pending · {overdue_count} overdue · "
                f"{len(self.needs_date)} chưa có hạn giao"
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(4, 8))

        content.grid_rowconfigure(2, weight=1)
        if self.needs_date:
            needs_box = ctk.CTkFrame(content, fg_color=COLORS["card"], corner_radius=10)
            needs_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            ctk.CTkLabel(
                needs_box,
                text="Chưa có hạn giao tem — cần cập nhật trước khi check phiếu",
                font=("Segoe UI", 12, "bold"),
                text_color=COLORS["accent"][1],
            ).pack(anchor="w", padx=12, pady=(10, 6))
            for entry in self.needs_date:
                self._needs_date_row(needs_box, entry)

        self._pager_bar = TablePagerBar(
            content,
            self._pager,
            on_change=self._render_check_page,
            placeholder="Lọc plan tháng này…",
        )
        self._pager_bar.set_filter_handler(self._check_plan_filter)
        self._pager_bar.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.scroll = ctk.CTkScrollableFrame(content, fg_color=COLORS["card"], corner_radius=10)
        self.scroll.grid(row=2, column=0, sticky="nsew")

        self._pager.set_items(entries, filter_fn=self._check_plan_filter, reset_page=True)
        self._render_check_page()

        ctk.CTkButton(footer, text="Close", width=90, height=36, fg_color="transparent", command=self.destroy).pack(
            side="right"
        )
        show_dialog(self, master)

    def _needs_date_row(self, parent, entry: dict) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)
        text = (
            f"{entry.get('dg_case')} · {entry.get('item_code')} · {entry.get('supplier', '')} · "
            f"Qty {entry.get('quantity')} · Lập KH {entry.get('verify_date')}"
        )
        ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=COLORS["accent"][1], anchor="w").pack(
            side="left", fill="x", expand=True
        )
        if self.on_edit_plan is not None and self.can_write:
            ctk.CTkButton(
                row,
                text="Nhập hạn giao",
                width=110,
                height=28,
                command=lambda eid=int(entry["id"]): self._edit_plan(eid),
            ).pack(side="right")

    def _edit_plan(self, entry_id: int) -> None:
        if self.on_edit_plan is None:
            return

        def refresh() -> None:
            self.destroy()

        self.on_edit_plan(entry_id, refresh)

    @staticmethod
    def _check_plan_filter(entry: dict, query: str) -> bool:
        blob = " ".join(
            [
                normalize_text(entry.get("plan_date")),
                normalize_text(entry.get("dg_case")),
                normalize_text(entry.get("item_code")),
                normalize_text(entry.get("supplier")),
                str(entry.get("quantity") or ""),
            ]
        ).lower()
        return query in blob

    def _render_check_page(self) -> None:
        for w in self.scroll.winfo_children():
            w.destroy()
        page_items = self._pager.page_items()
        self._pager_bar.refresh_info()
        if not page_items and not self.entries:
            ctk.CTkLabel(self.scroll, text="No plans for this month.", font=FONT_BODY).pack(pady=20)
            return
        if not page_items:
            ctk.CTkLabel(self.scroll, text="Không khớp bộ lọc.", font=FONT_BODY).pack(pady=20)
            return
        for entry in page_items:
            self._row(self.scroll, entry)

    def _row(self, parent, entry: dict) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=6)
        status = effective_check_status(entry)
        overdue = status == "miss"
        color = COLORS["warning"][1] if overdue else COLORS["muted"]
        prepare = prepare_status_label(effective_prepare_status(entry))
        text = (
            f"Giao {format_plan_date_display(entry)} · {entry.get('dg_case')} · {entry.get('item_code')} · "
            f"{entry.get('supplier', '')} · Qty {entry.get('quantity')} · Lập KH {entry.get('verify_date')} · "
            f"Check {check_status_label(status)} · Prepare {prepare}"
        )
        ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=color, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        if status != "confirmed":
            btn_state = "normal" if status != "no_date" else "disabled"
            ctk.CTkButton(
                row,
                text="Check phiếu",
                width=88,
                height=28,
                state=btn_state,
                command=lambda eid=int(entry["id"]): self._verify(eid),
            ).pack(side="right")

    def _verify(self, entry_id: int) -> None:
        if self.on_verify(entry_id):
            self.destroy()


class PlanningLogDialog(ctk.CTkToplevel):
    def __init__(self, master, *, entries: list[dict], month_title: str):
        super().__init__(master)
        self.entries = entries
        self._pager = TablePager()
        self.title("Planning Log")
        configure_dialog(self, width=1000, height=600, min_width=820, min_height=480, resizable=True, parent=master)
        self.transient(master.winfo_toplevel())

        _, header, content, footer = create_dialog_layout(self)
        ctk.CTkLabel(header, text="Planning Log", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=(
                f"Activity for {month_title} — create, remove, confirm, prepare. "
                "Removed plans stay in the database but no longer appear on the calendar."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        col_header = ctk.CTkFrame(header, fg_color=("gray88", "gray28"), corner_radius=8)
        col_header.pack(fill="x", pady=(0, 4))
        for col, width in [
            ("Time", 140),
            ("Action", 120),
            ("DG Case", 96),
            ("Production No", 110),
            ("Supplier", 96),
            ("Hạn giao tem", 88),
            ("Ngày lập KH", 88),
            ("By", 88),
        ]:
            ctk.CTkLabel(
                col_header,
                text=col,
                width=width,
                anchor="center",
                font=("Segoe UI", 11, "bold"),
            ).pack(side="left", padx=4, pady=8)

        content.grid_rowconfigure(1, weight=1)
        self._pager_bar = TablePagerBar(
            content,
            self._pager,
            on_change=self._render_log_page,
            placeholder="Lọc log tháng…",
        )
        self._pager_bar.set_filter_handler(self._log_filter)
        self._pager_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.scroll = ctk.CTkScrollableFrame(content, fg_color=COLORS["card"], corner_radius=10)
        self.scroll.grid(row=1, column=0, sticky="nsew")

        self._pager.set_items(entries, filter_fn=self._log_filter, reset_page=True)
        self._render_log_page()

        ctk.CTkButton(footer, text="Close", width=90, height=36, command=self.destroy).pack(side="right")
        show_dialog(self, master)

    @staticmethod
    def _log_filter(entry: dict, query: str) -> bool:
        blob = " ".join(
            [
                normalize_text(entry.get("action")),
                normalize_text(entry.get("dg_case")),
                normalize_text(entry.get("item_code")),
                normalize_text(entry.get("supplier")),
                normalize_text(entry.get("actor")),
                normalize_text(entry.get("plan_date")),
            ]
        ).lower()
        return query in blob

    def _render_log_page(self) -> None:
        for w in self.scroll.winfo_children():
            w.destroy()
        page_items = self._pager.page_items()
        self._pager_bar.refresh_info()
        if not page_items and not self.entries:
            ctk.CTkLabel(
                self.scroll,
                text="No activity recorded for this month.",
                font=FONT_BODY,
                text_color=COLORS["muted"],
            ).pack(pady=24)
            return
        if not page_items:
            ctk.CTkLabel(self.scroll, text="Không khớp bộ lọc.", font=FONT_BODY).pack(pady=24)
            return
        for idx, entry in enumerate(page_items):
            self._row(self.scroll, entry, idx)

    def _row(self, parent, entry: dict, row_idx: int) -> None:
        action = str(entry.get("action", ""))
        is_delete = action == "deleted"
        bg = ("#ffebee", "#3d2020") if is_delete else (
            ("gray95", "gray26") if row_idx % 2 == 0 else ("gray90", "gray22")
        )
        row = ctk.CTkFrame(parent, fg_color=bg, corner_radius=6)
        row.pack(fill="x", padx=8, pady=2)

        when = format_check_timestamp(entry.get("created_at")) or "—"
        action_label = audit_action_label(action)
        dg = normalize_text(entry.get("dg_case")) or "—"
        item = normalize_text(entry.get("item_code")) or "—"
        supplier = normalize_text(entry.get("supplier")) or "—"
        plan_date = normalize_text(entry.get("plan_date")) or "—"
        verify_date = normalize_text(entry.get("verify_date")) or "—"
        actor = normalize_text(entry.get("actor")) or "—"
        if is_delete:
            deleted_at = format_check_timestamp(entry.get("deleted_at"))
            if deleted_at:
                when = deleted_at

        values = [when, action_label, dg, item, supplier, plan_date, verify_date, actor]
        widths = [140, 120, 96, 110, 96, 88, 88, 88]
        for text, width in zip(values, widths):
            color = "#c62828" if is_delete else None
            kwargs: dict = {
                "text": text,
                "width": width,
                "anchor": "center",
                "font": FONT_SMALL,
            }
            if color:
                kwargs["text_color"] = color
            ctk.CTkLabel(row, **kwargs).pack(side="left", padx=4, pady=6)
        detail = entry.get("detail") if isinstance(entry.get("detail"), dict) else {}
        change = format_plan_change_line(detail)
        if change:
            ctk.CTkLabel(
                parent,
                text=f"    {change}",
                font=FONT_SMALL,
                text_color=COLORS["muted"],
                anchor="w",
            ).pack(fill="x", padx=16, pady=(0, 4))


class RemindersDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        needs_date: list[dict],
        reminders: list[dict],
        on_verify,
        on_edit_plan=None,
        can_write: bool = True,
    ):
        super().__init__(master)
        self.on_verify = on_verify
        self.on_edit_plan = on_edit_plan
        self.can_write = can_write
        self.needs_date = needs_date
        self.reminders = reminders
        self.title("Reminders")
        configure_dialog(self, width=820, height=620, min_width=720, min_height=480, resizable=True, parent=master)
        self.transient(master.winfo_toplevel())

        _, header, content, footer = create_dialog_layout(self)
        ctk.CTkLabel(header, text="Nhắc việc Planning", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=(
                "Plan chưa có hạn giao sẽ luôn hiện ở đây cho đến khi nhập ngày giao và check phiếu. "
                "Phần dưới là hạn giao trong 7 ngày tới."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        content.grid_rowconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(content, fg_color=COLORS["card"], corner_radius=10)
        scroll.grid(row=0, column=0, sticky="nsew")

        if self.needs_date:
            ctk.CTkLabel(
                scroll,
                text=f"Chưa có hạn giao tem ({len(self.needs_date)})",
                font=("Segoe UI", 13, "bold"),
                text_color=COLORS["accent"][1],
            ).pack(anchor="w", padx=12, pady=(12, 6))
            for entry in self.needs_date:
                self._needs_date_row(scroll, entry)
        else:
            ctk.CTkLabel(
                scroll,
                text="Không có plan thiếu hạn giao tem.",
                font=FONT_BODY,
                text_color=COLORS["success"][1],
            ).pack(anchor="w", padx=12, pady=(12, 8))

        ctk.CTkLabel(
            scroll,
            text=f"Hạn giao trong 7 ngày tới ({len(self.reminders)})",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=12, pady=(16, 6))

        if not self.reminders:
            ctk.CTkLabel(
                scroll,
                text="Không có plan sắp đến hạn giao tem.",
                font=FONT_BODY,
                text_color=COLORS["muted"],
            ).pack(anchor="w", padx=12, pady=(0, 12))
        else:
            for entry in self.reminders:
                self._reminder_row(scroll, entry)

        ctk.CTkButton(footer, text="Close", width=90, height=36, fg_color="transparent", command=self.destroy).pack(
            side="right"
        )
        show_dialog(self, master)

    def _needs_date_row(self, parent, entry: dict) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=6)
        text = (
            f"{entry.get('dg_case')} · {entry.get('item_code')} · {entry.get('supplier', '')} · "
            f"Lập KH {entry.get('verify_date')} · Qty {entry.get('quantity')}"
        )
        ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=COLORS["accent"][1], anchor="w").pack(
            side="left", fill="x", expand=True
        )
        if self.on_edit_plan is not None and self.can_write:
            ctk.CTkButton(
                row,
                text="Nhập hạn giao",
                width=110,
                height=28,
                command=lambda eid=int(entry["id"]): self._edit_plan(eid),
            ).pack(side="right")

    def _reminder_row(self, parent, entry: dict) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=6)
        due = format_plan_date_display(entry)
        text = (
            f"Giao tem {due} · {entry.get('dg_case')} · {entry.get('item_code')} · "
            f"{entry.get('supplier', '')} · Lập KH {entry.get('verify_date')} · Qty {entry.get('quantity')}"
        )
        ctk.CTkLabel(row, text=text, font=FONT_SMALL, anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            row,
            text="Check phiếu",
            width=88,
            height=28,
            command=lambda eid=int(entry["id"]): self._verify(eid),
        ).pack(side="right")

    def _edit_plan(self, entry_id: int) -> None:
        if self.on_edit_plan is None:
            return

        def refresh() -> None:
            self.destroy()

        self.on_edit_plan(entry_id, refresh)

    def _verify(self, entry_id: int) -> None:
        if self.on_verify(entry_id):
            self.destroy()
