"""Trạng thái dùng chung giữa các tab."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from core.database import HubDatabase
from core.ol_reader import OlLoadResult, OlReaderService


@dataclass
class SessionUser:
    id: int
    username: str
    display_name: str


@dataclass
class AppState:
    user: SessionUser
    db: HubDatabase = field(default_factory=HubDatabase)
    ol_service: OlReaderService | None = None
    ol_df: pd.DataFrame | None = None
    ol_status: str = "Chưa đọc OL hôm nay."
    ol_ok: bool = False
    _listeners: list[Callable[[], None]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.ol_service is None:
            self.ol_service = OlReaderService(self.db)

    def on_change(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def notify(self) -> None:
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    def set_ol_result(self, result: OlLoadResult) -> None:
        self.ol_df = result.df
        self.ol_ok = result.row_count >= 0 and result.source != "error"
        self.ol_status = result.message
        self.notify()

    def set_ol_error(self, message: str) -> None:
        self.ol_ok = False
        self.ol_status = f"Lỗi: {message}"
        self.notify()

    def load_snapshot_into_state(self, snapshot_date: str) -> bool:
        result = self.ol_service.load_snapshot(snapshot_date)
        if not result:
            return False
        self.ol_df = result.df
        self.ol_ok = True
        self.ol_status = result.message
        self.notify()
        return True
