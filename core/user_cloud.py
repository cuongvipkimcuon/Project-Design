"""Đồng bộ settings + metadata dataset lên Supabase (per owner_id)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.supabase_config import supabase_enabled
from core.utils import normalize_text

# Keys đồng bộ cloud (link cá nhân + pointer cache)
SYNC_SETTING_KEYS = frozenset(
    {
        "ol_file_path",
        "ol_file_name",
        "emg_scanner_json_path",
        "bom_ke_file_path",
        "bom_link",
        "bom_ke_a6_hash",
        "bom_ke_a6_text",
        "ol_active_dataset_id",
        "ol_active_read_at",
        "ol_active_file_name",
        "ol_active_file_path",
        "supplier_template_path",
        "supplier_template_file_name",
    }
)


class UserCloud:
    def __init__(
        self,
        owner_id: str,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self.owner_id = normalize_text(owner_id)
        self._access_token = normalize_text(access_token) or None
        self._refresh_token = normalize_text(refresh_token) or None
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.owner_id) and supabase_enabled() and not self.owner_id.isdigit()

    def _safe(self, action: str, fn) -> None:
        if not self.enabled:
            return
        try:
            fn()
        except Exception as exc:
            print(f"[UserCloud] {action}: {exc}")

    def _get_client(self):
        if self._client is not None:
            return self._client
        from supabase import create_client

        from core.supabase_config import SUPABASE_ANON_KEY, SUPABASE_URL

        self._client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
        if self._access_token and self._refresh_token:
            try:
                self._client.auth.set_session(self._access_token, self._refresh_token)
            except Exception as exc:
                print(f"[UserCloud] set_session: {exc}")
        return self._client

    def pull_settings(self) -> dict[str, str]:
        if not self.enabled:
            return {}
        out: dict[str, str] = {}

        def _run() -> None:
            client = self._get_client()
            rows = (
                client.table("user_settings")
                .select("key, value")
                .eq("owner_id", self.owner_id)
                .execute()
                .data
                or []
            )
            for r in rows:
                k = str(r.get("key") or "")
                if k in SYNC_SETTING_KEYS:
                    out[k] = str(r.get("value") or "")

        try:
            _run()
        except Exception as exc:
            print(f"[UserCloud] pull_settings: {exc}")
        return out

    def set_setting(self, key: str, value: str) -> None:
        if not self.enabled or key not in SYNC_SETTING_KEYS:
            return

        def _run() -> None:
            client = self._get_client()
            client.table("user_settings").upsert(
                {
                    "owner_id": self.owner_id,
                    "key": key,
                    "value": value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).execute()

        self._safe("set_setting", _run)

    def upsert_dataset(
        self,
        *,
        dataset_type: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        is_active: bool = False,
        visibility: str = "private",
    ) -> None:
        if not self.enabled:
            return

        def _run() -> None:
            client = self._get_client()
            if is_active:
                client.table("user_datasets").update({"is_active": False}).eq(
                    "owner_id", self.owner_id
                ).eq("dataset_type", dataset_type).execute()

            payload = {
                "owner_id": self.owner_id,
                "dataset_type": dataset_type,
                "file_name": normalize_text(file_name),
                "file_path": normalize_text(file_path),
                "file_hash": normalize_text(file_hash),
                "content_hash": normalize_text(content_hash) or normalize_text(file_hash),
                "row_count": int(row_count),
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "is_active": bool(is_active),
                "visibility": visibility if visibility in ("private", "team") else "private",
            }
            try:
                client.table("user_datasets").upsert(
                    payload,
                    on_conflict="owner_id,dataset_type,content_hash",
                ).execute()
            except Exception:
                client.table("user_datasets").upsert(payload).execute()

        self._safe("upsert_dataset", _run)

    def set_active_dataset(self, dataset_type: str, content_hash: str) -> None:
        if not self.enabled:
            return

        def _run() -> None:
            client = self._get_client()
            client.table("user_datasets").update({"is_active": False}).eq(
                "owner_id", self.owner_id
            ).eq("dataset_type", dataset_type).execute()
            if content_hash:
                client.table("user_datasets").update({"is_active": True}).eq(
                    "owner_id", self.owner_id
                ).eq("dataset_type", dataset_type).eq(
                    "content_hash", content_hash
                ).execute()

        self._safe("set_active_dataset", _run)

    def list_datasets(self, dataset_type: str | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []

        def _run() -> list[dict[str, Any]]:
            client = self._get_client()
            q = client.table("user_datasets").select("*").eq("owner_id", self.owner_id)
            if dataset_type:
                q = q.eq("dataset_type", dataset_type)
            return q.order("imported_at", desc=True).execute().data or []

        try:
            return _run()
        except Exception as exc:
            print(f"[UserCloud] list_datasets: {exc}")
            return []

    def publish_team_dataset(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        rows_data: list[dict],
    ) -> str:
        """Admin: đăng bản active lên team_datasets (chunk nếu lớn)."""
        if not self.enabled:
            raise RuntimeError("Cloud chưa bật (đăng nhập Supabase).")

        from core.team_dataset_store import TeamDatasetStore, format_cloud_error

        try:
            store = TeamDatasetStore(self.owner_id, self._get_client)
            dataset_id = store.publish(
                dataset_type=dataset_type,
                publisher_name=normalize_text(publisher_name),
                file_name=file_name,
                file_path=file_path,
                file_hash=file_hash,
                content_hash=content_hash,
                row_count=row_count,
                meta=meta,
                records=rows_data,
            )
            self.upsert_dataset(
                dataset_type=dataset_type,
                file_name=file_name,
                file_path=file_path,
                file_hash=file_hash,
                content_hash=content_hash,
                row_count=row_count,
                is_active=True,
                visibility="team",
            )
            return dataset_id
        except Exception as exc:
            raise RuntimeError(format_cloud_error(exc)) from exc

    def publish_team_excel_file(
        self,
        *,
        dataset_type: str,
        publisher_name: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        content_hash: str,
        row_count: int,
        meta: dict,
        excel_path: str,
    ) -> str:
        """Chia sẻ file Excel gzip (bảng kê — không gửi từng dòng JSON)."""
        if not self.enabled:
            raise RuntimeError("Cloud chưa bật (đăng nhập Supabase).")

        from core.team_dataset_store import TeamDatasetStore, format_cloud_error

        try:
            store = TeamDatasetStore(self.owner_id, self._get_client)
            dataset_id = store.publish_excel_file(
                dataset_type=dataset_type,
                publisher_name=normalize_text(publisher_name),
                file_name=file_name,
                file_path=file_path,
                file_hash=file_hash,
                content_hash=content_hash,
                row_count=row_count,
                meta=meta,
                excel_path=excel_path,
            )
            self.upsert_dataset(
                dataset_type=dataset_type,
                file_name=file_name,
                file_path=file_path,
                file_hash=file_hash,
                content_hash=content_hash,
                row_count=row_count,
                is_active=True,
                visibility="team",
            )
            return dataset_id
        except Exception as exc:
            raise RuntimeError(format_cloud_error(exc)) from exc

    def fetch_team_excel_bytes(self, dataset_type: str) -> tuple[dict[str, Any], bytes]:
        if not self.enabled:
            return {}, b""
        from core.team_dataset_store import TeamDatasetStore, format_cloud_error

        try:
            store = TeamDatasetStore(self.owner_id, self._get_client)
            return store.fetch_excel_bytes(dataset_type)
        except Exception as exc:
            raise RuntimeError(format_cloud_error(exc)) from exc

    def get_active_team_dataset(self, dataset_type: str) -> dict[str, Any] | None:
        """Header + rows_data (đã gộp chunk)."""
        if not self.enabled:
            return None

        from core.team_dataset_store import TeamDatasetStore, format_cloud_error

        try:
            store = TeamDatasetStore(self.owner_id, self._get_client)
            header, records = store.fetch_records(dataset_type)
            if not header:
                return None
            header = dict(header)
            header["rows_data"] = records
            return header
        except Exception as exc:
            print(f"[UserCloud] get_active_team_dataset: {format_cloud_error(exc)}")
            return None

    def get_active_team_dataset_header(self, dataset_type: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        from core.team_dataset_store import TeamDatasetStore, format_cloud_error

        try:
            store = TeamDatasetStore(self.owner_id, self._get_client)
            return store.fetch_header(dataset_type)
        except Exception as exc:
            print(f"[UserCloud] get_active_team_dataset_header: {format_cloud_error(exc)}")
            return None
