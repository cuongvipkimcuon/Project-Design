"""Đường dẫn khi chạy source hoặc bản PyInstaller."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Thư mục làm việc — .env, SQLite, file user đặt cạnh exe."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_dir() -> Path:
    """Tài nguyên đóng gói (template, supabase SQL)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def ensure_app_cwd() -> None:
    if is_frozen():
        import os

        os.chdir(app_dir())
