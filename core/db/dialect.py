"""SQL dialect helpers — SQLite today, PostgreSQL-ready placeholders and timestamps."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class DbBackend(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


def sql_placeholder(backend: DbBackend = DbBackend.SQLITE) -> str:
    return "?" if backend == DbBackend.SQLITE else "%s"


def now_iso(*, utc: bool = False) -> str:
    """ISO-8601 timestamp string stored in TEXT columns (portable across backends)."""
    if utc:
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    return datetime.now().isoformat(timespec="seconds")


def bool_int(value: bool) -> int:
    """Store booleans as INTEGER 0/1 for SQLite and PostgreSQL compatibility."""
    return 1 if value else 0
