"""Xác thực — Supabase Auth (ưu tiên) hoặc SQLite local."""

from __future__ import annotations

from typing import Any

from core.database import HubDatabase
from core.permissions import DEFAULT_ROLE, normalize_role
from core.supabase_service import APPROVAL_APPROVED, APPROVAL_PENDING, APPROVAL_REJECTED, SupabaseService
from core.utils import hash_password, verify_password


class AuthService:
    def __init__(self, db: HubDatabase | None = None):
        self.db = db or HubDatabase()
        self.supabase = SupabaseService()

    @property
    def uses_supabase(self) -> bool:
        return self.supabase.enabled

    def get_supabase_tokens(self) -> tuple[str | None, str | None]:
        if not self.uses_supabase:
            return None, None
        return self.supabase.access_token, self.supabase.refresh_token

    def register(self, username: str, password: str, display_name: str = "") -> dict[str, Any]:
        uname = username.strip().lower()
        if len(uname) < 2:
            raise ValueError("Username phải có ít nhất 2 ký tự.")
        if len(password) < 6:
            raise ValueError("Mật khẩu tối thiểu 6 ký tự.")
        if self.uses_supabase:
            existing = self.supabase.get_profile_by_username(uname)
            if existing:
                raise ValueError("Username đã tồn tại.")
            return self.supabase.sign_up(uname, password, display_name)
        if self.db.get_user_by_username(uname):
            raise ValueError("Username đã tồn tại.")
        uid = self.db.create_user(
            uname,
            password,
            display_name,
            role=DEFAULT_ROLE,
            approval_status=APPROVAL_PENDING,
            is_active=False,
        )
        user = self.db.get_user_by_id(uid)
        if not user:
            raise ValueError("Không tạo được user.")
        return self._map_local_user(user)

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        uname = username.strip().lower()
        if not uname or not password:
            return None
        if self.uses_supabase:
            try:
                return self.supabase.sign_in(uname, password)
            except ValueError:
                raise
            except Exception:
                return None
        user = self.db.get_user_by_username(uname)
        if not user:
            return None
        if not verify_password(password, user["password_hash"]):
            return None
        profile = self._map_local_user(user)
        try:
            self._ensure_can_login(profile)
        except ValueError:
            raise
        return profile

    def _ensure_can_login(self, profile: dict[str, Any]) -> None:
        status = str(profile.get("approval_status") or APPROVAL_APPROVED)
        if status == APPROVAL_PENDING:
            raise ValueError("Tài khoản chưa được admin duyệt.")
        if status == APPROVAL_REJECTED:
            raise ValueError("Tài khoản đã bị từ chối.")
        if not profile.get("is_active", True):
            raise ValueError("Tài khoản đã bị khóa.")

    def ensure_super_admin(
        self,
        username: str = "admin",
        password: str = "1",
        display_name: str = "Administrator",
    ) -> dict[str, Any]:
        uname = username.strip().lower()
        if self.uses_supabase:
            from core.bootstrap_admin import bootstrap_super_admin

            row = bootstrap_super_admin(uname, password, display_name)
            return {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "role": row["role"],
                "is_active": row["is_active"],
                "approval_status": row["approval_status"],
            }
        existing = self.db.get_user_by_username(uname)
        if existing:
            self.db.update_user_approval(
                int(existing["id"]),
                APPROVAL_APPROVED,
                is_active=True,
                role="admin",
            )
            return self._map_local_user(self.db.get_user_by_id(int(existing["id"])) or existing)
        uid = self.db.create_user(
            uname,
            password,
            display_name,
            role="admin",
            approval_status=APPROVAL_APPROVED,
            is_active=True,
        )
        user = self.db.get_user_by_id(uid)
        if not user:
            raise ValueError("Không tạo được super admin.")
        return self._map_local_user(user)

    def update_display_name(self, user_id: str | int, display_name: str) -> None:
        name = display_name.strip()
        if self.uses_supabase:
            self.supabase.update_profile(str(user_id), display_name=name)
            return
        self.db.update_user_display_name(int(user_id), name)

    def change_password(self, user_id: str | int, old_password: str, new_password: str) -> None:
        if len(new_password) < 6:
            raise ValueError("Mật khẩu mới tối thiểu 6 ký tự.")
        if self.uses_supabase:
            self.supabase.update_password(new_password)
            return
        user = self.db.get_user_by_id(int(user_id))
        if not user or not verify_password(old_password, user["password_hash"]):
            raise ValueError("Mật khẩu hiện tại không đúng.")
        self.db.update_user_password(int(user_id), new_password)

    def list_users(self) -> list[dict[str, Any]]:
        if self.uses_supabase:
            return self.supabase.list_profiles()
        return [self._map_local_user(u) for u in self.db.list_users()]

    def list_pending_users(self) -> list[dict[str, Any]]:
        if self.uses_supabase:
            return self.supabase.list_pending_profiles()
        return [
            self._map_local_user(u)
            for u in self.db.list_users()
            if str(u.get("approval_status") or "") == APPROVAL_PENDING
        ]

    def approve_user(self, actor_role: str, user_id: str | int, *, role: str | None = None) -> None:
        if normalize_role(actor_role) != "admin":
            raise PermissionError("Chi admin duyet tai khoan.")
        if self.uses_supabase:
            self.supabase.update_profile(
                str(user_id),
                role=role,
                is_active=True,
                approval_status=APPROVAL_APPROVED,
            )
            return
        self.db.update_user_approval(
            int(user_id),
            APPROVAL_APPROVED,
            is_active=True,
            role=role,
        )

    def reject_user(self, actor_role: str, user_id: str | int) -> None:
        if normalize_role(actor_role) != "admin":
            raise PermissionError("Chi admin tu choi tai khoan.")
        if self.uses_supabase:
            self.supabase.update_profile(
                str(user_id),
                is_active=False,
                approval_status=APPROVAL_REJECTED,
            )
            return
        self.db.update_user_approval(int(user_id), APPROVAL_REJECTED, is_active=False)

    def set_user_role(self, actor_role: str, user_id: str | int, role: str) -> None:
        if normalize_role(actor_role) != "admin":
            raise PermissionError("Chỉ admin được phân quyền.")
        if self.uses_supabase:
            self.supabase.update_profile(str(user_id), role=role)
            return
        self.db.update_user_role(int(user_id), role)

    def set_user_active(self, actor_role: str, user_id: str | int, is_active: bool) -> None:
        if normalize_role(actor_role) != "admin":
            raise PermissionError("Chỉ admin được khóa/mở tài khoản.")
        if self.uses_supabase:
            self.supabase.update_profile(str(user_id), is_active=is_active)
            return
        self.db.set_user_active(int(user_id), is_active)

    @staticmethod
    def _map_local_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(user["id"]),
            "username": str(user["username"]),
            "display_name": str(user.get("display_name") or user["username"]),
            "role": normalize_role(str(user.get("role") or DEFAULT_ROLE)),
            "is_active": bool(int(user.get("is_active", 1))),
            "approval_status": str(user.get("approval_status") or APPROVAL_APPROVED),
        }
