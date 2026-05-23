"""Setup — tab con: Tài khoản | Phân Quyền."""

from __future__ import annotations

import customtkinter as ctk

from core.app_state import AppState
from core.auth import AuthService
from core.permissions import MOD_SETUP_PERMISSIONS, can_access
from ui.setup.account_panel import SetupAccountPanel
from ui.setup.data_status_panel import SetupDataStatusPanel
from ui.setup.permissions_panel import SetupPermissionsPanel
from ui.theme import COLORS, FONT_TITLE


class SetupPanel(ctk.CTkFrame):
    def __init__(self, master, state: AppState, auth: AuthService | None = None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.state = state
        self.auth = auth or AuthService(state.db)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)
        header.grid_columnconfigure(2, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_box, text="Setup", font=FONT_TITLE).pack(side="left", padx=8)

        tabs = ctk.CTkFrame(header, fg_color="transparent")
        tabs.grid(row=0, column=1)
        self.sub_buttons: dict[str, ctk.CTkButton] = {}
        sub_defs = [("account", "Tài khoản"), ("data_status", "Trạng thái dữ liệu")]
        if can_access(state.user.role, MOD_SETUP_PERMISSIONS):
            sub_defs.append(("permissions", "Phân Quyền"))

        for key, label in sub_defs:
            btn = ctk.CTkButton(
                tabs,
                text=label,
                width=140 if key == "data_status" else 120,
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

        self.sub_pages: dict[str, ctk.CTkFrame] = {
            "account": SetupAccountPanel(self.sub_content, state, self.auth),
            "data_status": SetupDataStatusPanel(self.sub_content, state, self.auth),
        }
        if can_access(state.user.role, MOD_SETUP_PERMISSIONS):
            self.sub_pages["permissions"] = SetupPermissionsPanel(
                self.sub_content, state, self.auth
            )

        self._show_sub("account")

    def _show_sub(self, key: str) -> None:
        for page in self.sub_pages.values():
            page.grid_forget()
        self.sub_pages[key].grid(row=0, column=0, sticky="nsew")
        for k, btn in self.sub_buttons.items():
            btn.configure(fg_color=COLORS["accent"] if k == key else "transparent")
