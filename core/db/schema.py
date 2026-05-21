"""Portable DDL — INTEGER booleans, TEXT timestamps, standard SQL types.

PostgreSQL migration notes (future online sync):
- Replace INTEGER PRIMARY KEY AUTOINCREMENT with BIGSERIAL PRIMARY KEY
- Keep TEXT ISO timestamps or migrate to TIMESTAMPTZ
- Placeholders: ? (sqlite) -> %s (psycopg2)
- ON CONFLICT ... DO UPDATE works on both modern SQLite and PostgreSQL
"""

from __future__ import annotations

from core.db.dialect import DbBackend

PLANNING_ACTIVE_FILTER = "is_deleted = 0"


def _pk(backend: DbBackend) -> str:
    if backend == DbBackend.POSTGRES:
        return "BIGSERIAL PRIMARY KEY"
    return "INTEGER PRIMARY KEY AUTOINCREMENT"


def build_schema(backend: DbBackend = DbBackend.SQLITE) -> list[str]:
    pk = _pk(backend)
    return [
        """
        CREATE TABLE IF NOT EXISTS setup (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ol_snapshots (
            id {pk},
            snapshot_date TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(snapshot_date)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ol_file_hash (
            file_path TEXT PRIMARY KEY,
            file_hash TEXT NOT NULL,
            last_read_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {pk},
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ol_datasets (
            id {pk},
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(file_name, file_hash)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ol_rows (
            id {pk},
            dataset_id INTEGER NOT NULL,
            excel_row INTEGER,
            order_date TEXT,
            order_date_str TEXT,
            order_no TEXT,
            dg_case TEXT NOT NULL DEFAULT '',
            customer TEXT,
            qty REAL,
            production_no TEXT,
            production_name TEXT,
            logo TEXT,
            color TEXT,
            supplier TEXT,
            shipdate TEXT,
            material TEXT,
            cutting TEXT,
            cutting_str TEXT,
            stock TEXT,
            stock_str TEXT,
            estimate_delivery TEXT,
            estimate_delivery_str TEXT,
            customer_code TEXT,
            item_code TEXT,
            FOREIGN KEY(dataset_id) REFERENCES ol_datasets(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS bom_ke_datasets (
            id {pk},
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            a6_text TEXT NOT NULL,
            a6_hash TEXT NOT NULL UNIQUE,
            file_hash TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS bom_ke_rows (
            id {pk},
            dataset_id INTEGER NOT NULL,
            row_index INTEGER,
            dg_case TEXT NOT NULL DEFAULT '',
            order_date TEXT,
            product_code TEXT,
            qty_divisor REAL,
            ma_npl TEXT,
            ten_npl TEXT,
            mo_ta TEXT,
            don_vi_tinh TEXT,
            so_luong_dm_1 REAL,
            so_luong REAL,
            customer_code TEXT,
            item_code TEXT,
            FOREIGN KEY(dataset_id) REFERENCES bom_ke_datasets(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS planning_entries (
            id {pk},
            dg_case TEXT NOT NULL DEFAULT '',
            item_code TEXT NOT NULL DEFAULT '',
            supplier TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            plan_date TEXT NOT NULL DEFAULT '',
            plan_date_iso TEXT NOT NULL DEFAULT '',
            verify_date TEXT NOT NULL DEFAULT '',
            verify_date_iso TEXT NOT NULL DEFAULT '',
            session TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planned',
            check_status TEXT NOT NULL DEFAULT 'pending',
            prepare_status TEXT NOT NULL DEFAULT 'pending',
            check_by TEXT NOT NULL DEFAULT '',
            prepare_by TEXT NOT NULL DEFAULT '',
            check_at TEXT NOT NULL DEFAULT '',
            prepare_at TEXT NOT NULL DEFAULT '',
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT NOT NULL DEFAULT '',
            deleted_by TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS planning_prepare_items (
            id {pk},
            entry_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL DEFAULT 0,
            ma_npl TEXT NOT NULL DEFAULT '',
            ten_npl TEXT NOT NULL DEFAULT '',
            mo_ta TEXT NOT NULL DEFAULT '',
            quantity REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES planning_entries(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS planning_audit_log (
            id {pk},
            entry_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            actor_user_id INTEGER,
            detail_json TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY(entry_id) REFERENCES planning_entries(id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS weekly_label_plans (
            id {pk},
            week_start TEXT NOT NULL,
            dg_case TEXT NOT NULL DEFAULT '',
            order_no TEXT NOT NULL DEFAULT '',
            customer TEXT NOT NULL DEFAULT '',
            production_name TEXT NOT NULL DEFAULT '',
            planned_date TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
    ]


def build_indexes() -> list[str]:
    return [
        "CREATE INDEX IF NOT EXISTS idx_ol_rows_dataset ON ol_rows(dataset_id)",
        "CREATE INDEX IF NOT EXISTS idx_ol_rows_dg_case ON ol_rows(dg_case)",
        "CREATE INDEX IF NOT EXISTS idx_ol_rows_order_no ON ol_rows(order_no)",
        "CREATE INDEX IF NOT EXISTS idx_ol_rows_production_no ON ol_rows(production_no)",
        "CREATE INDEX IF NOT EXISTS idx_ol_rows_file_name ON ol_datasets(file_name)",
        "CREATE INDEX IF NOT EXISTS idx_bom_ke_rows_dataset ON bom_ke_rows(dataset_id)",
        "CREATE INDEX IF NOT EXISTS idx_bom_ke_rows_dg_case ON bom_ke_rows(dg_case)",
        "CREATE INDEX IF NOT EXISTS idx_bom_ke_rows_product ON bom_ke_rows(product_code)",
        "CREATE INDEX IF NOT EXISTS idx_bom_ke_rows_ma_npl ON bom_ke_rows(ma_npl)",
        "CREATE INDEX IF NOT EXISTS idx_bom_ke_datasets_a6 ON bom_ke_datasets(a6_hash)",
        "CREATE INDEX IF NOT EXISTS idx_planning_plan_date ON planning_entries(plan_date_iso)",
        "CREATE INDEX IF NOT EXISTS idx_planning_verify_date ON planning_entries(verify_date_iso)",
        "CREATE INDEX IF NOT EXISTS idx_planning_dg_case ON planning_entries(dg_case)",
        "CREATE INDEX IF NOT EXISTS idx_planning_supplier ON planning_entries(supplier)",
        "CREATE INDEX IF NOT EXISTS idx_planning_status ON planning_entries(status)",
        "CREATE INDEX IF NOT EXISTS idx_planning_check ON planning_entries(check_status)",
        "CREATE INDEX IF NOT EXISTS idx_planning_prepare ON planning_entries(prepare_status)",
        "CREATE INDEX IF NOT EXISTS idx_planning_prepare_items_entry ON planning_prepare_items(entry_id)",
        "CREATE INDEX IF NOT EXISTS idx_planning_active ON planning_entries(is_deleted)",
        "CREATE INDEX IF NOT EXISTS idx_planning_audit_entry ON planning_audit_log(entry_id)",
        "CREATE INDEX IF NOT EXISTS idx_planning_audit_created ON planning_audit_log(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_planning_audit_action ON planning_audit_log(action)",
    ]


SCHEMA_STATEMENTS = build_schema() + build_indexes()
