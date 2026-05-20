"""Cửa sổ đăng nhập."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk
from tkinter import messagebox

from core.app_state import AppState, SessionUser
from core.auth import AuthService
from core.database import HubDatabase
from ui.theme import APPEARANCE, COLOR_THEME, COLORS, FONT_BODY, FONT_TITLE


class LoginWindow(ctk.CTk):
    def __init__(self, on_success: Callable[[AppState], None]):
        super().__init__()
        ctk.set_appearance_mode(APPEARANCE)
        ctk.set_default_color_theme(COLOR_THEME)

        self.on_success = on_success
        self.auth = AuthService()
        self.db = HubDatabase()

        self.title("DG Hub — Đăng nhập")
        self.geometry("420x380")
        self.resizable(False, False)

        frame = ctk.CTkFrame(self, corner_radius=12)
        frame.pack(fill="both", expand=True, padx=32, pady=32)

        ctk.CTkLabel(frame, text="DG Hub", font=FONT_TITLE).pack(pady=(8, 4))
        ctk.CTkLabel(
            frame,
            text="Đề xuất in tem",
            font=FONT_BODY,
            text_color=COLORS["muted"],
        ).pack(pady=(0, 24))

        ctk.CTkLabel(frame, text="Username", anchor="w").pack(fill="x", padx=8)
        self.user_entry = ctk.CTkEntry(frame, width=300, placeholder_text="Tên đăng nhập")
        self.user_entry.pack(pady=(4, 12), padx=8)

        ctk.CTkLabel(frame, text="Password", anchor="w").pack(fill="x", padx=8)
        self.pass_entry = ctk.CTkEntry(frame, width=300, show="•", placeholder_text="Mật khẩu")
        self.pass_entry.pack(pady=(4, 20), padx=8)

        self.error_label = ctk.CTkLabel(frame, text="", text_color="#e57373", font=FONT_BODY)
        self.error_label.pack(pady=(0, 8))

        ctk.CTkButton(
            frame,
            text="Đăng nhập",
            width=200,
            height=40,
            command=self._login,
        ).pack(pady=8)

        self.pass_entry.bind("<Return>", lambda e: self._login())
        self.user_entry.bind("<Return>", lambda e: self.pass_entry.focus())

        if self.db.count_users() == 0:
            self.error_label.configure(
                text="Chưa có user. Chạy: python tools/add_user.py",
                text_color=COLORS["warning"][1],
            )

    def _login(self) -> None:
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        if not username or not password:
            self.error_label.configure(text="Nhập username và password.")
            return

        user = self.auth.authenticate(username, password)
        if not user:
            self.error_label.configure(text="Sai tên đăng nhập hoặc mật khẩu.")
            return

        session = SessionUser(
            id=int(user["id"]),
            username=str(user["username"]),
            display_name=str(user["display_name"] or user["username"]),
        )
        state = AppState(user=session, db=self.db)
        self.on_success(state)
