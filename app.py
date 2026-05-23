"""
DG House (CustomTkinter).

Đăng nhập → Setup | Sales | Design
"""

from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

from core.paths import ensure_app_cwd

ensure_app_cwd()

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.app_state import AppState
from core.auth import AuthService
from core.permissions import default_nav_page, role_label, visible_nav_pages
from core.shared_dataset_service import SharedDatasetService
from ui.design_panel import DesignPanel
from ui.login_window import LoginWindow
from ui.sales_panel import SalesPanel
from ui.setup_panel import SetupPanel
from ui.theme import APP_NAME, APP_TITLE, APPEARANCE, COLOR_THEME, COLORS, FONT_SMALL, FONT_TITLE


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

        ctk.CTkLabel(side, text=APP_NAME, font=FONT_TITLE).pack(padx=20, pady=(24, 2), anchor="w")
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
        for key, label in visible_nav_pages(self.app_state.user.role):
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
        role = self.app_state.user.role
        if role in ("admin", "design", "sales"):
            self.pages["setup"] = SetupPanel(self.content, self.app_state, self.auth)
        if role in ("admin", "sales"):
            self.pages["sales"] = SalesPanel(self.content)
        if role in ("admin", "design"):
            self.pages["design"] = DesignPanel(self.content, self.app_state)

        self._show_page(default_nav_page(role))

    def _show_page(self, key: str) -> None:
        for page in self.pages.values():
            page.grid_forget()
        self.pages[key].grid(row=0, column=0, sticky="nsew")
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color=COLORS["accent"] if k == key else "transparent")

    def _logout(self) -> None:
        self.destroy()
        run_app()

    def show_toast(self, message: str, *, duration_ms: int = 3500) -> None:
        from ui.toast import show_toast

        show_toast(self, message, duration_ms=duration_ms)

    def schedule_toast(self, message: str, *, duration_ms: int = 3500) -> None:
        from ui.toast import schedule_toast

        schedule_toast(self, message, duration_ms=duration_ms)


def _safe_destroy(window: ctk.CTk | None) -> None:
    if window is None:
        return
    try:
        if window.winfo_exists():
            window.destroy()
    except Exception:
        pass


def run_app() -> None:
    session: list[tuple[AppState, AuthService] | None] = [None]
    login_ref: list[LoginWindow | None] = [None]

    def on_login_ok(state: AppState, auth: AuthService) -> None:
        session[0] = (state, auth)
        _safe_destroy(login_ref[0])

    login = LoginWindow(on_success=on_login_ok)
    login_ref[0] = login
    login.mainloop()
    login_ref[0] = None

    if session[0] is None:
        return
    state, auth = session[0]
    state.load_active_ol_into_state()
    state.load_bom_ke_into_state()
    state.db._ops_notify_callback = state.notify  # noqa: SLF001

    app = DgHubApp(state, auth)
    app_holder: list[DgHubApp | None] = [app]

    def _ops_overwrite_prompt(result, retry_force) -> None:
        from tkinter import messagebox

        if messagebox.askyesno("Đồng bộ cloud", result.message, parent=app):
            retry_force()
        else:
            app.schedule_toast("Chưa đẩy — cloud có bản mới hơn")

    state.db._ops_overwrite_callback = _ops_overwrite_prompt  # noqa: SLF001
    state.db._ops_ui_scheduler = lambda fn: app.after(0, fn)  # noqa: SLF001

    def _sync_cloud(app_ref: list[DgHubApp | None]) -> None:
        try:
            result = SharedDatasetService(state.db).sync_all_team_data_if_needed()
            if result and result.ol_result:
                if app_ref[0]:
                    app_ref[0].after(0, lambda: state.set_ol_result(result.ol_result))
            if result and result.bom_result:
                if app_ref[0]:
                    app_ref[0].after(0, lambda: state.set_bom_ke_result(result.bom_result))
            if result:
                for msg in result.messages:
                    print(f"[DG Hub] {msg}")
                for err in result.errors:
                    print(f"[DG Hub] sync skip: {err}")
                if app_ref[0] and (result.ops_pulled or result.ops_pushed):
                    app_ref[0].after(0, state.notify)
                    if result.ops_pulled:
                        app_ref[0].schedule_toast("Đã cập nhật từ cloud")
        except Exception as exc:
            try:
                print(f"[DG Hub] sync cloud: {exc}")
            except UnicodeEncodeError:
                print(f"[DG Hub] sync cloud: {exc!r}")

    import threading
    from core.team_ops_sync import TeamOpsSyncResult, start_team_ops_polling

    def _on_ops_poll(result: TeamOpsSyncResult) -> None:
        if not result.pulled:
            return

        def _ui() -> None:
            state.notify()
            app.show_toast("Đã cập nhật từ cloud")

        app.after(0, _ui)

    threading.Thread(target=_sync_cloud, args=(app_holder,), daemon=True).start()
    start_team_ops_polling(state.db, on_pulled=_on_ops_poll)

    app.mainloop()


def main() -> None:
    run_app()


if __name__ == "__main__":
    main()
