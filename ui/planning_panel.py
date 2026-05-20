"""Tab Orderlist Planning — OL hiện tại + kế hoạch giao tem trong tuần."""

from __future__ import annotations

from datetime import date, timedelta
from tkinter import messagebox, simpledialog

import customtkinter as ctk
import pandas as pd

from core.app_state import AppState
from core.ol_reader import OlReaderService
from core.utils import normalize_dg_case, normalize_text
from ui.theme import COLORS, FONT_BODY, FONT_SMALL
from ui.widgets.ol_table import OlTableWidget


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_start_str(d: date) -> str:
    return monday_of(d).strftime("%Y-%m-%d")


class PlanningPanel(ctk.CTkFrame):
    def __init__(self, master, state: AppState, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self.ol_service = OlReaderService(state.db)
        self.filter_var = ctk.StringVar()
        self._build()
        state.on_change(self._on_state_changed)
        self._load_initial_ol()

    def _build(self) -> None:
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 4))
        ctk.CTkLabel(top, text="Orderlist Planning", font=("Segoe UI", 20, "bold")).pack(side="left")
        self.ol_info = ctk.CTkLabel(top, text="", font=FONT_SMALL, text_color=COLORS["muted"])
        self.ol_info.pack(side="left", padx=16)

        ol_bar = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=10)
        ol_bar.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(ol_bar, text="Snapshot:", font=FONT_BODY).pack(side="left", padx=(12, 6), pady=10)
        self.snap_combo = ctk.CTkComboBox(
            ol_bar,
            width=130,
            values=self._snap_values(),
            command=self._on_snap_change,
        )
        self.snap_combo.pack(side="left", padx=4, pady=10)
        ctk.CTkLabel(ol_bar, text="Lọc DG Case:", font=FONT_BODY).pack(side="left", padx=(16, 6))
        ctk.CTkEntry(ol_bar, textvariable=self.filter_var, width=160).pack(side="left", padx=4, pady=10)
        self.filter_var.trace_add("write", lambda *_: self._render_ol())
        ctk.CTkButton(ol_bar, text="↻", width=36, command=self._refresh_all).pack(side="left", padx=8, pady=10)

        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True, padx=12, pady=8)
        split.grid_columnconfigure(0, weight=3)
        split.grid_columnconfigure(1, weight=2)
        split.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(split, fg_color=COLORS["card"], corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(left, text="Order List hiện tại", font=("Segoe UI", 14, "bold")).pack(
            anchor="w", padx=12, pady=8
        )
        self.ol_table = OlTableWidget(left)
        self.ol_table.pack(fill="both", expand=True, padx=8, pady=8)

        right = ctk.CTkFrame(split, fg_color=COLORS["card"], corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(right, text="Kế hoạch giao tem trong tuần", font=("Segoe UI", 14, "bold")).pack(
            anchor="w", padx=12, pady=8
        )

        wrow = ctk.CTkFrame(right, fg_color="transparent")
        wrow.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(wrow, text="Tuần (T2):", font=FONT_BODY).pack(side="left")
        self.week_var = ctk.StringVar(value=week_start_str(date.today()))
        weeks = self._week_options()
        self.week_combo = ctk.CTkComboBox(
            wrow,
            width=140,
            values=weeks,
            variable=self.week_var,
            command=lambda _: self._reload_plans(),
        )
        self.week_combo.pack(side="left", padx=8)

        prow = ctk.CTkFrame(right, fg_color="transparent")
        prow.pack(fill="x", padx=12, pady=6)
        ctk.CTkButton(prow, text="+ Thêm từ OL", width=120, command=self._add_plan_dialog).pack(side="left")
        ctk.CTkButton(prow, text="+ Thêm tay", width=100, command=self._add_manual_plan).pack(side="left", padx=6)
        ctk.CTkButton(prow, text="Hoàn thành", width=100, command=lambda: self._set_plan_status("done")).pack(
            side="left", padx=4
        )
        ctk.CTkButton(prow, text="Xóa", width=70, command=self._delete_plan).pack(side="left", padx=4)

        self.plan_list = ctk.CTkTextbox(right, font=("Consolas", 11))
        self.plan_list.pack(fill="both", expand=True, padx=12, pady=8)
        self.plan_list.bind("<Button-1>", self._on_plan_click)
        self._plan_rows: list[dict] = []
        self._selected_plan_id: int | None = None

        self._reload_plans()

    def _week_options(self) -> list[str]:
        today = date.today()
        opts = []
        for delta in range(-2, 6):
            d = today + timedelta(weeks=delta)
            opts.append(week_start_str(d))
        return opts

    def _snap_values(self) -> list[str]:
        dates = self.state.db.list_snapshot_dates()
        return dates if dates else ["(chưa có)"]

    def _load_initial_ol(self) -> None:
        today = date.today().strftime("%Y-%m-%d")
        if today in self.state.db.list_snapshot_dates():
            self.state.load_snapshot_into_state(today)
            self.snap_combo.set(today)
        self._on_state_changed()

    def _on_state_changed(self) -> None:
        self.ol_info.configure(text=self.state.ol_status)
        self._render_ol()
        vals = self._snap_values()
        self.snap_combo.configure(values=vals)

    def _refresh_all(self) -> None:
        snap = self.snap_combo.get()
        if snap and not snap.startswith("("):
            self.state.load_snapshot_into_state(snap)
        self._reload_plans()

    def _on_snap_change(self, choice: str) -> None:
        if choice and not choice.startswith("("):
            self.state.load_snapshot_into_state(choice)

    def _render_ol(self) -> None:
        df = self.state.ol_df
        if df is not None and not df.empty:
            text = self.filter_var.get().strip()
            if text:
                df = self.ol_service.find_by_dg_case(df, text)
        self.ol_table.render(df)

    def _reload_plans(self) -> None:
        ws = self.week_var.get()
        self._plan_rows = self.state.db.list_weekly_plans(ws)
        lines = []
        for p in self._plan_rows:
            st = p.get("status", "pending")
            icon = "✓" if st == "done" else "○"
            lines.append(
                f"{icon} [{p['id']}] {p.get('planned_date') or '—'} | "
                f"{p.get('dg_case') or '—'} | {p.get('customer') or '—'}\n"
                f"    {p.get('production_name') or ''} {('— ' + p['notes']) if p.get('notes') else ''}"
            )
        self.plan_list.delete("1.0", "end")
        self.plan_list.insert("1.0", "\n\n".join(lines) if lines else "(Chưa có kế hoạch tuần này)")
        self._selected_plan_id = None

    def _on_plan_click(self, _event=None) -> None:
        try:
            idx = self.plan_list.index("@insert linestart")
            line = self.plan_list.get(f"{idx} linestart", f"{idx} lineend")
        except Exception:
            return
        if "[" in line and "]" in line:
            try:
                pid = int(line.split("[")[1].split("]")[0])
                self._selected_plan_id = pid
            except ValueError:
                pass

    def _add_plan_dialog(self) -> None:
        dg = simpledialog.askstring("Kế hoạch", "DG Case (để trống = thêm tay sau):")
        if dg is None:
            return
        df = self.state.ol_df
        if dg.strip() and df is not None:
            sub = self.ol_service.find_by_dg_case(df, dg)
            if not sub.empty:
                row = sub.iloc[0]
                self._insert_plan_from_row(row)
                return
        self._insert_plan_manual(dg_case=normalize_dg_case(dg) if dg else "")

    def _add_manual_plan(self) -> None:
        self._insert_plan_manual()

    def _insert_plan_from_row(self, row: pd.Series) -> None:
        planned = simpledialog.askstring("Ngày giao tem", "dd-mm-yyyy:", initialvalue="") or ""
        notes = simpledialog.askstring("Ghi chú", "") or ""
        self.state.db.add_weekly_plan(
            self.week_var.get(),
            dg_case=normalize_text(row.get("dg_case")),
            order_no=normalize_text(row.get("order_no")),
            customer=normalize_text(row.get("customer")),
            production_name=normalize_text(row.get("production_name")),
            planned_date=planned,
            notes=notes,
            created_by=self.state.user.id,
        )
        self._reload_plans()

    def _insert_plan_manual(self, dg_case: str = "") -> None:
        dg = dg_case or simpledialog.askstring("DG Case", "") or ""
        cust = simpledialog.askstring("Khách", "") or ""
        planned = simpledialog.askstring("Ngày giao", "") or ""
        notes = simpledialog.askstring("Ghi chú", "") or ""
        self.state.db.add_weekly_plan(
            self.week_var.get(),
            dg_case=dg,
            customer=cust,
            planned_date=planned,
            notes=notes,
            created_by=self.state.user.id,
        )
        self._reload_plans()

    def _set_plan_status(self, status: str) -> None:
        if self._selected_plan_id is None:
            messagebox.showinfo("Planning", "Click dòng kế hoạch (có [id]) để chọn trước.")
            return
        self.state.db.update_weekly_plan_status(self._selected_plan_id, status)
        self._reload_plans()

    def _delete_plan(self) -> None:
        if self._selected_plan_id is None:
            messagebox.showinfo("Planning", "Chọn kế hoạch trước (click dòng có [id]).")
            return
        if messagebox.askyesno("Xác nhận", "Xóa kế hoạch đã chọn?"):
            self.state.db.delete_weekly_plan(self._selected_plan_id)
            self._reload_plans()
