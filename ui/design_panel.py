"""Design — tab con: Planning, Plastic Label, Pictogram, Supplier."""

from __future__ import annotations

import customtkinter as ctk

from core.app_state import AppState
from core.npl_stock_service import MODULE_PICTOGRAM, MODULE_PLASTIC_LABEL
from core.permissions import MOD_DESIGN_PICTOGRAM, MOD_DESIGN_PLASTIC, MOD_DESIGN_SUPPLIER
from ui.npl_stock_panel import NplStockPanel
from ui.planning_panel import PlanningPanel
from ui.supplier_panel import SupplierPanel
from ui.theme import COLORS, FONT_TITLE


class DesignPanel(ctk.CTkFrame):
    def __init__(self, master, state: AppState, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_box, text="Design", font=FONT_TITLE).pack(side="left", padx=8)

        tabs = ctk.CTkFrame(header, fg_color="transparent")
        tabs.grid(row=0, column=1)
        self.sub_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in [
            ("planning", "Plan"),
            ("supplier", "Supplier"),
            ("plastic_label", "Plastic Label"),
            ("pictogram", "Pictogram"),
        ]:
            btn = ctk.CTkButton(
                tabs,
                text=label,
                width=130,
                height=32,
                fg_color="transparent",
                command=lambda k=key: self._show_sub(k),
            )
            btn.pack(side="left", padx=4)
            self.sub_buttons[key] = btn

        self.sub_content = ctk.CTkFrame(self, fg_color="transparent")
        self.sub_content.grid(row=1, column=0, sticky="nsew")
        self.sub_content.grid_columnconfigure(0, weight=1)
        self.sub_content.grid_rowconfigure(0, weight=1)

        self.supplier_panel = SupplierPanel(self.sub_content, state)
        open_slip = self._open_supplier_slip
        self.sub_pages: dict[str, ctk.CTkFrame] = {
            "planning": PlanningPanel(self.sub_content, state),
            "supplier": self.supplier_panel,
            "plastic_label": NplStockPanel(
                self.sub_content,
                state,
                module=MODULE_PLASTIC_LABEL,
                perm_module=MOD_DESIGN_PLASTIC,
                on_open_slip=open_slip,
            ),
            "pictogram": NplStockPanel(
                self.sub_content,
                state,
                module=MODULE_PICTOGRAM,
                perm_module=MOD_DESIGN_PICTOGRAM,
                on_open_slip=open_slip,
            ),
        }
        self._show_sub("planning")

    def _open_supplier_slip(self, slip_id: int) -> None:
        self._show_sub("supplier")
        self.supplier_panel.open_slip(int(slip_id))

    def _show_sub(self, key: str) -> None:
        for page in self.sub_pages.values():
            page.grid_forget()
        self.sub_pages[key].grid(row=0, column=0, sticky="nsew")
        for k, btn in self.sub_buttons.items():
            btn.configure(fg_color=COLORS["accent"] if k == key else "transparent")
