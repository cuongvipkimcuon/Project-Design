"""Tab quản lý tồn NPL — Pictogram / Plastic Label."""

from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from core.app_state import AppState
from core.npl_stock_service import (
    INPUT_UNIT_PCS,
    INPUT_UNIT_ROLL,
    MODULE_PICTOGRAM,
    MODULE_PLASTIC_LABEL,
    TXN_COMPENSATION,
    TXN_LABELS,
    TXN_LOSS,
    TXN_RECEIPT,
    NplStockService,
    balance_display_parts,
    format_qty,
    input_to_pcs,
)
from core.utils import normalize_text
from ui.dialog_utils import configure_dialog, show_dialog
from ui.pictogram_tool_dialogs import open_check_pictogram_dialog, open_count_pictogram_dialog
from ui.table_pager import TablePager, TablePagerBar
from ui.theme import COLORS, FONT_BODY, FONT_SMALL

MODULE_TITLES = {
    MODULE_PICTOGRAM: ("Tồn Pictogram", "Theo dõi 720.176.USA.S / M / L theo pcs · xuất FIFO"),
    MODULE_PLASTIC_LABEL: ("Tồn Plastic Label", "Blue / White Label · nhập theo roll hoặc pcs"),
}

MODULE_INFO = {
    MODULE_PICTOGRAM: {
        "rules": [
            "Tồn theo pcs — loại 720.176.USA.S / M / L (khớp mã NPL bảng kê).",
            "Check phiếu Supplier → trừ tự động theo mã NPL dòng phiếu.",
            "Prepare: có thể map tồn thủ công nếu mã không khớp rule.",
            "Nhập / Hư hao / Bù đắp: nhập theo pcs — mỗi lần nhập/bù tạo mã lô (FIFO).",
            "Xuất (check phiếu, hư hao) trừ lô cũ nhất trước.",
        ],
        "summary_primary": "Tổng pcs",
        "summary_secondary": "",
    },
    MODULE_PLASTIC_LABEL: {
        "rules": [
            "Blue Label: mã 705.204… · White Label: mã 705.800…",
            "Tồn lưu theo roll (1 roll = 100 pcs). Check phiếu trừ theo số pcs dòng phiếu.",
            "Nhập / Hư hao / Bù đắp: chọn nhập roll hoặc pcs — mỗi lần nhập/bù tạo mã lô.",
            "Xuất trừ theo FIFO (lô nhập cũ nhất trước).",
            "704 / keyword blue|white vẫn map fallback khi không có mã 705.",
        ],
        "summary_primary": "Tổng roll",
        "summary_secondary": "Quy đổi pcs",
    },
}

STOCK_HEADERS = (("Loại NPL", 200), ("Mã", 120), ("Tồn hiện tại", 160), ("Thao tác", 380))
BATCH_HEADERS = (
    ("#", 36),
    ("Mã lô", 130),
    ("Loại NPL", 110),
    ("Còn lại", 100),
    ("Nhập lúc", 118),
    ("Người NH", 88),
    ("Ghi chú", 140),
)
LEDGER_HEADERS = (
    ("Thời gian", 108),
    ("Người TH", 76),
    ("Giao dịch", 76),
    ("Loại", 80),
    ("Lô", 100),
    ("Thay đổi", 92),
    ("Phiếu", 76),
    ("Ghi chú", 80),
)


class NplStockPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        state: AppState,
        *,
        module: str,
        perm_module: str,
        on_open_slip=None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.app_state = state
        self.module = module
        self._on_open_slip = on_open_slip
        self._can_write = state.user.can_write(perm_module)
        self._can_manage_types = state.user.can_manage_npl_types()
        self.svc = NplStockService(state.db)
        title, desc = MODULE_TITLES.get(module, ("NPL Stock", ""))
        self._title = title
        self._desc = desc
        self._info = MODULE_INFO.get(module, {})
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build()
        self._reload_job: str | None = None
        self._reload_dirty = False
        state.on_change(self._schedule_reload)
        self.bind("<Map>", self._on_map)
        self._reload()

    def destroy(self) -> None:
        try:
            self.app_state._listeners.remove(self._schedule_reload)
        except (ValueError, AttributeError):
            pass
        if self._reload_job:
            try:
                self.after_cancel(self._reload_job)
            except Exception:
                pass
        super().destroy()

    def _schedule_reload(self) -> None:
        if not self.winfo_exists():
            return
        try:
            if not self.winfo_ismapped():
                self._reload_dirty = True
                return
        except Exception:
            pass
        if self._reload_job:
            try:
                self.after_cancel(self._reload_job)
            except Exception:
                pass
        self._reload_job = self.after(250, self._reload)

    def _build(self) -> None:
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 6))
        toolbar.grid_columnconfigure(0, weight=1)
        title_box = ctk.CTkFrame(toolbar, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_box, text=self._title, font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text=self._desc,
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(anchor="w")

        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        btn_state = "normal" if self._can_write else "disabled"
        ctk.CTkButton(
            actions,
            text="Làm mới",
            width=80,
            height=30,
            fg_color="transparent",
            border_width=1,
            command=self._reload,
        ).pack(side="right")
        if self.module == MODULE_PICTOGRAM:
            ctk.CTkButton(
                actions,
                text="Check Pictogram",
                width=120,
                height=30,
                fg_color="transparent",
                border_width=1,
                command=lambda: open_check_pictogram_dialog(self.winfo_toplevel(), self.app_state),
            ).pack(side="right", padx=(0, 8))
            ctk.CTkButton(
                actions,
                text="Count Pictogram",
                width=120,
                height=30,
                fg_color="transparent",
                border_width=1,
                command=lambda: open_count_pictogram_dialog(self.winfo_toplevel(), self.app_state),
            ).pack(side="right", padx=(0, 8))
        if self._can_manage_types:
            ctk.CTkButton(
                actions,
                text="+ Thêm loại",
                width=100,
                height=30,
                fg_color=COLORS["accent"][1],
                command=self._add_stock_type,
            ).pack(side="right", padx=(0, 8))
        elif self._can_write:
            ctk.CTkLabel(
                actions,
                text="Loại NPL: chỉ admin",
                font=FONT_SMALL,
                text_color=COLORS["muted"],
            ).pack(side="right", padx=(0, 8))
        if not self._can_write:
            ctk.CTkLabel(
                actions,
                text="Chỉ xem",
                font=FONT_SMALL,
                text_color=COLORS["warning"][1],
            ).pack(side="right", padx=(0, 10))

        self.main_tabs = ctk.CTkTabview(self)
        self.main_tabs.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.main_tabs.add("Tồn theo loại")
        self.main_tabs.add("Lô nhập (FIFO)")
        self.main_tabs.add("Nhật ký")

        stock_tab = self.main_tabs.tab("Tồn theo loại")
        batch_tab = self.main_tabs.tab("Lô nhập (FIFO)")
        ledger_tab = self.main_tabs.tab("Nhật ký")

        stock_tab.grid_columnconfigure(0, weight=1)
        stock_tab.grid_rowconfigure(1, weight=1)
        batch_tab.grid_columnconfigure(0, weight=1)
        batch_tab.grid_rowconfigure(2, weight=1)
        ledger_tab.grid_columnconfigure(0, weight=1)
        ledger_tab.grid_rowconfigure(2, weight=1)

        self._render_fixed_header(stock_tab, STOCK_HEADERS, row=0, padx=4)
        self.stock_wrap = ctk.CTkScrollableFrame(stock_tab, fg_color="transparent")
        self.stock_wrap.grid(row=1, column=0, sticky="nsew", padx=4, pady=(4, 8))

        self._render_fixed_header(batch_tab, BATCH_HEADERS, row=0, padx=4)
        self._batch_pager = TablePager()
        self._batch_rows: list[dict] = []
        self._batch_pager_bar = TablePagerBar(
            batch_tab,
            self._batch_pager,
            on_change=self._render_batch_page,
            placeholder="Lọc mã lô, loại NPL…",
        )
        self._batch_pager_bar.set_filter_handler(self._batch_quick_filter)
        self._batch_pager_bar.grid(row=1, column=0, sticky="ew", padx=4, pady=(4, 0))
        self.batch_wrap = ctk.CTkScrollableFrame(batch_tab, fg_color="transparent")
        self.batch_wrap.grid(row=2, column=0, sticky="nsew", padx=4, pady=(4, 8))

        self._render_fixed_header(ledger_tab, LEDGER_HEADERS, row=0, padx=4)
        self._ledger_pager = TablePager()
        self._ledger_rows: list[dict] = []
        self._ledger_pager_bar = TablePagerBar(
            ledger_tab,
            self._ledger_pager,
            on_change=self._render_ledger_page,
            placeholder="Lọc giao dịch, phiếu, người… (double-click mở phiếu)",
        )
        self._ledger_pager_bar.set_filter_handler(self._ledger_quick_filter)
        self._ledger_pager_bar.grid(row=1, column=0, sticky="ew", padx=4, pady=(4, 0))
        self.ledger_wrap = ctk.CTkScrollableFrame(ledger_tab, fg_color="transparent")
        self.ledger_wrap.grid(row=2, column=0, sticky="nsew", padx=4, pady=(4, 8))

        self._reload()

    def _render_fixed_header(
        self,
        parent,
        headers: tuple[tuple[str, int], ...],
        *,
        row: int = 1,
        padx: int = 0,
        pady: tuple[int, int] = (0, 4),
    ) -> None:
        bar = ctk.CTkFrame(parent, fg_color=("gray88", "gray28"), corner_radius=6)
        bar.grid(row=row, column=0, sticky="ew", padx=padx, pady=pady)
        for title, width in headers:
            ctk.CTkLabel(
                bar,
                text=title,
                width=width,
                anchor="w",
                font=("Segoe UI", 11, "bold"),
            ).pack(side="left", padx=6, pady=7)

    @staticmethod
    def _ledger_quick_filter(row: dict, query: str) -> bool:
        meta = row.get("meta") or {}
        blob = " ".join(
            [
                normalize_text(row.get("txn_type")),
                normalize_text(row.get("type_name")),
                normalize_text(row.get("actor")),
                normalize_text(row.get("note")),
                normalize_text(row.get("slip_code")),
                normalize_text(row.get("created_at")),
                normalize_text(meta.get("batch_code")),
            ]
        ).lower()
        return query in blob

    @staticmethod
    def _batch_quick_filter(row: dict, query: str) -> bool:
        blob = " ".join(
            [
                normalize_text(row.get("batch_code")),
                normalize_text(row.get("type_name")),
                normalize_text(row.get("actor")),
                normalize_text(row.get("note")),
            ]
        ).lower()
        return query in blob

    def _reload(self) -> None:
        self._reload_job = None
        self._reload_dirty = False
        types = self.svc.list_types(self.module)

        for w in self.stock_wrap.winfo_children():
            w.destroy()
        if not types:
            ctk.CTkLabel(
                self.stock_wrap,
                text="Chưa có loại NPL — bấm + Thêm loại.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
                wraplength=420,
                justify="left",
            ).pack(pady=20, padx=8, anchor="w")
        else:
            for t in types:
                self._render_stock_row(t)

        self._ledger_rows = self.svc.list_ledger(self.module)
        self._ledger_pager.set_items(self._ledger_rows, filter_fn=self._ledger_quick_filter, reset_page=False)
        self._render_ledger_page()

        self._batch_rows = self.svc.list_batches(self.module)
        self._batch_pager.set_items(self._batch_rows, filter_fn=self._batch_quick_filter, reset_page=False)
        self._render_batch_page()

    def _on_map(self, _event=None) -> None:
        if self._reload_dirty:
            self._schedule_reload()

    def _render_batch_page(self) -> None:
        for w in self.batch_wrap.winfo_children():
            w.destroy()
        page_items = self._batch_pager.page_items()
        self._batch_pager_bar.refresh_info()
        if not page_items and not self._batch_rows:
            ctk.CTkLabel(
                self.batch_wrap,
                text="Chưa có lô — bấm Nhập hoặc Bù đắp để tạo mã lô.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(pady=16, padx=8, anchor="w")
            return
        if not page_items:
            ctk.CTkLabel(
                self.batch_wrap,
                text="Không khớp bộ lọc.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(pady=16)
            return
        for idx, batch in enumerate(page_items, start=1):
            self._render_batch_row(batch, idx)

    def _render_batch_row(self, batch: dict, fifo_no: int) -> None:
        unit = normalize_text(batch.get("unit_label")) or INPUT_UNIT_PCS
        bal = float(batch.get("balance") or 0)
        empty = bal <= 1e-9
        bg = ("gray90", "gray22") if empty else ("gray95", "gray26")
        line = ctk.CTkFrame(self.batch_wrap, fg_color=bg, corner_radius=6)
        line.pack(fill="x", pady=2)
        when = normalize_text(batch.get("created_at"))[:16].replace("T", " ")
        note = normalize_text(batch.get("note")) or "—"
        if len(note) > 28:
            note = note[:27] + "…"
        vals = [
            str(fifo_no),
            normalize_text(batch.get("batch_code")) or "—",
            normalize_text(batch.get("type_name")) or "—",
            f"{format_qty(bal)} {unit}",
            when,
            normalize_text(batch.get("actor")) or "—",
            note,
        ]
        for (title, width), text in zip(BATCH_HEADERS, vals):
            color = COLORS["muted"][1] if empty else None
            ctk.CTkLabel(
                line,
                text=text,
                width=width,
                anchor="w",
                font=FONT_SMALL,
                text_color=color,
            ).pack(side="left", padx=6, pady=6)

    def _render_ledger_page(self) -> None:
        for w in self.ledger_wrap.winfo_children():
            w.destroy()
        page_items = self._ledger_pager.page_items()
        self._ledger_pager_bar.refresh_info()
        if not page_items and not self._ledger_rows:
            ctk.CTkLabel(
                self.ledger_wrap,
                text="Chưa có giao dịch — nhập kho hoặc check phiếu Supplier để ghi nhận.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
                wraplength=420,
                justify="left",
            ).pack(pady=20, padx=8, anchor="w")
            return
        if not page_items:
            ctk.CTkLabel(
                self.ledger_wrap,
                text="Không khớp bộ lọc.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(pady=20)
            return
        for row in page_items:
            self._render_ledger_row(row)

    def _render_stock_row(self, stock_type: dict) -> None:
        primary, secondary = balance_display_parts(stock_type)
        balance_text = primary if not secondary else f"{primary} · {secondary}"
        bal_val = float(stock_type.get("balance") or stock_type.get("balance_pcs") or 0)
        low_stock = bal_val <= 1e-9

        row = ctk.CTkFrame(self.stock_wrap, fg_color=("gray95", "gray26"), corner_radius=8)
        row.pack(fill="x", pady=3)

        name = str(stock_type.get("name") or "—")
        code = str(stock_type.get("code") or "—")
        bal_color = COLORS["warning"][1] if low_stock else COLORS["success"][1]

        ctk.CTkLabel(row, text=name, width=STOCK_HEADERS[0][1], anchor="w", font=("Segoe UI", 12, "bold")).pack(
            side="left", padx=6, pady=8
        )
        ctk.CTkLabel(
            row, text=code, width=STOCK_HEADERS[1][1], anchor="w", font=FONT_SMALL, text_color=COLORS["muted"]
        ).pack(side="left", padx=6, pady=8)
        ctk.CTkLabel(
            row,
            text=balance_text,
            width=STOCK_HEADERS[2][1],
            anchor="w",
            font=FONT_BODY,
            text_color=bal_color,
        ).pack(side="left", padx=6, pady=8)

        btns = ctk.CTkFrame(row, fg_color="transparent", width=STOCK_HEADERS[3][1])
        btns.pack(side="left", padx=6, pady=6)
        btns.pack_propagate(False)
        btn_state = "normal" if self._can_write else "disabled"
        manage_state = "normal" if self._can_manage_types else "disabled"
        tid = int(stock_type["id"])
        actions = [
            ("Nhập", TXN_RECEIPT, COLORS["success"][1]),
            ("Hư hao", TXN_LOSS, "#c62828"),
            ("Bù đắp", TXN_COMPENSATION, COLORS["warning"][1]),
        ]
        for idx, (label, txn, color) in enumerate(actions):
            ctk.CTkButton(
                btns,
                text=label,
                width=68,
                height=28,
                fg_color=color,
                hover_color=color,
                command=lambda t=tid, x=txn, n=stock_type.get("name"): self._manual_txn(t, x, n),
                state=btn_state,
            ).grid(row=0, column=idx, padx=(0 if idx == 0 else 3, 0))
        ctk.CTkButton(
            btns,
            text="Sửa",
            width=48,
            height=28,
            fg_color="transparent",
            border_width=1,
            command=lambda st=stock_type: self._edit_stock_type(st),
            state=manage_state,
        ).grid(row=0, column=3, padx=(6, 0))
        ctk.CTkButton(
            btns,
            text="Xóa",
            width=48,
            height=28,
            fg_color="transparent",
            border_width=1,
            text_color="#c62828",
            command=lambda st=stock_type: self._delete_stock_type(st),
            state=manage_state,
        ).grid(row=0, column=4, padx=(3, 0))

    def _render_ledger_row(self, row: dict) -> None:
        txn_key = normalize_text(row.get("txn_type"))
        txn = TXN_LABELS.get(txn_key, row.get("txn_type"))
        unit = normalize_text(row.get("unit_label")) or INPUT_UNIT_PCS
        delta = float(row.get("qty_delta") or 0)
        pcs = float(row.get("qty_pcs") or 0)
        sign = "+" if delta > 0 else ""
        when = normalize_text(row.get("created_at"))[:16].replace("T", " ")
        actor = normalize_text(row.get("actor")) or "—"
        slip_code = normalize_text(row.get("slip_code"))
        slip_id = row.get("slip_id")
        slip_text = slip_code if slip_code else ("—" if not slip_id else f"#{slip_id}")
        change = f"{sign}{format_qty(delta)} {unit}"
        if unit == "roll":
            change += f" ({format_qty(pcs)} pcs)"
        note = normalize_text(row.get("note")) or "—"
        meta = row.get("meta") or {}
        batch_text = normalize_text(meta.get("batch_code")) or "—"
        if len(batch_text) > 18:
            batch_text = batch_text[:17] + "…"

        if txn_key == TXN_RECEIPT:
            bg = ("#e8f5e9", "#1b3d24")
        elif txn_key == TXN_LOSS:
            bg = ("#ffebee", "#3d2020")
        elif txn_key == TXN_COMPENSATION:
            bg = ("#fff8e1", "#3d3420")
        else:
            bg = ("gray95", "gray26")

        line = ctk.CTkFrame(self.ledger_wrap, fg_color=bg, corner_radius=6)
        line.pack(fill="x", pady=2)
        if slip_id and self._on_open_slip:
            line.bind("<Double-Button-1>", lambda _e, sid=int(slip_id): self._on_open_slip(sid))
            line.configure(cursor="hand2")

        values = [
            when,
            actor,
            txn,
            normalize_text(row.get("type_name")),
            batch_text,
            change,
            slip_text,
            note[:32],
        ]
        change_color = COLORS["success"][1] if delta > 0 else ("#c62828" if delta < 0 else None)
        for col, ((title, width), text) in enumerate(zip(LEDGER_HEADERS, values)):
            kwargs: dict = {
                "text": str(text),
                "width": width,
                "anchor": "w",
                "font": FONT_SMALL,
            }
            if col == 5 and change_color:
                kwargs["text_color"] = change_color
            lbl = ctk.CTkLabel(line, **kwargs)
            lbl.pack(side="left", padx=6, pady=5)
            if slip_id and self._on_open_slip:
                lbl.bind("<Double-Button-1>", lambda _e, sid=int(slip_id): self._on_open_slip(sid))

    def _manual_txn(self, type_id: int, txn_type: str, type_name: str) -> None:
        StockTxnDialog(
            self.winfo_toplevel(),
            svc=self.svc,
            stock_type_id=type_id,
            txn_type=txn_type,
            type_name=str(type_name),
            actor=self.app_state.user.display_name or self.app_state.user.username,
            on_saved=self._reload,
        )

    def _add_stock_type(self) -> None:
        if not self._can_manage_types:
            messagebox.showwarning(
                "Loại NPL",
                "Chỉ admin được thêm loại NPL theo dõi.",
                parent=self.winfo_toplevel(),
            )
            return
        StockTypeFormDialog(
            self.winfo_toplevel(),
            module=self.module,
            svc=self.svc,
            actor_role=self.app_state.user.role,
            on_saved=self._reload,
        )

    def _edit_stock_type(self, stock_type: dict) -> None:
        if not self._can_manage_types:
            messagebox.showwarning(
                "Loại NPL",
                "Chỉ admin được sửa loại NPL theo dõi.",
                parent=self.winfo_toplevel(),
            )
            return
        StockTypeFormDialog(
            self.winfo_toplevel(),
            module=self.module,
            svc=self.svc,
            stock_type=stock_type,
            actor_role=self.app_state.user.role,
            on_saved=self._reload,
        )

    def _delete_stock_type(self, stock_type: dict) -> None:
        if not self._can_manage_types:
            messagebox.showwarning(
                "Loại NPL",
                "Chỉ admin được xóa loại NPL theo dõi.",
                parent=self.winfo_toplevel(),
            )
            return
        name = normalize_text(stock_type.get("name")) or "—"
        code = normalize_text(stock_type.get("code")) or "—"
        if not messagebox.askyesno(
            "Xóa loại NPL",
            f"Ẩn «{name}» ({code}) khỏi danh sách theo dõi?\n\n"
            "Lịch sử nhật ký / lô vẫn giữ. Chỉ xóa khi tồn = 0.",
            parent=self.winfo_toplevel(),
        ):
            return
        try:
            self.svc.delete_stock_type(int(stock_type["id"]), actor_role=self.app_state.user.role)
        except Exception as exc:
            messagebox.showerror("Xóa loại", str(exc), parent=self.winfo_toplevel())
            return
        self._reload()


class StockTypeFormDialog(ctk.CTkToplevel):
    """Thêm / sửa loại NPL — mã khớp (prefix/đuôi) + tên hiển thị."""

    def __init__(
        self,
        master,
        *,
        module: str,
        svc: NplStockService,
        on_saved,
        stock_type: dict | None = None,
        actor_role: str | None = None,
    ) -> None:
        super().__init__(master)
        self.module = module
        self.svc = svc
        self.stock_type = stock_type
        self.actor_role = actor_role
        self.type_id = int(stock_type["id"]) if stock_type else None
        self.on_saved = on_saved
        is_edit = self.type_id is not None
        if module == MODULE_PICTOGRAM:
            title = "Sửa loại Pictogram" if is_edit else "Thêm loại Pictogram"
        else:
            title = "Sửa loại Plastic Label" if is_edit else "Thêm loại Plastic Label"
        self.title(title)
        top = master.winfo_toplevel() if hasattr(master, "winfo_toplevel") else master
        configure_dialog(self, width=480, height=340, min_width=420, min_height=300, parent=top)
        self.transient(top)
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=16)

        if module == MODULE_PICTOGRAM:
            hint = "Mã khớp: mã NPL đầy đủ hoặc prefix (vd. 720.176.USA.S) — đuôi S/M/L xác định size tem"
            code_ph = "vd. 720.176.USA.S"
        else:
            hint = "Mã khớp: prefix mã NPL (vd. 705.204, blue) — dùng khi check phiếu tự trừ tồn"
            code_ph = "vd. 705.204 hoặc blue"
        ctk.CTkLabel(body, text=hint, font=FONT_SMALL, text_color=COLORS["muted"], wraplength=440, justify="left").pack(
            anchor="w", pady=(0, 12)
        )

        ctk.CTkLabel(body, text="Mã khớp NPL", anchor="w", font=FONT_SMALL).pack(fill="x")
        self.code_var = ctk.StringVar(value=normalize_text(stock_type.get("code")) if stock_type else "")
        ctk.CTkEntry(body, textvariable=self.code_var, placeholder_text=code_ph, height=34).pack(fill="x", pady=(4, 10))

        ctk.CTkLabel(body, text="Tên hiển thị", anchor="w", font=FONT_SMALL).pack(fill="x")
        self.name_var = ctk.StringVar(value=normalize_text(stock_type.get("name")) if stock_type else "")
        ctk.CTkEntry(body, textvariable=self.name_var, placeholder_text="Tên dễ nhớ khi tra cứu", height=34).pack(
            fill="x", pady=(4, 10)
        )

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkButton(foot, text="Hủy", fg_color="transparent", command=self.destroy).pack(side="right", padx=4)
        ctk.CTkButton(
            foot,
            text="Lưu",
            fg_color=COLORS["success"][1],
            command=self._save,
        ).pack(side="right")
        show_dialog(self, top)

    def _save(self) -> None:
        code = self.code_var.get().strip()
        if not code:
            messagebox.showwarning("Loại NPL", "Nhập mã khớp NPL.", parent=self)
            return
        name = self.name_var.get().strip()
        try:
            if self.type_id is not None:
                self.svc.update_stock_type(
                    self.type_id, code=code, name=name, actor_role=self.actor_role
                )
            else:
                self.svc.add_stock_type(
                    module=self.module, code=code, name=name, actor_role=self.actor_role
                )
        except PermissionError as exc:
            messagebox.showwarning("Loại NPL", str(exc), parent=self)
            return
        except Exception as exc:
            label = "Sửa loại" if self.type_id else "Thêm loại"
            messagebox.showerror(label, str(exc), parent=self)
            return
        self.on_saved()
        self.destroy()


class AddStockTypeDialog(StockTypeFormDialog):
    """Alias giữ tương thích."""

    def __init__(self, master, *, module: str, svc: NplStockService, on_saved) -> None:
        super().__init__(master, module=module, svc=svc, on_saved=on_saved)


class StockTxnDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        svc: NplStockService,
        stock_type_id: int,
        txn_type: str,
        type_name: str,
        actor: str,
        on_saved,
    ) -> None:
        super().__init__(master)
        self.svc = svc
        self.stock_type_id = stock_type_id
        self.txn_type = txn_type
        self.actor = actor
        self.on_saved = on_saved
        self.stock_type = svc.get_type(stock_type_id) or {}

        self.storage_unit = normalize_text(self.stock_type.get("unit_label")) or INPUT_UNIT_PCS
        self.divisor = float(self.stock_type.get("divisor") or 100)
        self.allow_roll_input = self.storage_unit == "roll"

        title = TXN_LABELS.get(txn_type, txn_type)
        self.title(f"{title} — {type_name}")
        top = master.winfo_toplevel() if hasattr(master, "winfo_toplevel") else master
        height = 340 if self.allow_roll_input else 300
        configure_dialog(self, width=440, height=height, min_width=380, min_height=height - 40, parent=top)
        self.transient(top)
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=12)

        if self.allow_roll_input:
            hint = (
                f"Tồn lưu theo roll (1 roll = {format_qty(self.divisor)} pcs). "
                "Chọn đơn vị nhập roll hoặc pcs."
            )
        else:
            hint = "Nhập số lượng theo pcs."
        if self.txn_type in (TXN_RECEIPT, TXN_COMPENSATION):
            hint += " Hệ thống tự tạo mã lô (FIFO)."
        ctk.CTkLabel(body, text=hint, font=FONT_SMALL, text_color=COLORS["muted"], wraplength=400).pack(
            anchor="w", pady=(0, 10)
        )

        if self.allow_roll_input:
            unit_row = ctk.CTkFrame(body, fg_color="transparent")
            unit_row.pack(fill="x", pady=(0, 8))
            ctk.CTkLabel(unit_row, text="Đơn vị nhập", font=FONT_SMALL).pack(side="left")
            self.input_unit_var = ctk.StringVar(value=INPUT_UNIT_PCS)
            ctk.CTkSegmentedButton(
                unit_row,
                values=[INPUT_UNIT_PCS, INPUT_UNIT_ROLL],
                variable=self.input_unit_var,
                command=lambda _v: self._update_preview(),
            ).pack(side="right")

        self.qty_label = ctk.CTkLabel(body, text="Số lượng (pcs)", anchor="w", font=FONT_SMALL)
        self.qty_label.pack(fill="x")
        self.qty_var = ctk.StringVar()
        self.qty_var.trace_add("write", lambda *_: self._update_preview())
        ctk.CTkEntry(body, textvariable=self.qty_var, height=34).pack(fill="x", pady=(4, 4))

        self.preview_label = ctk.CTkLabel(body, text="", font=FONT_SMALL, text_color=COLORS["accent"][1])
        self.preview_label.pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(body, text="Ghi chú", anchor="w", font=FONT_SMALL).pack(fill="x")
        self.note_var = ctk.StringVar()
        ctk.CTkEntry(body, textvariable=self.note_var, height=34).pack(fill="x", pady=(4, 10))

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(foot, text="Hủy", fg_color="transparent", command=self.destroy).pack(side="right", padx=4)
        ctk.CTkButton(
            foot,
            text="Lưu",
            fg_color=COLORS["success"][1],
            command=self._save,
        ).pack(side="right")

        if self.allow_roll_input:
            self.input_unit_var.trace_add("write", lambda *_: self._sync_qty_label())
            self._sync_qty_label()

        show_dialog(self, top)

    def _current_input_unit(self) -> str:
        if self.allow_roll_input:
            return normalize_text(self.input_unit_var.get()) or INPUT_UNIT_PCS
        return INPUT_UNIT_PCS

    def _sync_qty_label(self) -> None:
        unit = self._current_input_unit()
        label = "Số lượng (roll)" if unit == INPUT_UNIT_ROLL else "Số lượng (pcs)"
        self.qty_label.configure(text=label)
        self._update_preview()

    def _update_preview(self) -> None:
        raw = self.qty_var.get().strip().replace(",", "")
        if not raw:
            self.preview_label.configure(text="")
            return
        try:
            val = float(raw)
        except ValueError:
            self.preview_label.configure(text="")
            return
        if not self.allow_roll_input:
            self.preview_label.configure(text="")
            return
        unit = self._current_input_unit()
        try:
            pcs = input_to_pcs(self.stock_type, val, unit)
        except ValueError:
            self.preview_label.configure(text="")
            return
        rolls = pcs / self.divisor
        if unit == INPUT_UNIT_ROLL:
            self.preview_label.configure(text=f"≈ {format_qty(pcs)} pcs")
        else:
            self.preview_label.configure(text=f"≈ {format_qty(rolls)} roll")

    def _save(self) -> None:
        try:
            qty = float(self.qty_var.get().strip().replace(",", ""))
        except ValueError:
            messagebox.showwarning("NPL", "Nhập số lượng hợp lệ.", parent=self)
            return
        input_unit = self._current_input_unit()
        try:
            out = self.svc.record_manual(
                stock_type_id=self.stock_type_id,
                txn_type=self.txn_type,
                qty=qty,
                input_unit=input_unit,
                actor=self.actor,
                note=self.note_var.get().strip(),
            )
        except Exception as exc:
            messagebox.showerror("NPL", str(exc), parent=self)
            return
        batch_code = out.get("batch_code")
        if batch_code:
            messagebox.showinfo(
                "NPL",
                f"Đã lưu.\nMã lô: {batch_code}",
                parent=self,
            )
        self.on_saved()
        self.destroy()
