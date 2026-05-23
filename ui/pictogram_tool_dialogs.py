"""Dialog công cụ Pictogram — Count / Check."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from core.app_state import AppState
from core.npl_stock_service import MODULE_PICTOGRAM, NplStockService, format_qty
from core.pictogram_calculator import FABRIC_WIDTH_CM, PICTO_LABEL_TYPES, calculate_pictogram_fabric
from core.pictogram_check import apply_pictogram_exclusions, check_pictogram_needs, pictogram_ma_key
from ui.dialog_utils import configure_dialog, create_dialog_layout, show_dialog
from ui.table_pager import TablePager, TablePagerBar
from ui.theme import COLORS, FONT_BODY, FONT_SMALL


class CountPictogramDialog(ctk.CTkToplevel):
    def __init__(self, master, state: AppState, *, seed: dict[str, float] | None = None) -> None:
        super().__init__(master)
        self.state = state
        self.title("Count Pictogram")
        configure_dialog(self, width=820, height=520, min_width=700, min_height=420, parent=master)
        self._qty_vars: dict[str, ctk.StringVar] = {}
        self._type_codes = self._load_type_codes()
        self._seed = seed if seed is not None else self._load_seed_from_check()
        self._build()
        self._recalculate()
        show_dialog(self, master)

    def _load_type_codes(self) -> list[str]:
        types = NplStockService(self.state.db).list_types(MODULE_PICTOGRAM)
        codes = [str(t.get("code", "")).upper() for t in types if normalize_str(t.get("code"))]
        return codes or list(PICTO_LABEL_TYPES)

    def _load_seed_from_check(self) -> dict[str, float]:
        seed = {code: 0.0 for code in self._type_codes}
        try:
            result = check_pictogram_needs(
                self.state.get_active_ol_df(),
                self.state.get_active_bom_ke_df(),
                NplStockService(self.state.db),
            )
        except ValueError:
            return seed
        for item in result.get("summary") or []:
            code = str(item.get("type_code", "")).upper()
            if code:
                seed[code] = float(item.get("needed") or 0)
        return seed

    def _build(self) -> None:
        body, header, content, footer = create_dialog_layout(self)
        ctk.CTkLabel(header, text="Count Pictogram", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=(
                f"Số lượng tem lấy từ Check Pictogram (cột «Cần») — chỉnh lại rồi tính vải · "
                f"khổ {FABRIC_WIDTH_CM}cm · cm tem S/M/L = 10/12/17"
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=660,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self.hint_label = ctk.CTkLabel(
            content,
            text="",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.hint_label.pack(fill="x", pady=(0, 8))

        table = ctk.CTkFrame(content, fg_color=COLORS["card"], corner_radius=8)
        table.pack(fill="both", expand=True)
        table_inner = ctk.CTkFrame(table, fg_color="transparent")
        table_inner.pack(fill="both", expand=True, padx=12, pady=12)

        head = ctk.CTkFrame(table_inner, fg_color="transparent")
        head.pack(fill="x", pady=(0, 6))
        for text, width in (
            ("Loại", 120),
            ("Số lượng cần", 110),
            ("Tem/hàng", 72),
            ("Hàng in", 64),
            ("Thực tế in", 80),
            ("Vải (m)", 72),
        ):
            ctk.CTkLabel(head, text=text, width=width, anchor="w", font=FONT_SMALL, text_color=COLORS["muted"]).pack(
                side="left", padx=(0, 8)
            )

        self.result_rows: dict[str, ctk.CTkFrame] = {}
        for code in self._type_codes:
            self._render_type_row(table_inner, code)

        self.summary_label = ctk.CTkLabel(
            table_inner,
            text="",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.summary_label.pack(fill="x", pady=(12, 0))

        ctk.CTkButton(footer, text="Nạp lại từ Check", width=120, command=self._reload_from_check).pack(side="left")
        ctk.CTkButton(footer, text="Tính lại", width=90, command=self._recalculate).pack(side="left", padx=(8, 0))
        ctk.CTkButton(footer, text="Đóng", width=80, command=self.destroy).pack(side="right")

        if not any(self._seed.get(c, 0) for c in self._type_codes):
            self.hint_label.configure(
                text="Chưa có dữ liệu Check — chạy Check Pictogram (hoặc đọc OL + bảng kê) rồi bấm «Nạp lại từ Check»."
            )
        else:
            self.hint_label.configure(text="Đã nạp số lượng «Cần» từ Check — sửa cột Số lượng cần nếu muốn.")

    def _render_type_row(self, parent, code: str) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ctk.CTkLabel(row, text=code, width=120, anchor="w", font=FONT_SMALL).pack(side="left", padx=(0, 8))

        var = ctk.StringVar(value=format_qty(self._seed.get(code, 0)))
        self._qty_vars[code] = var
        entry = ctk.CTkEntry(row, textvariable=var, width=110, height=30)
        entry.pack(side="left", padx=(0, 8))
        entry.bind("<FocusOut>", lambda _e: self._recalculate())
        entry.bind("<Return>", lambda _e: self._recalculate())

        lbl_per_row = ctk.CTkLabel(row, text="—", width=72, anchor="w")
        lbl_per_row.pack(side="left", padx=(0, 8))
        lbl_rows = ctk.CTkLabel(row, text="—", width=64, anchor="w")
        lbl_rows.pack(side="left", padx=(0, 8))
        lbl_actual = ctk.CTkLabel(row, text="—", width=80, anchor="w", text_color=COLORS["accent"][1])
        lbl_actual.pack(side="left", padx=(0, 8))
        lbl_fabric = ctk.CTkLabel(row, text="—", width=72, anchor="w")
        lbl_fabric.pack(side="left")

        self.result_rows[code] = row
        row._lbl_per_row = lbl_per_row  # type: ignore[attr-defined]
        row._lbl_rows = lbl_rows  # type: ignore[attr-defined]
        row._lbl_actual = lbl_actual  # type: ignore[attr-defined]
        row._lbl_fabric = lbl_fabric  # type: ignore[attr-defined]

    def _collect_quantities(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for code, var in self._qty_vars.items():
            text = var.get().strip()
            try:
                out[code] = max(0.0, float(text or 0))
            except ValueError:
                out[code] = 0.0
        return out

    def _reload_from_check(self) -> None:
        try:
            result = check_pictogram_needs(
                self.state.get_active_ol_df(),
                self.state.get_active_bom_ke_df(),
                NplStockService(self.state.db),
            )
        except ValueError as exc:
            messagebox.showwarning("Count Pictogram", str(exc), parent=self)
            self.hint_label.configure(text=str(exc))
            return

        for item in result.get("summary") or []:
            code = str(item.get("type_code", "")).upper()
            if code in self._qty_vars:
                self._qty_vars[code].set(format_qty(item.get("needed") or 0))
        self.hint_label.configure(text="Đã nạp lại số lượng «Cần» từ Check Pictogram.")
        self._recalculate()

    def _recalculate(self) -> None:
        quantities = self._collect_quantities()
        result = calculate_pictogram_fabric(quantities, label_types=self._type_codes)
        for item in result.get("rows") or []:
            code = item["label_type"]
            row = self.result_rows.get(code)
            if not row:
                continue
            row._lbl_per_row.configure(text=str(item["labels_per_row"]))  # type: ignore[attr-defined]
            row._lbl_rows.configure(text=str(item["min_rows"]))  # type: ignore[attr-defined]
            row._lbl_actual.configure(text=format_qty(item["actual_labels"]))  # type: ignore[attr-defined]
            row._lbl_fabric.configure(text=format_qty(item["fabric_m"]))  # type: ignore[attr-defined]
        self.summary_label.configure(text=f"Tổng vải: {format_qty(result.get('fabric_total_m', 0))} m")


class PictogramLineDetailDialog(ctk.CTkToplevel):
    """Popup chi tiết S/O dùng mã Pictogram trong một dòng Check."""

    def __init__(self, master, item: dict) -> None:
        super().__init__(master)
        ma = normalize_str(item.get("ma_npl"))
        self.title(f"Pictogram — {ma}")
        configure_dialog(self, width=520, height=420, min_width=440, min_height=320, parent=master)
        self._build(item)
        show_dialog(self, master)

    def _build(self, item: dict) -> None:
        body, header, content, footer = create_dialog_layout(self)
        ma = normalize_str(item.get("ma_npl"))
        ctk.CTkLabel(header, text=ma, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=f"{normalize_str(item.get('ten_npl'))} · Loại {normalize_str(item.get('type_code'))}",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        table = ctk.CTkFrame(content, fg_color=COLORS["card"], corner_radius=8)
        table.pack(fill="both", expand=True)
        table_inner = ctk.CTkFrame(table, fg_color="transparent")
        table_inner.pack(fill="both", expand=True, padx=12, pady=12)

        head = ctk.CTkFrame(table_inner, fg_color="transparent")
        head.pack(fill="x", pady=(0, 6))
        for text, width in (("S/O (DG Case)", 200), ("Cần", 80)):
            ctk.CTkLabel(head, text=text, width=width, anchor="w", font=FONT_SMALL, text_color=COLORS["muted"]).pack(
                side="left", padx=(0, 8)
            )

        scroll = ctk.CTkScrollableFrame(table_inner, fg_color="transparent", height=220)
        scroll.pack(fill="both", expand=True)

        line_items = item.get("line_items") or []
        if not line_items and item.get("dg_cases"):
            line_items = [{"dg_case": dg, "needed": 0.0} for dg in item.get("dg_cases") or []]

        total = 0.0
        for line in line_items:
            qty = float(line.get("needed") or 0)
            total += qty
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=normalize_str(line.get("dg_case")), width=200, anchor="w", font=FONT_SMALL).pack(
                side="left", padx=(0, 8)
            )
            ctk.CTkLabel(row, text=format_qty(qty), width=80, anchor="w").pack(side="left")

        if not line_items:
            ctk.CTkLabel(scroll, text="Không có S/O.", text_color=COLORS["muted"], font=FONT_SMALL).pack(pady=12)

        ctk.CTkLabel(
            table_inner,
            text=f"Tổng {len(line_items)} S/O · Cần {format_qty(total)}",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            anchor="w",
        ).pack(fill="x", pady=(10, 0))

        ctk.CTkButton(footer, text="Đóng", width=80, command=self.destroy).pack(side="right")


class CheckPictogramDialog(ctk.CTkToplevel):
    def __init__(self, master, state: AppState) -> None:
        super().__init__(master)
        self.state = state
        self.title("Check Pictogram")
        configure_dialog(self, width=960, height=640, min_width=820, min_height=500, parent=master)
        self._pager = TablePager()
        self._rows: list[dict] = []
        self._last_summary: list[dict] = []
        self._raw_result: dict | None = None
        self._excluded_ma: set[str] = set()
        self._build()
        self._refresh()
        show_dialog(self, master)

    def _build(self) -> None:
        body, header, content, footer = create_dialog_layout(self)
        ctk.CTkLabel(header, text="Check Pictogram", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Dò DG Case (OL) = Số S/O bảng kê · chỉ mã khớp loại Pictogram đang theo dõi · double-click dòng xem S/O",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w", pady=(4, 0))

        self.status_label = ctk.CTkLabel(content, text="", font=FONT_SMALL, text_color=COLORS["muted"], anchor="w")
        self.status_label.pack(fill="x", pady=(0, 4))
        self.hint_label = ctk.CTkLabel(
            content,
            text="Tick «Bỏ» để loại dòng lỗi khỏi tổng Cần/In · double-click mở danh sách S/O dùng mã đó",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            anchor="w",
        )
        self.hint_label.pack(fill="x", pady=(0, 6))

        self.summary_wrap = ctk.CTkFrame(content, fg_color=COLORS["card"], corner_radius=8)
        self.summary_wrap.pack(fill="x", pady=(0, 8))

        table_box = ctk.CTkFrame(content, fg_color=COLORS["card"], corner_radius=8)
        table_box.pack(fill="both", expand=True)
        table_box.grid_columnconfigure(0, weight=1)
        table_box.grid_rowconfigure(2, weight=1)
        self._render_detail_header(table_box)
        self._pager_bar = TablePagerBar(
            table_box,
            self._pager,
            on_change=self._render_detail_page,
            placeholder="Lọc mã NPL, DG case…",
        )
        self._pager_bar.set_filter_handler(self._quick_filter)
        self._pager_bar.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 0))
        self.detail_wrap = ctk.CTkScrollableFrame(table_box, fg_color="transparent")
        self.detail_wrap.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))

        ctk.CTkButton(
            footer,
            text="→ Count Pictogram",
            width=130,
            fg_color=COLORS["accent"][1],
            command=self._open_count,
        ).pack(side="left")
        ctk.CTkButton(footer, text="Làm mới", width=90, command=self._refresh).pack(side="left", padx=(8, 0))
        self.restore_btn = ctk.CTkButton(
            footer,
            text="Khôi phục đã loại",
            width=130,
            command=self._restore_excluded,
            fg_color=COLORS["muted"],
        )
        ctk.CTkButton(footer, text="Đóng", width=80, command=self.destroy).pack(side="right")

    def _open_count(self) -> None:
        seed: dict[str, float] = {}
        for item in self._last_summary:
            code = str(item.get("type_code", "")).upper()
            if code:
                seed[code] = float(item.get("needed") or 0)
        CountPictogramDialog(self.master, self.state, seed=seed or None)

    def _render_detail_header(self, parent) -> None:
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        for text, width in (
            ("Bỏ", 36),
            ("Mã NPL", 130),
            ("Loại", 100),
            ("Cần", 72),
            ("Tồn loại", 72),
            ("Cần in", 72),
            ("DG Case", 56),
            ("Tên NPL", 120),
        ):
            ctk.CTkLabel(head, text=text, width=width, anchor="w", font=FONT_SMALL, text_color=COLORS["muted"]).pack(
                side="left", padx=(0, 4)
            )

    def _quick_filter(self, item: dict, q: str) -> bool:
        blob = " ".join(
            normalize_str(item.get(k))
            for k in ("ma_npl", "ten_npl", "type_code", "dg_cases")
        ).lower()
        if isinstance(item.get("dg_cases"), list):
            blob += " " + " ".join(item["dg_cases"]).lower()
        return q in blob

    def _restore_excluded(self) -> None:
        if not self._excluded_ma:
            return
        self._excluded_ma.clear()
        self._apply_view()

    def _toggle_exclude(self, ma_npl: str, var: ctk.BooleanVar) -> None:
        key = pictogram_ma_key(ma_npl)
        if var.get():
            self._excluded_ma.add(key)
        else:
            self._excluded_ma.discard(key)
        self._apply_view()

    def _open_line_detail(self, item: dict) -> None:
        PictogramLineDetailDialog(self, item)

    def _apply_view(self) -> None:
        if not self._raw_result:
            return
        result = apply_pictogram_exclusions(self._raw_result, self._excluded_ma)
        excluded_n = result.get("excluded_ma_count") or 0
        active_n = result.get("active_detail_count") or 0

        missing = result.get("missing_bom_cases") or []
        no_picto = result.get("cases_without_picto") or []
        tracked = result.get("tracked_codes_label") or ""
        status = (
            f"{result['ol_dg_count']} DG Case (OL) · "
            f"{result.get('matched_bom_count', 0)} khớp S/O · "
            f"{result.get('cases_with_picto_count', 0)} có Picto theo dõi · "
            f"{active_n} mã tính · theo dõi: {tracked}"
        )
        if excluded_n:
            status += f" · đã loại {excluded_n} mã"
        if missing:
            status += f" · {len(missing)} S/O không có bảng kê"
        if no_picto:
            status += f" · {len(no_picto)} S/O không có mã khớp"
        if active_n == 0 and not excluded_n:
            status += " — kiểm tra đã đọc OL + bảng kê đầy đủ (Setup)."
        self.status_label.configure(text=status)

        if excluded_n:
            self.restore_btn.pack(side="left", padx=(8, 0))
        else:
            self.restore_btn.pack_forget()

        self._last_summary = result.get("summary") or []
        self._render_summary(self._last_summary)
        self._rows = result.get("details") or []
        self._pager.set_items(self._rows, filter_fn=self._quick_filter)
        self._render_detail_page()

    def _refresh(self) -> None:
        try:
            result = check_pictogram_needs(
                self.state.get_active_ol_df(),
                self.state.get_active_bom_ke_df(),
                NplStockService(self.state.db),
            )
        except ValueError as exc:
            messagebox.showwarning("Check Pictogram", str(exc), parent=self)
            self.status_label.configure(text=str(exc))
            self._rows = []
            self._last_summary = []
            self._raw_result = None
            self._excluded_ma.clear()
            self._pager.set_items([])
            self._render_summary([])
            self._render_detail_page()
            self.restore_btn.pack_forget()
            return

        self._raw_result = result
        self._excluded_ma.clear()
        self._apply_view()

    def _render_summary(self, rows: list[dict]) -> None:
        for w in self.summary_wrap.winfo_children():
            w.destroy()
        inner = ctk.CTkFrame(self.summary_wrap, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        if not rows:
            ctk.CTkLabel(inner, text="—", text_color=COLORS["muted"]).pack(anchor="w")
            return
        for item in rows:
            code = item["type_code"]
            name = item.get("type_name") or code
            need = format_qty(item["needed"])
            stock = format_qty(item["stock"])
            pr = format_qty(item["print"])
            color = COLORS["warning"][1] if item["print"] > 0 else COLORS["success"][1]
            card = ctk.CTkFrame(inner, fg_color=COLORS["bg"], corner_radius=8)
            card.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(card, text=name, font=FONT_SMALL, text_color=COLORS["muted"]).pack(
                padx=12, pady=(8, 0), anchor="w"
            )
            ctk.CTkLabel(card, text=code, font=FONT_SMALL, text_color=COLORS["muted"]).pack(
                padx=12, anchor="w"
            )
            ctk.CTkLabel(card, text=f"Cần {need} · Tồn {stock}", font=FONT_BODY).pack(padx=12, anchor="w")
            ctk.CTkLabel(card, text=f"In thêm {pr}", font=("Segoe UI", 13, "bold"), text_color=color).pack(
                padx=12, pady=(0, 8), anchor="w"
            )

    def _render_detail_page(self) -> None:
        for w in self.detail_wrap.winfo_children():
            w.destroy()
        items = self._pager.page_items()
        if not items:
            ctk.CTkLabel(
                self.detail_wrap,
                text="Không có mã Pictogram trong các DG Case OL.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(pady=16, anchor="w")
            return
        for item in items:
            excluded = bool(item.get("excluded"))
            row = ctk.CTkFrame(
                self.detail_wrap,
                fg_color=("gray92", "gray22") if excluded else "transparent",
                corner_radius=4,
            )
            row.pack(fill="x", pady=2)
            row.configure(cursor="hand2")
            row.bind("<Double-Button-1>", lambda _e, it=item: self._open_line_detail(it))

            ma = item.get("ma_npl", "")
            ma_key = pictogram_ma_key(ma)
            exclude_var = ctk.BooleanVar(value=ma_key in self._excluded_ma)
            chk = ctk.CTkCheckBox(
                row,
                text="",
                width=28,
                checkbox_width=18,
                checkbox_height=18,
                variable=exclude_var,
                command=lambda v=exclude_var, m=ma: self._toggle_exclude(m, v),
            )
            chk.pack(side="left", padx=(0, 2))

            print_qty = item.get("print_share", 0)
            print_color = None if excluded else (COLORS["warning"][1] if print_qty > 0 else None)
            muted = COLORS["muted"] if excluded else None

            def add_lbl(parent, text, width, **extra):
                lbl = ctk.CTkLabel(parent, text=text, width=width, anchor="w", font=FONT_SMALL, **extra)
                lbl.pack(side="left", padx=(0, 4))
                lbl.configure(cursor="hand2")
                lbl.bind("<Double-Button-1>", lambda _e, it=item: self._open_line_detail(it))
                return lbl

            add_lbl(row, ma, 130, text_color=muted)
            add_lbl(row, item.get("type_code", ""), 100, text_color=muted)
            add_lbl(row, format_qty(item.get("needed", 0)), 72, text_color=muted)
            add_lbl(row, format_qty(item.get("stock_type", 0)), 72, text_color=muted)
            add_lbl(row, format_qty(print_qty), 72, text_color=print_color or muted)
            add_lbl(row, str(item.get("dg_case_count", 0)), 56, text_color=muted)
            add_lbl(row, item.get("ten_npl", "")[:36], 120, text_color=muted)


def normalize_str(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return text


def open_count_pictogram_dialog(master, state: AppState) -> None:
    CountPictogramDialog(master, state)


def open_check_pictogram_dialog(master, state: AppState) -> None:
    CheckPictogramDialog(master, state)
