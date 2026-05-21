"""Portable database schema and dialect helpers (SQLite now, PostgreSQL later)."""

from core.db.dialect import DbBackend, now_iso, sql_placeholder
from core.db.schema import SCHEMA_STATEMENTS, build_indexes, build_schema

__all__ = [
    "DbBackend",
    "SCHEMA_STATEMENTS",
    "build_indexes",
    "build_schema",
    "now_iso",
    "sql_placeholder",
]
