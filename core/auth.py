"""Xác thực người dùng — tài khoản chỉ thêm qua database."""

from __future__ import annotations

from core.database import HubDatabase
from core.utils import verify_password


class AuthService:
    def __init__(self, db: HubDatabase | None = None):
        self.db = db or HubDatabase()

    def authenticate(self, username: str, password: str) -> dict | None:
        user = self.db.get_user_by_username(username.strip())
        if not user:
            return None
        if not int(user["is_active"]):
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        return user

    def update_display_name(self, user_id: int, display_name: str) -> None:
        self.db.update_user_display_name(user_id, display_name.strip())
