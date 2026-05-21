"""Planning tab — monthly calendar with plan management."""

from __future__ import annotations

import calendar
from datetime import date
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.app_state import AppState
from core.planning_service import (
    DEFAULT_EXCEL_MAP,
    PlanningValidationError,
    audit_action_label,
    check_status_label,
    day_all_confirmed,
    day_has_miss,
    effective_check_status,
    effective_prepare_status,
    format_check_display,
    format_check_timestamp,
    format_prepare_display,
    import_plans_from_excel,
    iso_in_days,
    iso_today,
    load_excel_mapping,
    prepare_status_label,
    save_excel_mapping,
    validate_plan_payload,
)
from core.utils import format_date_dd_mm_yyyy, normalize_text, parse_date_dd_mm_yyyy
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
DATE_FIELD_KEYS = frozenset({"plan_date", "verify_date"})
OL_AUTOFILL_TO_FORM = {
    "production_no": "item_code",
    "supplier": "supplier",
    "quantity": "quantity",
}


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
        self.geometry("340x340")
        self.resizable(False, False)
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
        self.geometry("620x620")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(body, text="Add Production Plan", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text="Enter manually or import rows from Excel with configurable columns.",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(4, 12))

        tabs = ctk.CTkTabview(body, height=460)
        tabs.pack(fill="both", expand=True)
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
            "verify_date": ctk.StringVar(),
            "session": ctk.StringVar(value="—"),
        }
        fields = [
            ("DG Case", "dg_case", "e.g. O-1249-01"),
            ("Production No", "item_code", "e.g. mã SP đầy đủ từ OL"),
            ("Supplier", "supplier", "e.g. NCC ABC — giao cho ai"),
            ("Quantity", "quantity", "e.g. 160"),
            ("Plan Date", "plan_date", "dd-mm-yyyy"),
            ("Verify Date", "verify_date", "dd-mm-yyyy"),
        ]
        for label, key, placeholder in fields:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=7)
            ctk.CTkLabel(row, text=label, width=110, anchor="w", font=FONT_BODY).pack(side="left")
            if key in DATE_FIELD_KEYS:
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
            ("Plan Date", "plan_date"),
            ("Verify Date", "verify_date"),
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
    TABLE_HEADERS = (
        ("", 36),
        ("Mã NPL", 108),
        ("Tên NPL", 220),
        ("Mô tả", 180),
        ("Quantity", 80),
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
        self.state = state
        self.entry_id = entry_id
        self.plan = plan
        self.on_saved = on_saved
        self.checkbox_vars: dict[str, ctk.BooleanVar] = {}
        self.candidates: list[dict] = []

        already = effective_prepare_status(plan) == "prepared"
        self.title("Update Prepare" if already else "Prepare Labels")
        self.geometry("820x520")
        self.minsize(760, 420)
        self.transient(master.winfo_toplevel())
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)

        dg = normalize_text(plan.get("dg_case"))
        prod = normalize_text(plan.get("item_code"))
        supplier = normalize_text(plan.get("supplier"))
        ctk.CTkLabel(body, text="Prepare — Select Labels", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text=f"DG Case {dg} · {prod} · {supplier}",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(4, 4))
        ctk.CTkLabel(
            body,
            text=(
                "Label rows from bảng kê (Số S/O) where Tên NPL contains: "
                "nhãn, label, poly, satin, picto…"
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        toolbar = ctk.CTkFrame(body, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(toolbar, text="Select all", width=90, height=30, command=self._select_all).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(toolbar, text="Clear all", width=90, height=30, command=self._clear_all).pack(
            side="left"
        )
        self.summary_label = ctk.CTkLabel(toolbar, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.summary_label.pack(side="right")

        table_wrap = ctk.CTkFrame(body, fg_color=COLORS["card"], corner_radius=10)
        table_wrap.pack(fill="both", expand=True)

        header = ctk.CTkFrame(table_wrap, fg_color=("gray88", "gray28"), corner_radius=0)
        header.pack(fill="x", padx=12, pady=(12, 0))
        for title, width in self.TABLE_HEADERS:
            ctk.CTkLabel(
                header,
                text=title,
                width=width,
                anchor="center",
                font=("Segoe UI", 11, "bold"),
            ).pack(side="left", padx=4, pady=8)

        self.rows_frame = ctk.CTkScrollableFrame(table_wrap, fg_color="transparent", height=280)
        self.rows_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        actions = ctk.CTkFrame(body, fg_color="transparent")
        actions.pack(fill="x", pady=(12, 0))
        ctk.CTkButton(actions, text="Cancel", width=90, fg_color="transparent", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        confirm_text = "Confirm Update" if already else "Confirm Prepare"
        ctk.CTkButton(
            actions,
            text=confirm_text,
            width=140,
            fg_color=COLORS["success"][1],
            command=self._confirm,
        ).pack(side="right")

        self._load_rows()
        self.after(80, lambda: (self.lift(), self.focus_force()))

    def _load_rows(self) -> None:
        from core.prepare_service import item_key, list_label_candidates

        for w in self.rows_frame.winfo_children():
            w.destroy()
        self.checkbox_vars.clear()

        bom_df = self.state.get_active_bom_ke_df()
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

        saved = self.state.db.list_planning_prepare_items(self.entry_id)
        saved_keys = {item_key(str(r.get("ma_npl")), int(r.get("row_index", 0))) for r in saved}
        default_checked = bool(saved_keys)

        for idx, row in enumerate(self.candidates):
            key = str(row["item_key"])
            var = ctk.BooleanVar(value=key in saved_keys if default_checked else False)
            self.checkbox_vars[key] = var

            bg = ("gray95", "gray26") if idx % 2 == 0 else ("gray90", "gray22")
            line = ctk.CTkFrame(self.rows_frame, fg_color=bg, corner_radius=6)
            line.pack(fill="x", pady=2)

            ctk.CTkCheckBox(line, text="", variable=var, width=36).pack(side="left", padx=(8, 4), pady=8)
            from core.prepare_service import format_prepare_quantity

            for text, width in [
                (row.get("ma_npl", ""), 108),
                (row.get("ten_npl", ""), 220),
                (row.get("mo_ta", ""), 180),
                (format_prepare_quantity(row.get("quantity")), 80),
            ]:
                ctk.CTkLabel(
                    line,
                    text=str(text),
                    width=width,
                    anchor="w" if width > 100 else "center",
                    font=FONT_SMALL,
                    wraplength=width - 8 if width >= 180 else 0,
                    justify="left",
                ).pack(side="left", padx=4, pady=8)

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
            if self.checkbox_vars.get(str(row["item_key"]), ctk.BooleanVar(value=False)).get():
                selected.append(row)
        return selected

    def _confirm(self) -> None:
        if not self.candidates:
            messagebox.showwarning("Prepare", "Không có dòng nhãn để chọn.", parent=self)
            return
        selected = self._selected_items()
        if not selected:
            messagebox.showwarning("Prepare", "Chọn ít nhất một dòng nhãn.", parent=self)
            return
        actor = self.state.user.display_name or self.state.user.username
        self.state.db.save_planning_prepare_items(
            self.entry_id,
            selected,
            prepare_by=actor,
            actor_user_id=self.state.user.id,
        )
        messagebox.showinfo(
            "Prepare",
            f"Đã lưu {len(selected)} dòng nhãn cho bước Làm Phiếu.",
            parent=self,
        )
        self.on_saved()
        self.destroy()


class DayDetailDialog(ctk.CTkToplevel):
    TABLE_HEADERS = (
        ("DG Case", 100),
        ("Production No", 118),
        ("Supplier", 96),
        ("Qty", 48),
        ("Plan Date", 88),
        ("Verify Date", 88),
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
    ):
        super().__init__(master)
        self.db = db
        self.day = day
        self.on_confirm = on_confirm
        self.on_prepare = on_prepare
        self.on_remove = on_remove
        self.on_refresh = on_refresh
        self.on_add_plan = on_add_plan
        self.selected_id: int | None = None
        self.title("Day Plan Details")
        self.geometry("1180x540")
        self.minsize(1100, 460)
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self._close)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=20)

        ctk.CTkLabel(
            body,
            text=day.strftime("%A, %d-%m-%Y"),
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="center")
        self.subtitle = ctk.CTkLabel(body, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.subtitle.pack(anchor="center", pady=(4, 12))

        action_bar = ctk.CTkFrame(body, fg_color="transparent")
        action_bar.pack(anchor="center", pady=(0, 10))
        ctk.CTkButton(
            action_bar,
            text="Confirm Delivery",
            width=140,
            height=34,
            fg_color=COLORS["success"][1],
            command=self._confirm_selected,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            action_bar,
            text="Prepare",
            width=100,
            height=34,
            command=self._prepare_selected,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            action_bar,
            text="Remove Plan",
            width=110,
            height=34,
            fg_color="#c62828",
            hover_color="#b71c1c",
            command=self._remove_selected,
        ).pack(side="left", padx=6)
        ctk.CTkLabel(
            action_bar,
            text="Select a row, then click an action",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(side="left", padx=(12, 0))

        table_outer = ctk.CTkFrame(body, fg_color="transparent")
        table_outer.pack(fill="both", expand=True)
        table_wrap = ctk.CTkFrame(table_outer, fg_color=COLORS["card"], corner_radius=10)
        table_wrap.pack(anchor="center", fill="both", expand=True)

        header = ctk.CTkFrame(table_wrap, fg_color=("gray88", "gray28"), corner_radius=0)
        header.pack(fill="x", padx=12, pady=(12, 0))
        for i, (title, width) in enumerate(self.TABLE_HEADERS):
            header.grid_columnconfigure(i, weight=1, uniform="col")
            ctk.CTkLabel(
                header,
                text=title,
                width=width,
                anchor="center",
                font=("Segoe UI", 11, "bold"),
            ).grid(row=0, column=i, sticky="nsew", padx=4, pady=8)

        self.rows_frame = ctk.CTkScrollableFrame(table_wrap, fg_color="transparent", height=300)
        self.rows_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        ctk.CTkButton(body, text="Close", width=90, fg_color="transparent", command=self._close).pack(
            anchor="center", pady=(10, 0)
        )
        self._reload_rows()
        self.after(80, lambda: (self.lift(), self.focus_force()))

    def _close(self) -> None:
        self.destroy()

    def _reload_rows(self) -> None:
        iso = self.day.strftime("%Y-%m-%d")
        plans = self.db.list_planning_entries_for_day(iso)
        miss_n = sum(1 for p in plans if effective_check_status(p) == "miss")
        confirmed_n = sum(1 for p in plans if effective_check_status(p) == "confirmed")
        self.subtitle.configure(
            text=f"{len(plans)} item(s) · {confirmed_n} confirmed · {miss_n} miss"
        )

        for w in self.rows_frame.winfo_children():
            w.destroy()

        if not plans:
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

        for idx, plan in enumerate(plans):
            self._render_row(plan, idx)

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
            normalize_text(plan.get("plan_date")),
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
            messagebox.showinfo("Day Plans", "Delivery already confirmed for this row.", parent=self)
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
        today = date.today()
        self.view_year = today.year
        self.view_month = today.month
        self.selected_day: date | None = None
        self._plans_by_day: dict[str, list[dict]] = {}
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
        ctk.CTkButton(
            tb,
            text="+ Add Plan",
            width=120,
            height=34,
            fg_color=COLORS["accent"][1],
            command=self._open_add_plan,
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
        self._plans_by_day = {}
        for entry in entries:
            iso = str(entry.get("plan_date_iso", ""))
            self._plans_by_day.setdefault(iso, []).append(entry)

        confirmed = sum(1 for e in entries if effective_check_status(e, today_iso=today_iso) == "confirmed")
        miss_n = sum(1 for e in entries if effective_check_status(e, today_iso=today_iso) == "miss")
        open_n = len(entries) - confirmed - miss_n
        self.summary_label.configure(
            text=f"{len(entries)} plan(s) · {confirmed} confirmed · {miss_n} miss · {open_n} open"
        )

        for child in self.calendar_grid.winfo_children():
            child.destroy()

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
                self._bind_day_cell(cell, day)

    def _select_day(self, day: date) -> None:
        self.selected_day = day
        self._reload_calendar()

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
        return format_date_dd_mm_yyyy(date.today())

    def _open_add_plan(self) -> None:
        AddPlanDialog(
            self,
            db=self.state.db,
            on_save=self._save_plan,
            on_import_batch=self._save_plans_batch,
            initial_plan_date=self._initial_plan_date(),
            lookup_from_ol=self._lookup_from_ol,
        )

    def _save_plan(self, payload: dict) -> None:
        self._insert_plan(payload)
        messagebox.showinfo("Planning", "Plan saved successfully.")

    def _save_plans_batch(self, plans: list[dict]) -> None:
        for payload in plans:
            self._insert_plan(payload, refresh=False)
        self._reload_calendar()

    def _insert_plan(self, payload: dict, *, refresh: bool = True) -> None:
        actor = self.state.user.display_name or self.state.user.username
        self.state.db.add_planning_entry(
            dg_case=str(payload["dg_case"]),
            item_code=str(payload["item_code"]),
            supplier=str(payload.get("supplier", "")),
            quantity=float(payload["quantity"]),
            plan_date=str(payload["plan_date"]),
            plan_date_iso=str(payload["plan_date_iso"]),
            verify_date=str(payload["verify_date"]),
            verify_date_iso=str(payload["verify_date_iso"]),
            session=str(payload["session"]),
            created_by=self.state.user.id,
            actor=actor,
        )
        iso = str(payload["plan_date_iso"])
        parts = iso.split("-")
        if len(parts) == 3:
            self.view_year = int(parts[0])
            self.view_month = int(parts[1])
            self.selected_day = date(int(parts[0]), int(parts[1]), int(parts[2]))
        if refresh:
            self._reload_calendar()

    def _open_check_plan(self) -> None:
        entries = self.state.db.list_planning_entries_for_month(self.view_year, self.view_month)
        CheckPlanDialog(self, entries=entries, on_verify=self._verify_entry)

    def _open_reminders(self) -> None:
        reminders = self.state.db.list_planning_reminders(
            from_iso=iso_today(),
            to_iso=iso_in_days(7),
        )
        RemindersDialog(self, reminders=reminders, on_verify=self._verify_entry)

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

    def _confirm_delivery(self, entry_id: int) -> None:
        actor = self.state.user.display_name or self.state.user.username
        self.state.db.update_planning_check_status(
            entry_id, "confirmed", check_by=actor, actor_user_id=self.state.user.id
        )

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
        actor = self.state.user.display_name or self.state.user.username
        if self.state.db.soft_delete_planning_entry(
            entry_id, deleted_by=actor, actor_user_id=self.state.user.id
        ):
            messagebox.showinfo("Planning", "Plan removed from calendar.")
        else:
            messagebox.showwarning("Planning", "Could not remove plan.")

    def _verify_entry(self, entry_id: int) -> None:
        self._confirm_delivery(entry_id)
        self._reload_calendar()


class CheckPlanDialog(ctk.CTkToplevel):
    def __init__(self, master, *, entries: list[dict], on_verify):
        super().__init__(master)
        self.on_verify = on_verify
        self.entries = entries
        self.title("Check Plan")
        self.geometry("760x520")
        self.transient(master.winfo_toplevel())

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)
        ctk.CTkLabel(body, text="Check Plan — This Month", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text=(
                "Review every plan scheduled in the current calendar month. "
                "Use this to confirm delivery checks or spot misses (red / overdue items)."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=700,
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
            body,
            text=f"{len(entries)} total · {len(pending)} pending · {overdue_count} overdue",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(4, 12))

        scroll = ctk.CTkScrollableFrame(body, fg_color=COLORS["card"], corner_radius=10)
        scroll.pack(fill="both", expand=True)

        if not entries:
            ctk.CTkLabel(scroll, text="No plans for this month.", font=FONT_BODY).pack(pady=20)
            return

        for entry in entries:
            self._row(scroll, entry)

    def _row(self, parent, entry: dict) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=6)
        status = effective_check_status(entry)
        overdue = status == "miss"
        color = COLORS["warning"][1] if overdue else COLORS["muted"]
        prepare = prepare_status_label(effective_prepare_status(entry))
        text = (
            f"{entry.get('plan_date')} · {entry.get('dg_case')} · {entry.get('item_code')} · "
            f"{entry.get('supplier', '')} · Qty {entry.get('quantity')} · Verify {entry.get('verify_date')} · "
            f"Check {check_status_label(status)} · Prepare {prepare}"
        )
        ctk.CTkLabel(row, text=text, font=FONT_SMALL, text_color=color, anchor="w").pack(
            side="left", fill="x", expand=True
        )
        if status != "confirmed":
            ctk.CTkButton(
                row,
                text="Confirm",
                width=70,
                height=28,
                command=lambda eid=int(entry["id"]): self._verify(eid),
            ).pack(side="right")

    def _verify(self, entry_id: int) -> None:
        self.on_verify(entry_id)
        messagebox.showinfo("Check Plan", "Delivery confirmed.", parent=self)
        self.destroy()


class PlanningLogDialog(ctk.CTkToplevel):
    def __init__(self, master, *, entries: list[dict], month_title: str):
        super().__init__(master)
        self.title("Planning Log")
        self.geometry("980x520")
        self.minsize(780, 420)
        self.transient(master.winfo_toplevel())

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)
        ctk.CTkLabel(body, text="Planning Log", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text=(
                f"Activity for {month_title} — create, remove, confirm, prepare. "
                "Removed plans stay in the database but no longer appear on the calendar."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=860,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        header = ctk.CTkFrame(body, fg_color=("gray88", "gray28"), corner_radius=8)
        header.pack(fill="x", pady=(0, 8))
        for col, width in [
            ("Time", 140),
            ("Action", 120),
            ("DG Case", 96),
            ("Production No", 110),
            ("Supplier", 96),
            ("Plan Date", 88),
            ("By", 88),
        ]:
            ctk.CTkLabel(
                header,
                text=col,
                width=width,
                anchor="center",
                font=("Segoe UI", 11, "bold"),
            ).pack(side="left", padx=4, pady=8)

        scroll = ctk.CTkScrollableFrame(body, fg_color=COLORS["card"], corner_radius=10)
        scroll.pack(fill="both", expand=True)

        if not entries:
            ctk.CTkLabel(
                scroll,
                text="No activity recorded for this month.",
                font=FONT_BODY,
                text_color=COLORS["muted"],
            ).pack(pady=24)
        else:
            for idx, entry in enumerate(entries):
                self._row(scroll, entry, idx)

        ctk.CTkButton(body, text="Close", width=90, command=self.destroy).pack(anchor="e", pady=(12, 0))
        self.after(80, lambda: (self.lift(), self.focus_force()))

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
        actor = normalize_text(entry.get("actor")) or "—"
        if is_delete:
            deleted_at = format_check_timestamp(entry.get("deleted_at"))
            if deleted_at:
                when = deleted_at

        values = [when, action_label, dg, item, supplier, plan_date, actor]
        widths = [140, 120, 96, 110, 96, 88, 88]
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


class RemindersDialog(ctk.CTkToplevel):
    def __init__(self, master, *, reminders: list[dict], on_verify):
        super().__init__(master)
        self.on_verify = on_verify
        self.title("Reminders")
        self.geometry("720x460")
        self.transient(master.winfo_toplevel())

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=16)
        ctk.CTkLabel(body, text="Reminders — Next 7 Days", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text=(
                "Shows plans whose Verify Date falls within the next 7 days and are not yet confirmed. "
                "Use this as a short-term to-do list before items become Miss."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(4, 4))
        ctk.CTkLabel(
            body,
            text="Tip: Check Plan = full month audit · Reminders = near-term deadlines only.",
            font=FONT_SMALL,
            text_color=COLORS["accent"][1],
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        scroll = ctk.CTkScrollableFrame(body, fg_color=COLORS["card"], corner_radius=10)
        scroll.pack(fill="both", expand=True)

        if not reminders:
            ctk.CTkLabel(
                scroll,
                text="No upcoming verification reminders.",
                font=FONT_BODY,
                text_color=COLORS["success"][1],
            ).pack(pady=24)
            return

        for entry in reminders:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=6)
            due = str(entry.get("verify_date", ""))
            text = (
                f"Verify by {due} · {entry.get('dg_case')} · {entry.get('item_code')} · "
                f"{entry.get('supplier', '')} · Plan {entry.get('plan_date')} · Qty {entry.get('quantity')}"
            )
            ctk.CTkLabel(row, text=text, font=FONT_SMALL, anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row,
                text="Confirm",
                width=70,
                height=28,
                command=lambda eid=int(entry["id"]): self._verify(eid),
            ).pack(side="right")

    def _verify(self, entry_id: int) -> None:
        self.on_verify(entry_id)
        messagebox.showinfo("Reminders", "Delivery confirmed.", parent=self)
        self.destroy()
