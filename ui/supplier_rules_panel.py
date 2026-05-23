"""Supplier → tab Quy tắc Detail."""

from __future__ import annotations

import threading
from tkinter import messagebox

import customtkinter as ctk

from core.app_state import AppState
from core.permissions import MOD_DESIGN_SUPPLIER
from core.shared_dataset_service import SharedDatasetService
from core.supplier_detail_rules import (
    DEFAULT_PICTO_SIZE_CM,
    DEFAULT_RULES_DOC,
    RULE_EMG_SERIAL,
    RULE_FIXED,
    RULE_PICTOGRAM,
    RULE_SCOPE_LOCAL,
    RULE_SCOPE_TEAM,
    delete_rule,
    format_rule_conditions,
    load_detail_rules,
    new_rule,
    rule_scope,
    upsert_rule,
)
from core.utils import normalize_text
from ui.dialog_utils import configure_dialog, show_dialog
from ui.table_pager import TablePager, TablePagerBar
from ui.theme import COLORS, FONT_BODY, FONT_SMALL

RULE_TYPE_LABELS = {
    RULE_FIXED: "Text cố định / mẫu",
    RULE_EMG_SERIAL: "Serial EMG (705)",
    RULE_PICTOGRAM: "Pictogram (720)",
}


class SupplierRulesPanel(ctk.CTkFrame):
    def __init__(self, master, state: AppState, *, is_admin: bool = False, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self._is_admin = is_admin
        self._can_write = state.user.can_write(MOD_DESIGN_SUPPLIER)
        self.shared = SharedDatasetService(state.db)
        self._rules: list[dict] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self._build()

    def _build(self) -> None:
        ctk.CTkLabel(
            self,
            text="Quy tắc autofill cột Detail",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 4))

        hint = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=8)
        hint.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        scope_hint = (
            "Admin: quy tắc [Team] lưu cloud — user đồng bộ từ Setup. "
            "User: thêm quy tắc [Local] chỉ trên máy mình."
            if self._is_admin
            else "Quy tắc [Team] từ admin (cloud). Bạn có thể thêm [Local] riêng — chỉ lưu máy này."
        )
        ctk.CTkLabel(
            hint,
            text=(
                f"{scope_hint}\n"
                "Prefix mã NPL + (tuỳ chọn) customer / production no / logo. Trường trống = không lọc.\n"
                "Không khớp quy tắc → mặc định 705/704/720."
            ),
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=920,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 8))

        defaults = ctk.CTkFrame(hint, fg_color="transparent")
        defaults.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(defaults, text="Mặc định (built-in):", font=FONT_BODY).pack(anchor="w")
        for item in DEFAULT_RULES_DOC:
            ctk.CTkLabel(
                defaults,
                text=f"• {item['prefix']} — {item['type']}: {item['detail']}",
                font=FONT_SMALL,
                text_color=COLORS["muted"],
                anchor="w",
            ).pack(anchor="w", padx=8)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 4))
        ctk.CTkLabel(toolbar, text="Quy tắc tùy chỉnh", font=FONT_BODY).pack(side="left")
        btn_state = "normal" if self._can_write else "disabled"
        add_label = "+ Quy tắc Team" if self._is_admin else "+ Quy tắc Local"
        ctk.CTkButton(
            toolbar,
            text=add_label,
            fg_color=COLORS["accent"][1],
            command=self._add_rule,
            state=btn_state,
        ).pack(side="right", padx=4)
        ctk.CTkButton(toolbar, text="Refresh", command=self._reload).pack(side="right", padx=4)

        self._rules: list[dict] = []
        self._pager = TablePager()
        self._pager_bar = TablePagerBar(
            self,
            self._pager,
            on_change=self._render_rules_page,
            placeholder="Lọc prefix, tên, detail…",
        )
        self._pager_bar.set_filter_handler(self._rule_quick_filter)
        self._pager_bar.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 4))

        self.list_wrap = ctk.CTkScrollableFrame(self, fg_color=COLORS["card"], corner_radius=10)
        self.list_wrap.grid(row=4, column=0, sticky="nsew", padx=12, pady=8)
        self.grid_rowconfigure(4, weight=1)

        self._reload()

    @staticmethod
    def _rule_quick_filter(rule: dict, query: str) -> bool:
        blob = " ".join(
            [
                normalize_text(rule.get("material_prefix")),
                normalize_text(rule.get("name")),
                normalize_text(rule.get("detail_text")),
                normalize_text(rule.get("rule_type")),
                format_rule_conditions(rule),
            ]
        ).lower()
        return query in blob

    def _reload(self) -> None:
        self._rules = load_detail_rules(self.state.db)
        self._pager.set_items(self._rules, filter_fn=self._rule_quick_filter, reset_page=True)
        self._render_rules_page()

    def _render_rules_page(self) -> None:
        for w in self.list_wrap.winfo_children():
            w.destroy()
        page_items = self._pager.page_items()
        self._pager_bar.refresh_info()
        if not page_items and not self._rules:
            ctk.CTkLabel(
                self.list_wrap,
                text="Chưa có quy tắc — admin thêm Team (cloud) hoặc user thêm Local.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(pady=24)
            return
        if not page_items:
            ctk.CTkLabel(
                self.list_wrap,
                text="Không khớp bộ lọc.",
                text_color=COLORS["muted"],
                font=FONT_SMALL,
            ).pack(pady=24)
            return

        head = ctk.CTkFrame(self.list_wrap, fg_color=("gray88", "gray28"))
        head.pack(fill="x", padx=8, pady=(8, 4))
        for i, (title, w) in enumerate(
            [
                ("Nguồn", 56),
                ("Prefix", 64),
                ("Tên", 100),
                ("Điều kiện", 140),
                ("Loại", 90),
                ("Detail", 180),
                ("", 96),
            ]
        ):
            head.grid_columnconfigure(i, weight=1 if title == "Detail" else 0)
            ctk.CTkLabel(
                head,
                text=title,
                width=w,
                anchor="w",
                font=("Segoe UI", 11, "bold"),
            ).grid(row=0, column=i, sticky="ew", padx=6, pady=8)

        for idx, rule in enumerate(page_items):
            self._render_rule_row(rule, idx)

    def _can_edit_rule(self, rule: dict) -> bool:
        if not self._can_write:
            return False
        if rule_scope(rule) == RULE_SCOPE_TEAM:
            return self._is_admin
        return True

    def _render_rule_row(self, rule: dict, idx: int) -> None:
        bg = ("gray95", "gray26") if idx % 2 == 0 else ("gray90", "gray22")
        row = ctk.CTkFrame(self.list_wrap, fg_color=bg, corner_radius=6)
        row.pack(fill="x", padx=8, pady=2)
        enabled = rule.get("enabled", True)
        scope = "Team" if rule_scope(rule) == RULE_SCOPE_TEAM else "Local"
        prefix = normalize_text(rule.get("material_prefix"))
        name = normalize_text(rule.get("name"))
        rtype = RULE_TYPE_LABELS.get(normalize_text(rule.get("rule_type")), "?")
        detail = normalize_text(rule.get("detail_text"))
        if normalize_text(rule.get("rule_type")) == RULE_PICTOGRAM and not detail:
            detail = "Pictogram size {size} ({cm}cm)"
        conditions = format_rule_conditions(rule) or "—"

        cells = [
            scope,
            prefix,
            name + ("" if enabled else " (tắt)"),
            conditions,
            rtype,
            detail[:50] + ("…" if len(detail) > 50 else ""),
        ]
        for i, text in enumerate(cells):
            row.grid_columnconfigure(i, weight=1 if i == 5 else 0)
            ctk.CTkLabel(row, text=text, anchor="w", font=FONT_SMALL).grid(
                row=0, column=i, sticky="ew", padx=6, pady=8
            )

        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.grid(row=0, column=6, sticky="e", padx=4)
        can_edit = self._can_edit_rule(rule)
        ctk.CTkButton(
            btns,
            text="Sửa",
            width=44,
            height=26,
            command=lambda r=rule: self._edit_rule(r),
            state="normal" if can_edit else "disabled",
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            btns,
            text="Xóa",
            width=44,
            height=26,
            fg_color="transparent",
            border_width=1,
            command=lambda r=rule: self._delete_rule(r),
            state="normal" if can_edit else "disabled",
        ).pack(side="left", padx=2)

    def _default_scope(self) -> str:
        return RULE_SCOPE_TEAM if self._is_admin else RULE_SCOPE_LOCAL

    def _add_rule(self) -> None:
        RuleEditorDialog(
            self.winfo_toplevel(),
            state=self.state,
            scope=self._default_scope(),
            is_admin=self._is_admin,
            on_saved=self._on_rules_saved,
        )

    def _edit_rule(self, rule: dict) -> None:
        if not self._can_edit_rule(rule):
            return
        RuleEditorDialog(
            self.winfo_toplevel(),
            state=self.state,
            rule=rule,
            scope=rule_scope(rule),
            is_admin=self._is_admin,
            on_saved=self._on_rules_saved,
        )

    def _delete_rule(self, rule: dict) -> None:
        if not self._can_edit_rule(rule):
            return
        if not messagebox.askyesno(
            "Xóa quy tắc",
            f"Xóa quy tắc «{rule.get('name')}» ({rule_scope(rule)})?",
            parent=self.winfo_toplevel(),
        ):
            return
        delete_rule(self.state.db, str(rule.get("id")), scope=rule_scope(rule))
        if rule_scope(rule) == RULE_SCOPE_TEAM and self._is_admin:
            self._publish_team_rules_async()
        self._reload()

    def _on_rules_saved(self, scope: str) -> None:
        self._reload()
        if scope == RULE_SCOPE_TEAM and self._is_admin:
            self._publish_team_rules_async()

    def _publish_team_rules_async(self) -> None:
        if not self._is_admin or not self.shared.cloud_enabled:
            return
        name = self.state.user.display_name or self.state.user.username

        def worker() -> None:
            try:
                msg = self.shared.publish_detail_rules(publisher_name=name)
                print(f"[SupplierRules] {msg}")
            except Exception as exc:
                print(f"[SupplierRules] publish team rules: {exc}")

        threading.Thread(target=worker, daemon=True).start()


class RuleEditorDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        *,
        state: AppState,
        rule: dict | None = None,
        scope: str = RULE_SCOPE_LOCAL,
        is_admin: bool = False,
        on_saved,
    ) -> None:
        super().__init__(master)
        self.state = state
        self.scope = scope if scope in (RULE_SCOPE_TEAM, RULE_SCOPE_LOCAL) else RULE_SCOPE_LOCAL
        self.is_admin = is_admin
        self.rule = dict(rule) if rule else new_rule(scope=self.scope)
        self.on_saved = on_saved

        title_scope = "Team" if self.scope == RULE_SCOPE_TEAM else "Local"
        self.title(f"{'Sửa' if rule else 'Thêm'} quy tắc Detail [{title_scope}]")
        top = master.winfo_toplevel() if hasattr(master, "winfo_toplevel") else master
        configure_dialog(self, width=580, height=620, min_width=500, min_height=500, parent=top)
        self.transient(top)
        self.grab_set()

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=12)

        self.name_var = ctk.StringVar(value=normalize_text(self.rule.get("name")))
        self.prefix_var = ctk.StringVar(value=normalize_text(self.rule.get("material_prefix")))
        self.type_var = ctk.StringVar(
            value=normalize_text(self.rule.get("rule_type")) or RULE_FIXED
        )
        self.detail_var = ctk.StringVar(value=normalize_text(self.rule.get("detail_text")))
        self.customer_filter_var = ctk.StringVar(value=normalize_text(self.rule.get("customer_filter")))
        self.production_filter_var = ctk.StringVar(
            value=normalize_text(self.rule.get("production_no_filter"))
        )
        self.logo_filter_var = ctk.StringVar(value=normalize_text(self.rule.get("logo_filter")))
        self.enabled_var = ctk.BooleanVar(value=bool(self.rule.get("enabled", True)))

        sizes = self.rule.get("pictogram_sizes") or DEFAULT_PICTO_SIZE_CM
        if not isinstance(sizes, dict):
            sizes = DEFAULT_PICTO_SIZE_CM
        self.size_vars = {
            k: ctk.StringVar(value=str(sizes.get(k, DEFAULT_PICTO_SIZE_CM.get(k, ""))))
            for k in ("S", "M", "L")
        }

        for label, var in [
            ("Tên quy tắc", self.name_var),
            ("Prefix mã NPL (bắt đầu bằng)", self.prefix_var),
        ]:
            ctk.CTkLabel(body, text=label, anchor="w", font=FONT_SMALL).pack(fill="x", pady=(8, 2))
            ctk.CTkEntry(body, textvariable=var, height=34).pack(fill="x")

        cond = ctk.CTkFrame(body, fg_color=COLORS["card"], corner_radius=8)
        cond.pack(fill="x", pady=(10, 4))
        ctk.CTkLabel(
            cond,
            text="Điều kiện — trường trống = không lọc",
            font=FONT_BODY,
            anchor="w",
        ).pack(anchor="w", padx=12, pady=(10, 6))
        ctk.CTkLabel(cond, text="Customer — tên KH như OL cột F", anchor="w", font=FONT_SMALL).pack(
            fill="x", padx=12, pady=(0, 2)
        )
        ctk.CTkEntry(
            cond,
            textvariable=self.customer_filter_var,
            placeholder_text="VD: EMG, Stanley Black & Decker",
            height=34,
        ).pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(cond, text="Production no / mã SP (OL cột H)", anchor="w", font=FONT_SMALL).pack(
            fill="x", padx=12, pady=(0, 2)
        )
        ctk.CTkEntry(
            cond,
            textvariable=self.production_filter_var,
            placeholder_text="VD: C-176, C-35200",
            height=34,
        ).pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(cond, text="Logo (OL cột J)", anchor="w", font=FONT_SMALL).pack(
            fill="x", padx=12, pady=(0, 2)
        )
        ctk.CTkEntry(
            cond,
            textvariable=self.logo_filter_var,
            placeholder_text="VD: Nike, Adidas",
            height=34,
        ).pack(fill="x", padx=12, pady=(0, 12))

        ctk.CTkLabel(body, text="Loại quy tắc", anchor="w", font=FONT_SMALL).pack(
            fill="x", pady=(8, 2)
        )
        ctk.CTkOptionMenu(
            body,
            variable=self.type_var,
            values=[RULE_FIXED, RULE_EMG_SERIAL, RULE_PICTOGRAM],
            command=self._on_type_change,
        ).pack(fill="x")

        ctk.CTkLabel(body, text="Detail / mẫu", anchor="w", font=FONT_SMALL).pack(
            fill="x", pady=(8, 2)
        )
        ctk.CTkEntry(body, textvariable=self.detail_var, height=34).pack(fill="x")
        self.detail_hint = ctk.CTkLabel(
            body,
            text="",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
            wraplength=500,
            justify="left",
        )
        self.detail_hint.pack(anchor="w", pady=4)

        self.size_frame = ctk.CTkFrame(body, fg_color="transparent")
        self.size_frame.pack(fill="x", pady=4)
        ctk.CTkLabel(self.size_frame, text="Pictogram cm:", font=FONT_SMALL).pack(side="left")
        for key in ("S", "M", "L"):
            ctk.CTkLabel(self.size_frame, text=key, font=FONT_SMALL).pack(side="left", padx=(8, 2))
            ctk.CTkEntry(self.size_frame, textvariable=self.size_vars[key], width=50, height=30).pack(
                side="left", padx=(0, 6)
            )

        ctk.CTkCheckBox(body, text="Bật quy tắc", variable=self.enabled_var).pack(
            anchor="w", pady=(12, 8)
        )

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkButton(foot, text="Hủy", fg_color="transparent", command=self.destroy).pack(
            side="right", padx=4
        )
        ctk.CTkButton(
            foot,
            text="Lưu",
            fg_color=COLORS["success"][1],
            command=self._save,
        ).pack(side="right")

        self._on_type_change(self.type_var.get())
        show_dialog(self, top)

    def _on_type_change(self, value: str) -> None:
        if value == RULE_FIXED:
            self.detail_hint.configure(
                text="VD: Check Poly or Satin · hoặc {customer} — {dg_case}"
            )
            self.size_frame.pack_forget()
        elif value == RULE_EMG_SERIAL:
            self.detail_hint.configure(
                text="Để trống = chỉ serial. Hoặc mẫu: Serial {serial} ({customer})"
            )
            self.size_frame.pack_forget()
        else:
            self.detail_hint.configure(
                text="Để trống = Pictogram size {size} ({cm}cm). Có thể sửa mẫu."
            )
            self.size_frame.pack(fill="x", pady=4)

    def _save(self) -> None:
        prefix = self.prefix_var.get().strip()
        if not prefix:
            messagebox.showwarning("Quy tắc", "Prefix mã NPL không được trống.", parent=self)
            return
        picto_sizes: dict[str, int] = {}
        for key, var in self.size_vars.items():
            try:
                picto_sizes[key] = int(var.get().strip())
            except ValueError:
                picto_sizes[key] = DEFAULT_PICTO_SIZE_CM[key]

        payload = {
            **self.rule,
            "name": self.name_var.get().strip() or "Quy tắc",
            "material_prefix": prefix,
            "customer_filter": self.customer_filter_var.get().strip(),
            "production_no_filter": self.production_filter_var.get().strip(),
            "logo_filter": self.logo_filter_var.get().strip(),
            "rule_type": self.type_var.get(),
            "detail_text": self.detail_var.get().strip(),
            "pictogram_sizes": picto_sizes,
            "enabled": self.enabled_var.get(),
            "scope": self.scope,
        }
        upsert_rule(self.state.db, payload, scope=self.scope)
        self.on_saved(self.scope)
        self.destroy()
