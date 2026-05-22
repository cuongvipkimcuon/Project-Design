"""Supabase Auth + bảng profiles."""

from __future__ import annotations

from typing import Any

from core.permissions import DEFAULT_ROLE, normalize_role
from core.supabase_config import (
    AUTH_EMAIL_DOMAIN,
    auth_email_for_username,
    supabase_enabled,
    username_from_auth_email,
)
from core.utils import normalize_text

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"


class SupabaseService:
    def __init__(self) -> None:
        self._client = None
        self._session = None

    @property
    def enabled(self) -> bool:
        return supabase_enabled()

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.enabled:
            raise RuntimeError("Supabase chưa cấu hình (SUPABASE_URL, SUPABASE_ANON_KEY).")
        from supabase import create_client

        from core.supabase_config import SUPABASE_ANON_KEY, SUPABASE_URL

        self._client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        return self._client

    def sign_up(self, username: str, password: str, display_name: str = "") -> dict[str, Any]:
        client = self._get_client()
        email = auth_email_for_username(username)
        uname = normalize_text(username).lower()
        dname = normalize_text(display_name) or uname
        resp = client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "username": uname,
                        "display_name": dname,
                    }
                },
            }
        )
        user = resp.user
        if not user:
            raise ValueError("Đăng ký thất bại — kiểm tra email đã dùng hoặc cấu hình Supabase.")
        return self._upsert_profile(
            str(user.id),
            username=uname,
            display_name=dname,
            role=DEFAULT_ROLE,
            is_active=False,
            approval_status=APPROVAL_PENDING,
        )

    def sign_in(self, username: str, password: str) -> dict[str, Any]:
        client = self._get_client()
        email = auth_email_for_username(username)
        resp = client.auth.sign_in_with_password({"email": email, "password": password})
        user = resp.user
        if not user:
            raise ValueError("Sai tên đăng nhập hoặc mật khẩu.")
        self._session = getattr(resp, "session", None)
        profile = self.get_profile_by_id(str(user.id))
        if not profile:
            profile = self._upsert_profile(
                str(user.id),
                username=username_from_auth_email(email),
                display_name=normalize_text(user.user_metadata.get("display_name")) or username,
                role=DEFAULT_ROLE,
                is_active=False,
                approval_status=APPROVAL_PENDING,
            )
        self._ensure_can_login(profile)
        return profile

    @property
    def access_token(self) -> str | None:
        if self._session is None:
            return None
        return getattr(self._session, "access_token", None)

    @property
    def refresh_token(self) -> str | None:
        if self._session is None:
            return None
        return getattr(self._session, "refresh_token", None)

    def _ensure_can_login(self, profile: dict[str, Any]) -> None:
        status = str(profile.get("approval_status") or APPROVAL_APPROVED)
        if status == APPROVAL_PENDING:
            raise ValueError("Tài khoản chưa được admin duyệt.")
        if status == APPROVAL_REJECTED:
            raise ValueError("Tài khoản đã bị từ chối.")
        if not profile.get("is_active", True):
            raise ValueError("Tài khoản đã bị khóa.")

    def update_password(self, new_password: str) -> None:
        client = self._get_client()
        client.auth.update_user({"password": new_password})

    def get_profile_by_id(self, user_id: str) -> dict[str, Any] | None:
        client = self._get_client()
        rows = (
            client.table("profiles")
            .select("*")
            .eq("id", user_id)
            .limit(1)
            .execute()
            .data
        )
        return self._map_profile(rows[0]) if rows else None

    def get_profile_by_username(self, username: str) -> dict[str, Any] | None:
        client = self._get_client()
        rows = (
            client.table("profiles")
            .select("*")
            .eq("username", normalize_text(username).lower())
            .limit(1)
            .execute()
            .data
        )
        return self._map_profile(rows[0]) if rows else None

    def list_profiles(self) -> list[dict[str, Any]]:
        client = self._get_client()
        rows = client.table("profiles").select("*").order("username").execute().data or []
        return [self._map_profile(r) for r in rows]

    def list_pending_profiles(self) -> list[dict[str, Any]]:
        client = self._get_client()
        rows = (
            client.table("profiles")
            .select("*")
            .eq("approval_status", APPROVAL_PENDING)
            .order("created_at")
            .execute()
            .data
            or []
        )
        return [self._map_profile(r) for r in rows]

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        approval_status: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if display_name is not None:
            payload["display_name"] = normalize_text(display_name)
        if role is not None:
            payload["role"] = normalize_role(role)
        if is_active is not None:
            payload["is_active"] = bool(is_active)
        if approval_status is not None:
            payload["approval_status"] = approval_status
        if not payload:
            existing = self.get_profile_by_id(user_id)
            if not existing:
                raise ValueError("User không tồn tại.")
            return existing
        client = self._get_client()
        rows = client.table("profiles").update(payload).eq("id", user_id).execute().data or []
        if not rows:
            raise ValueError("Không cập nhật được profile.")
        return self._map_profile(rows[0])

    def ensure_super_admin(
        self,
        username: str,
        password: str,
        display_name: str = "Administrator",
    ) -> dict[str, Any]:
        uname = normalize_text(username).lower()
        existing = self.get_profile_by_username(uname)
        if existing:
            return self.update_profile(
                existing["id"],
                role="admin",
                is_active=True,
                approval_status=APPROVAL_APPROVED,
                display_name=display_name or existing.get("display_name"),
            )

        client = self._get_client()
        email = auth_email_for_username(uname)
        resp = client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {
                    "data": {
                        "username": uname,
                        "display_name": display_name,
                    }
                },
            }
        )
        user = resp.user
        if not user:
            raise ValueError(
                "Không tạo được admin — username đã tồn tại trên Auth hoặc mật khẩu không hợp lệ."
            )
        return self.update_profile(
            str(user.id),
            role="admin",
            is_active=True,
            approval_status=APPROVAL_APPROVED,
            display_name=display_name,
        )

    def _upsert_profile(
        self,
        user_id: str,
        *,
        username: str,
        display_name: str,
        role: str,
        is_active: bool = False,
        approval_status: str = APPROVAL_PENDING,
    ) -> dict[str, Any]:
        client = self._get_client()
        row = {
            "id": user_id,
            "username": normalize_text(username).lower(),
            "display_name": normalize_text(display_name) or username,
            "role": normalize_role(role),
            "is_active": bool(is_active),
            "approval_status": approval_status,
        }
        rows = client.table("profiles").upsert(row).execute().data or []
        if rows:
            return self._map_profile(rows[0])
        existing = self.get_profile_by_id(user_id)
        if existing:
            return existing
        raise ValueError("Không tạo được profile trên Supabase.")

    @staticmethod
    def _map_profile(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "username": str(row.get("username") or ""),
            "display_name": str(row.get("display_name") or row.get("username") or ""),
            "role": normalize_role(str(row.get("role") or DEFAULT_ROLE)),
            "is_active": bool(row.get("is_active", True)),
            "approval_status": str(row.get("approval_status") or APPROVAL_APPROVED),
            "auth_email": f"{row.get('username', '')}@{AUTH_EMAIL_DOMAIN}",
        }
