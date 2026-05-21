"""Incremental schema migrations for existing SQLite databases."""

from __future__ import annotations

import sqlite3


def _table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    return {str(r[1]) for r in cur.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(cur: sqlite3.Cursor, table: str, column: str, ddl: str) -> None:
    cols = _table_columns(cur, table)
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def ensure_planning_columns(cur: sqlite3.Cursor) -> None:
    _add_column(cur, "planning_entries", "check_status", "check_status TEXT NOT NULL DEFAULT 'pending'")
    _add_column(cur, "planning_entries", "prepare_status", "prepare_status TEXT NOT NULL DEFAULT 'pending'")
    _add_column(cur, "planning_entries", "check_by", "check_by TEXT NOT NULL DEFAULT ''")
    _add_column(cur, "planning_entries", "prepare_by", "prepare_by TEXT NOT NULL DEFAULT ''")
    _add_column(cur, "planning_entries", "check_at", "check_at TEXT NOT NULL DEFAULT ''")
    _add_column(cur, "planning_entries", "is_deleted", "is_deleted INTEGER NOT NULL DEFAULT 0")
    _add_column(cur, "planning_entries", "deleted_at", "deleted_at TEXT NOT NULL DEFAULT ''")
    _add_column(cur, "planning_entries", "deleted_by", "deleted_by TEXT NOT NULL DEFAULT ''")
    _add_column(cur, "planning_entries", "supplier", "supplier TEXT NOT NULL DEFAULT ''")
    _add_column(cur, "planning_entries", "prepare_at", "prepare_at TEXT NOT NULL DEFAULT ''")


def ensure_planning_prepare_items_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_prepare_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL DEFAULT 0,
            ma_npl TEXT NOT NULL DEFAULT '',
            ten_npl TEXT NOT NULL DEFAULT '',
            mo_ta TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES planning_entries(id) ON DELETE CASCADE
        )
        """
    )


def ensure_planning_audit_table(cur: sqlite3.Cursor) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            actor_user_id INTEGER,
            detail_json TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES planning_entries(id)
        )
        """
    )
