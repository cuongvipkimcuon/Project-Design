"""
DG Hub — Đề xuất in tem (CustomTkinter).

Đăng nhập → Setup | Sales | Design
"""

from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.app_state import AppState
from core.auth import AuthService
from core.permissions import role_label
from ui.design_panel import DesignPanel
from ui.login_window import LoginWindow
from ui.sales_panel import SalesPanel
from ui.setup_panel import SetupPanel
from ui.theme import APP_TITLE, APPEARANCE, COLOR_THEME, COLORS, FONT_SMALL, FONT_TITLE


class DgHubApp(ctk.CTk):
    def __init__(self, state: AppState, auth: AuthService):
        super().__init__()
        ctk.set_appearance_mode(APPEARANCE)
        ctk.set_default_color_theme(COLOR_THEME)

        self.app_state = state
        self.auth = auth
        self.title(APP_TITLE)
        self.geometry("1320x800")
        self.minsize(1050, 660)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_content()

    def _build_sidebar(self) -> None:
        side = ctk.CTkFrame(self, width=280, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_rowconfigure(10, weight=1)

        ctk.CTkLabel(side, text="DG Hub", font=FONT_TITLE).pack(padx=20, pady=(24, 2), anchor="w")
        ctk.CTkLabel(
            side,
            text=self.app_state.user.display_name,
            font=("Segoe UI", 13),
            text_color=COLORS["accent"][1],
        ).pack(padx=20, anchor="w")
        ctk.CTkLabel(
            side,
            text=f"@{self.app_state.user.username} · {role_label(self.app_state.user.role)}",
            font=FONT_SMALL,
            text_color=COLORS["muted"],
        ).pack(padx=20, pady=(0, 20), anchor="w")

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in [
            ("setup", "Setup"),
            ("sales", "Sales"),
            ("design", "Design"),
        ]:
            btn = ctk.CTkButton(
                side,
                text=label,
                anchor="w",
                height=42,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray30"),
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=14, pady=4)
            self.nav_buttons[key] = btn

        ctk.CTkButton(
            side,
            text="Đăng xuất",
            fg_color="transparent",
            border_width=1,
            height=36,
            command=self._logout,
        ).pack(side="bottom", fill="x", padx=16, pady=20)

    def _build_content(self) -> None:
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.pages: dict[str, ctk.CTkFrame] = {}
        self.pages["setup"] = SetupPanel(self.content, self.app_state, self.auth)
        self.pages["sales"] = SalesPanel(self.content)
        self.pages["design"] = DesignPanel(self.content, self.app_state)

        self._show_page("design")

    def _show_page(self, key: str) -> None:
        for page in self.pages.values():
            page.grid_forget()
        self.pages[key].grid(row=0, column=0, sticky="nsew")
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color=COLORS["accent"] if k == key else "transparent")

    def _logout(self) -> None:
        self.destroy()
        run_app()


def run_app() -> None:
    session: list[tuple[AppState, AuthService] | None] = [None]

    def on_login_ok(state: AppState, auth: AuthService) -> None:
        session[0] = (state, auth)
        login.quit()

    login = LoginWindow(on_success=on_login_ok)
    login.mainloop()

    if session[0] is None:
        login.destroy()
        return

    login.destroy()
    state, auth = session[0]
    state.load_active_ol_into_state()
    state.load_bom_ke_into_state()
    app = DgHubApp(state, auth)
    app.mainloop()


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
