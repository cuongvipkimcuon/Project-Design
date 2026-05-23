"""Cửa sổ đăng nhập / đăng ký."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk
from tkinter import messagebox

from core.app_state import AppState, SessionUser
from core.auth import AuthService
from core.user_db import create_user_database
from core.supabase_config import supabase_enabled
from ui.theme import APP_NAME, APP_VERSION, APPEARANCE, COLOR_THEME, COLORS, FONT_BODY, FONT_TITLE


class LoginWindow(ctk.CTk):
    def __init__(self, on_success: Callable[[AppState, AuthService], None]):
        super().__init__()
        ctk.set_appearance_mode(APPEARANCE)
        ctk.set_default_color_theme(COLOR_THEME)

        self.on_success = on_success
        self.auth = AuthService()
        self.db = None  # legacy count only
        self._mode = "login"

        self.title(f"{APP_NAME} — Đăng nhập")
        self.geometry("420x500")
        self.minsize(420, 500)
        self.resizable(False, False)

        self.frame = ctk.CTkFrame(self, corner_radius=12)
        self.frame.pack(fill="both", expand=True, padx=32, pady=32)

        self._build_form()

    def _build_form(self) -> None:
        for w in self.frame.winfo_children():
            w.destroy()

        ctk.CTkLabel(self.frame, text=APP_NAME, font=FONT_TITLE).pack(pady=(8, 4))
        ctk.CTkLabel(
            self.frame,
            text=f"Version {APP_VERSION}",
            font=FONT_BODY,
            text_color=COLORS["muted"],
        ).pack(pady=(0, 16))

        mode_text = "Đăng nhập" if self._mode == "login" else "Đăng ký tài khoản"
        self.mode_label = ctk.CTkLabel(self.frame, text=mode_text, font=("Segoe UI", 14, "bold"))
        self.mode_label.pack(pady=(0, 12))

        ctk.CTkLabel(self.frame, text="Username", anchor="w").pack(fill="x", padx=8)
        self.user_entry = ctk.CTkEntry(self.frame, width=300, placeholder_text="Tên đăng nhập")
        self.user_entry.pack(pady=(4, 8), padx=8)

        if self._mode == "register":
            ctk.CTkLabel(self.frame, text="Tên hiển thị", anchor="w").pack(fill="x", padx=8)
            self.display_entry = ctk.CTkEntry(self.frame, width=300, placeholder_text="Tên hiển thị")
            self.display_entry.pack(pady=(4, 8), padx=8)
        else:
            self.display_entry = None

        ctk.CTkLabel(self.frame, text="Password", anchor="w").pack(fill="x", padx=8)
        self.pass_entry = ctk.CTkEntry(self.frame, width=300, show="•", placeholder_text="Mật khẩu")
        self.pass_entry.pack(pady=(4, 12), padx=8)

        if self._mode == "register":
            ctk.CTkLabel(self.frame, text="Nhập lại password", anchor="w").pack(fill="x", padx=8)
            self.pass2_entry = ctk.CTkEntry(self.frame, width=300, show="•", placeholder_text="Nhập lại")
            self.pass2_entry.pack(pady=(4, 12), padx=8)
        else:
            self.pass2_entry = None

        self.error_label = ctk.CTkLabel(self.frame, text="", text_color="#e57373", font=FONT_BODY)
        self.error_label.pack(pady=(0, 8))

        action = "Đăng nhập" if self._mode == "login" else "Đăng ký"
        ctk.CTkButton(
            self.frame,
            text=action,
            width=200,
            height=40,
            command=self._submit,
        ).pack(pady=6)

        toggle = "Chưa có tài khoản? Đăng ký" if self._mode == "login" else "Đã có tài khoản? Đăng nhập"
        ctk.CTkButton(
            self.frame,
            text=toggle,
            width=220,
            height=32,
            fg_color="transparent",
            command=self._toggle_mode,
        ).pack(pady=4)

        self.pass_entry.bind("<Return>", lambda e: self._submit())
        self.user_entry.bind("<Return>", lambda e: self.pass_entry.focus())

        from core.database import HubDatabase

        if HubDatabase().count_users() == 0 and not supabase_enabled():
            self.error_label.configure(
                text="Chưa có user — dùng Đăng ký hoặc tools/add_user.py",
                text_color=COLORS["warning"][1],
            )

    def _toggle_mode(self) -> None:
        self._mode = "register" if self._mode == "login" else "login"
        self.geometry("420x580" if self._mode == "register" else "420x500")
        self._build_form()

    def _submit(self) -> None:
        username = self.user_entry.get().strip().lower()
        password = self.pass_entry.get()
        if not username or not password:
            self.error_label.configure(text="Nhập username và password.")
            return

        if self._mode == "register":
            self._do_register(username, password)
        else:
            self._login(username, password)

    def _do_register(self, username: str, password: str) -> None:
        if self.pass2_entry and password != self.pass2_entry.get():
            self.error_label.configure(text="Password không khớp.")
            return
        display = ""
        if self.display_entry:
            display = self.display_entry.get().strip() or username
        try:
            user = self.auth.register(username, password, display)
        except Exception as exc:
            self.error_label.configure(text=str(exc))
            return
        messagebox.showinfo(
            "Đăng ký",
            "Đăng ký thành công.\n"
            "Không cần xác nhận email — tài khoản chờ admin duyệt trong Setup → Phân quyền.",
            parent=self,
        )
        self._mode = "login"
        self.geometry("420x500")
        self._build_form()
        self.user_entry.insert(0, username)

    def _login(self, username: str, password: str) -> None:
        try:
            user = self.auth.authenticate(username, password)
        except ValueError as exc:
            self.error_label.configure(text=str(exc))
            return
        if not user:
            self.error_label.configure(text="Sai tên đăng nhập hoặc mật khẩu.")
            return

        session = SessionUser(
            id=str(user["id"]),
            username=str(user["username"]),
            display_name=str(user["display_name"] or user["username"]),
            role=str(user.get("role", "design")),
        )
        access, refresh = self.auth.get_supabase_tokens()
        try:
            db = create_user_database(session.id, access_token=access, refresh_token=refresh)
        except Exception as exc:
            self.error_label.configure(text=f"Lỗi khởi tạo DB: {exc}")
            return
        state = AppState(user=session, db=db)
        self.on_success(state, self.auth)
