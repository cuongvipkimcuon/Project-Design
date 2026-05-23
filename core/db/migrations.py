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
    _add_column(cur, "planning_entries", "customer_code", "customer_code TEXT NOT NULL DEFAULT ''")


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
            npl_stock_type_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES planning_entries(id) ON DELETE CASCADE
        )
        """
    )
    _add_column(
        cur,
        "planning_prepare_items",
        "npl_stock_type_id",
        "npl_stock_type_id INTEGER",
    )


def ensure_user_role_column(cur: sqlite3.Cursor) -> None:
    _add_column(cur, "users", "role", "role TEXT NOT NULL DEFAULT 'design'")


def ensure_bom_ke_column_names(cur: sqlite3.Cursor) -> None:
    """Doi ten cot bang ke: order_qty, npl_qty_per_unit, npl_qty_order."""
    cols = _table_columns(cur, "bom_ke_rows")
    renames = [
        ("qty_divisor", "order_qty"),
        ("so_luong_dm_1", "npl_qty_per_unit"),
        ("so_luong", "npl_qty_order"),
    ]
    for old, new in renames:
        if old in cols and new not in cols:
            cur.execute(f"ALTER TABLE bom_ke_rows RENAME COLUMN {old} TO {new}")


def ensure_user_approval_column(cur: sqlite3.Cursor) -> None:
    _add_column(
        cur,
        "users",
        "approval_status",
        "approval_status TEXT NOT NULL DEFAULT 'approved'",
    )


def _has_index(cur: sqlite3.Cursor, name: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def ensure_owner_cache_tables(cur: sqlite3.Cursor) -> None:
    """Cache OL/BOM/snapshot theo owner_id — mỗi user một không gian local."""
    if "owner_id" not in _table_columns(cur, "ol_file_hash"):
        cur.execute(
            """
            CREATE TABLE ol_file_hash_new (
                owner_id TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                last_read_at TEXT NOT NULL,
                PRIMARY KEY (owner_id, file_path)
            )
            """
        )
        cur.execute(
            """
            INSERT INTO ol_file_hash_new(owner_id, file_path, file_hash, last_read_at)
            SELECT '', file_path, file_hash, last_read_at FROM ol_file_hash
            """
        )
        cur.execute("DROP TABLE ol_file_hash")
        cur.execute("ALTER TABLE ol_file_hash_new RENAME TO ol_file_hash")

    if "owner_id" not in _table_columns(cur, "ol_datasets"):
        cur.execute(
            """
            CREATE TABLE ol_datasets_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL DEFAULT '',
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            INSERT INTO ol_datasets_new(id, owner_id, file_name, file_path, file_hash, imported_at, row_count)
            SELECT id, '', file_name, file_path, file_hash, imported_at, row_count FROM ol_datasets
            """
        )
        cur.execute("DROP TABLE ol_datasets")
        cur.execute("ALTER TABLE ol_datasets_new RENAME TO ol_datasets")
        cur.execute(
            "CREATE UNIQUE INDEX idx_ol_datasets_owner_scope ON ol_datasets(owner_id, file_name, file_hash)"
        )

    if "owner_id" not in _table_columns(cur, "bom_ke_datasets"):
        cur.execute(
            """
            CREATE TABLE bom_ke_datasets_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL DEFAULT '',
                file_name TEXT NOT NULL,
                file_path TEXT NOT NULL,
                a6_text TEXT NOT NULL,
                a6_hash TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            INSERT INTO bom_ke_datasets_new(
                id, owner_id, file_name, file_path, a6_text, a6_hash, file_hash, imported_at, row_count
            )
            SELECT id, '', file_name, file_path, a6_text, a6_hash, file_hash, imported_at, row_count
            FROM bom_ke_datasets
            """
        )
        cur.execute("DROP TABLE bom_ke_datasets")
        cur.execute("ALTER TABLE bom_ke_datasets_new RENAME TO bom_ke_datasets")
        cur.execute(
            "CREATE UNIQUE INDEX idx_bom_ke_datasets_owner_scope ON bom_ke_datasets(owner_id, a6_hash)"
        )

    if "owner_id" not in _table_columns(cur, "ol_snapshots"):
        cur.execute(
            """
            CREATE TABLE ol_snapshots_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL DEFAULT '',
                snapshot_date TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            INSERT INTO ol_snapshots_new(
                id, owner_id, snapshot_date, file_path, file_hash, imported_at, row_count
            )
            SELECT id, '', snapshot_date, file_path, file_hash, imported_at, row_count FROM ol_snapshots
            """
        )
        cur.execute("DROP TABLE ol_snapshots")
        cur.execute("ALTER TABLE ol_snapshots_new RENAME TO ol_snapshots")
        cur.execute(
            "CREATE UNIQUE INDEX idx_ol_snapshots_owner_scope ON ol_snapshots(owner_id, snapshot_date)"
        )


def ensure_supplier_tables(cur: sqlite3.Cursor) -> None:
    from core.db.schema import build_schema

    for sql in build_schema():
        if "supplier_slip" in sql:
            cur.execute(sql)


def ensure_npl_stock_tables(cur: sqlite3.Cursor) -> None:
    from core.db.schema import build_schema

    for sql in build_schema():
        if "npl_stock" in sql:
            cur.execute(sql)


def ensure_performance_indexes(cur: sqlite3.Cursor) -> None:
    """Index bổ sung cho DB cũ — an toàn chạy lại nhiều lần."""
    from core.db.schema import build_indexes

    existing = {
        str(r[0])
        for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    for sql in build_indexes():
        name = sql.split("IF NOT EXISTS", 1)[-1].split("ON", 1)[0].strip()
        if name in existing:
            continue
        try:
            cur.execute(sql)
        except sqlite3.OperationalError:
            pass


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
