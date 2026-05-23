"""Trạng thái dùng chung giữa các tab."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from core.bom_ke_reader import BomKeLoadResult, BomKeReaderService
from core.database import HubDatabase
from core.ol_reader import OlLoadResult, OlReaderService
from core.permissions import can_write, normalize_role
from core.utils import normalize_text


@dataclass
class SessionUser:
    id: str
    username: str
    display_name: str
    role: str = "design"

    def can_write(self, module: str) -> bool:
        return can_write(self.role, module)

    def can_manage_npl_types(self) -> bool:
        from core.permissions import can_manage_npl_types

        return can_manage_npl_types(self.role)

    def numeric_id(self) -> int | None:
        """ID số cho SQLite created_by (Supabase UUID → None)."""
        if str(self.id).isdigit():
            return int(self.id)
        return None


@dataclass
class AppState:
    user: SessionUser
    db: HubDatabase = field(default_factory=HubDatabase)
    ol_service: OlReaderService | None = None
    bom_ke_service: BomKeReaderService | None = None
    ol_df: pd.DataFrame | None = None
    bom_ke_df: pd.DataFrame | None = None
    ol_status: str = "Chưa đọc OL hôm nay."
    bom_ke_status: str = "Chưa đọc bảng kê."
    ol_ok: bool = False
    bom_ke_ok: bool = False
    active_ol_dataset_id: int | None = None
    active_bom_a6_hash: str | None = None
    _listeners: list[Callable[[], None]] = field(default_factory=list)
    _notify_after_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.ol_service is None:
            self.ol_service = OlReaderService(self.db)
        if self.bom_ke_service is None:
            self.bom_ke_service = BomKeReaderService(self.db)

    def on_change(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def notify(self, *, debounce_ms: int = 200) -> None:
        if debounce_ms <= 0:
            self._cancel_notify_timer()
            self._flush_notify()
            return
        try:
            root = __import__("tkinter")._default_root
            if root is not None:
                self._cancel_notify_timer()
                self._notify_after_id = root.after(debounce_ms, self._flush_notify)
                return
        except Exception:
            pass
        self._flush_notify()

    def _cancel_notify_timer(self) -> None:
        if not self._notify_after_id:
            return
        try:
            root = __import__("tkinter")._default_root
            if root is not None:
                root.after_cancel(self._notify_after_id)
        except Exception:
            pass
        self._notify_after_id = None

    def _flush_notify(self) -> None:
        self._notify_after_id = None
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    def set_ol_result(self, result: OlLoadResult) -> None:
        self.ol_df = result.df
        self.active_ol_dataset_id = result.dataset_id
        self.ol_ok = result.row_count >= 0 and result.source != "error"
        self.ol_status = result.message
        self.notify()

    def set_ol_error(self, message: str) -> None:
        self.ol_ok = False
        self.ol_status = f"Lỗi: {message}"
        self.notify()

    def load_active_ol_into_state(self, *, notify: bool = True) -> bool:
        """Nạp OL vừa đọc gần nhất (pointer trong DB) — không phải dataset cũ."""
        result = self.ol_service.load_active_dataset()
        if not result:
            self.ol_df = None
            self.active_ol_dataset_id = None
            self.ol_ok = False
            self.ol_status = "Chưa đọc OL — vào Setup để đọc file."
            return False
        self.ol_df = result.df
        self.active_ol_dataset_id = result.dataset_id
        self.ol_ok = True
        self.ol_status = result.message
        if notify:
            self.notify()
        return True

    def get_active_ol_df(self) -> pd.DataFrame | None:
        active_id = self.db.get_setup("ol_active_dataset_id", "")
        if (
            self.ol_df is not None
            and not self.ol_df.empty
            and self.active_ol_dataset_id is not None
            and active_id == str(self.active_ol_dataset_id)
        ):
            return self.ol_df
        if self.load_active_ol_into_state(notify=False):
            return self.ol_df
        return None

    def set_bom_ke_result(self, result: BomKeLoadResult) -> None:
        self.bom_ke_df = result.df
        self.bom_ke_ok = result.row_count >= 0
        self.bom_ke_status = result.message
        self.active_bom_a6_hash = normalize_text(result.a6_hash) or self.db.get_setup("bom_ke_a6_hash", "")
        self.notify()

    def set_bom_ke_error(self, message: str) -> None:
        self.bom_ke_ok = False
        self.bom_ke_status = f"Lỗi: {message}"
        self.notify()

    def load_bom_ke_into_state(self, *, notify: bool = True) -> bool:
        result = self.bom_ke_service.load_cached()
        if not result or result.df is None or result.df.empty:
            self.bom_ke_ok = False
            if result and result.df is not None and result.df.empty:
                self.bom_ke_status = "Bảng kê cache rỗng — vào Setup bấm Đọc bảng kê lại."
            return False
        self.bom_ke_df = result.df
        self.bom_ke_ok = True
        self.bom_ke_status = result.message
        self.active_bom_a6_hash = normalize_text(result.a6_hash) or self.db.get_setup("bom_ke_a6_hash", "")
        if notify:
            self.notify()
        return True

    def get_active_bom_ke_df(self) -> pd.DataFrame | None:
        a6 = normalize_text(self.db.get_setup("bom_ke_a6_hash", ""))
        if (
            self.bom_ke_ok
            and self.bom_ke_df is not None
            and not self.bom_ke_df.empty
            and (not a6 or a6 == normalize_text(self.active_bom_a6_hash))
        ):
            return self.bom_ke_df
        if self.load_bom_ke_into_state(notify=False):
            return self.bom_ke_df
        return None

    def load_snapshot_into_state(self, snapshot_date: str) -> bool:
        result = self.ol_service.load_snapshot(snapshot_date)
        if not result:
            return False
        self.ol_df = result.df
        self.ol_ok = True
        self.ol_status = result.message
        self.notify()
        return True
