"""SQLite persistence for OL snapshots, users, and weekly plans."""

from __future__ import annotations

import json
import pickle
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from core.bom_ke_columns import NPL_QTY_ORDER, NPL_QTY_PER_UNIT, ORDER_QTY
from core.db.dialect import now_iso
from core.db.migrations import (
    ensure_owner_cache_tables,
    ensure_planning_audit_table,
    ensure_planning_columns,
    ensure_planning_prepare_items_table,
    ensure_bom_ke_column_names,
    ensure_supplier_tables,
    ensure_user_approval_column,
    ensure_user_role_column,
)

if TYPE_CHECKING:
    from core.user_cloud import UserCloud
from core.permissions import DEFAULT_ROLE, normalize_role
from core.db.schema import PLANNING_ACTIVE_FILTER, build_indexes, build_schema
from core.utils import hash_password, normalize_text

DB_FILE = "dg_hub.db"


class HubDatabase:
    def __init__(
        self,
        db_file: str = DB_FILE,
        *,
        owner_id: str = "",
        cloud: UserCloud | None = None,
    ):
        self.db_file = db_file
        self.owner_id = normalize_text(owner_id)
        self.cloud = cloud
        self._init_db()

    def _oid(self) -> str:
        return self.owner_id

    def _sk(self, key: str) -> str:
        if self.owner_id:
            return f"u:{self.owner_id}:{key}"
        return key

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        cur = conn.cursor()
        for sql in build_schema():
            cur.execute(sql)
        ensure_planning_columns(cur)
        ensure_planning_audit_table(cur)
        ensure_planning_prepare_items_table(cur)
        ensure_user_role_column(cur)
        ensure_user_approval_column(cur)
        ensure_owner_cache_tables(cur)
        ensure_bom_ke_column_names(cur)
        ensure_supplier_tables(cur)
        for sql in build_indexes():
            cur.execute(sql)
        conn.commit()
        conn.close()

    # --- Users (admin thêm trực tiếp DB hoặc tools/add_user.py) ---

    def count_users(self) -> int:
        conn = self._connect()
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return int(n)

    def create_user(
        self,
        username: str,
        password: str,
        display_name: str = "",
        *,
        role: str = DEFAULT_ROLE,
        approval_status: str = "pending",
        is_active: bool = False,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users(
                username, password_hash, display_name, role, approval_status, is_active, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username.strip().lower(),
                hash_password(password),
                display_name.strip() or username.strip(),
                normalize_role(role),
                approval_status,
                1 if is_active else 0,
                now,
            ),
        )
        uid = int(cur.lastrowid)
        conn.commit()
        conn.close()
        return uid

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def update_user_display_name(self, user_id: int, display_name: str) -> None:
        conn = self._connect()
        conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (display_name, user_id))
        conn.commit()
        conn.close()

    def update_user_password(self, user_id: int, new_password: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        conn.commit()
        conn.close()

    def update_user_role(self, user_id: int, role: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (normalize_role(role), user_id),
        )
        conn.commit()
        conn.close()

    def set_user_active(self, user_id: int, is_active: bool) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
        conn.commit()
        conn.close()

    def update_user_approval(
        self,
        user_id: int,
        approval_status: str,
        *,
        is_active: bool | None = None,
        role: str | None = None,
    ) -> None:
        conn = self._connect()
        if is_active is None:
            is_active = approval_status == "approved"
        sql = "UPDATE users SET approval_status = ?, is_active = ?"
        params: list[Any] = [approval_status, 1 if is_active else 0]
        if role is not None:
            sql += ", role = ?"
            params.append(normalize_role(role))
        sql += " WHERE id = ?"
        params.append(user_id)
        conn.execute(sql, params)
        conn.commit()
        conn.close()

    def list_users(self) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM users ORDER BY username COLLATE NOCASE ASC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # --- Weekly label plans ---

    def list_weekly_plans(self, week_start: str) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM weekly_label_plans
            WHERE week_start = ?
            ORDER BY planned_date ASC, id ASC
            """,
            (week_start,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_weekly_plan(
        self,
        week_start: str,
        *,
        dg_case: str = "",
        order_no: str = "",
        customer: str = "",
        production_name: str = "",
        planned_date: str = "",
        notes: str = "",
        created_by: int | None = None,
    ) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO weekly_label_plans(
                week_start, dg_case, order_no, customer, production_name,
                planned_date, notes, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                week_start,
                dg_case,
                order_no,
                customer,
                production_name,
                planned_date,
                notes,
                created_by,
                now,
                now,
            ),
        )
        pid = int(cur.lastrowid)
        conn.commit()
        conn.close()
        return pid

    def update_weekly_plan_status(self, plan_id: int, status: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        conn.execute(
            "UPDATE weekly_label_plans SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, plan_id),
        )
        conn.commit()
        conn.close()

    def update_weekly_plan(
        self,
        plan_id: int,
        *,
        planned_date: str,
        notes: str,
        status: str,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        conn.execute(
            """
            UPDATE weekly_label_plans
            SET planned_date = ?, notes = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (planned_date, notes, status, now, plan_id),
        )
        conn.commit()
        conn.close()

    def delete_weekly_plan(self, plan_id: int) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM weekly_label_plans WHERE id = ?", (plan_id,))
        conn.commit()
        conn.close()

    # --- Monthly planning entries ---

    def _append_planning_audit(
        self,
        cur: sqlite3.Cursor,
        *,
        entry_id: int,
        action: str,
        actor: str = "",
        actor_user_id: int | None = None,
        detail: dict | None = None,
    ) -> None:
        cur.execute(
            """
            INSERT INTO planning_audit_log(
                entry_id, action, actor, actor_user_id, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                action,
                actor.strip(),
                actor_user_id,
                json.dumps(detail or {}, ensure_ascii=False),
                now_iso(),
            ),
        )

    def list_planning_entries_for_day(self, plan_date_iso: str) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM planning_entries
            WHERE plan_date_iso = ? AND {PLANNING_ACTIVE_FILTER}
            ORDER BY session ASC, id ASC
            """,
            (plan_date_iso,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def list_planning_entries_for_month(self, year: int, month: int) -> list[dict[str, Any]]:
        prefix = f"{year:04d}-{month:02d}-"
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM planning_entries
            WHERE plan_date_iso LIKE ? AND {PLANNING_ACTIVE_FILTER}
            ORDER BY plan_date_iso ASC, session ASC, id ASC
            """,
            (f"{prefix}%",),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_planning_entry(self, entry_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM planning_entries WHERE id = ?", (entry_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def add_planning_entry(
        self,
        *,
        dg_case: str,
        item_code: str,
        quantity: float,
        plan_date: str,
        plan_date_iso: str,
        verify_date: str,
        verify_date_iso: str,
        session: str = "",
        supplier: str = "",
        created_by: int | None = None,
        actor: str = "",
    ) -> int:
        ts = now_iso()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planning_entries(
                dg_case, item_code, supplier, quantity, plan_date, plan_date_iso,
                verify_date, verify_date_iso, session, status,
                check_status, prepare_status,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned', 'pending', 'pending', ?, ?, ?)
            """,
            (
                dg_case,
                item_code,
                supplier,
                quantity,
                plan_date,
                plan_date_iso,
                verify_date,
                verify_date_iso,
                session,
                created_by,
                ts,
                ts,
            ),
        )
        entry_id = int(cur.lastrowid)
        self._append_planning_audit(
            cur,
            entry_id=entry_id,
            action="created",
            actor=actor,
            actor_user_id=created_by,
            detail={
                "dg_case": dg_case,
                "item_code": item_code,
                "supplier": supplier,
                "plan_date": plan_date,
                "verify_date": verify_date,
            },
        )
        conn.commit()
        conn.close()
        return entry_id

    def update_planning_entry_status(self, entry_id: int, status: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        conn.execute(
            "UPDATE planning_entries SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, entry_id),
        )
        conn.commit()
        conn.close()

    def update_planning_check_status(
        self, entry_id: int, check_status: str, *, check_by: str = "", actor_user_id: int | None = None
    ) -> None:
        ts = now_iso()
        status = "verified" if check_status == "confirmed" else "planned"
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE planning_entries
            SET check_status = ?, status = ?, check_by = ?, check_at = ?, updated_at = ?
            WHERE id = ? AND is_deleted = 0
            """,
            (
                check_status,
                status,
                check_by.strip(),
                ts if check_status == "confirmed" else "",
                ts,
                entry_id,
            ),
        )
        if check_status == "confirmed":
            self._append_planning_audit(
                cur,
                entry_id=entry_id,
                action="check_confirmed",
                actor=check_by,
                actor_user_id=actor_user_id,
            )
        conn.commit()
        conn.close()

    def update_planning_prepare_status(
        self, entry_id: int, prepare_status: str, *, prepare_by: str = "", actor_user_id: int | None = None
    ) -> None:
        ts = now_iso()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE planning_entries
            SET prepare_status = ?, prepare_by = ?, prepare_at = ?, updated_at = ?
            WHERE id = ? AND is_deleted = 0
            """,
            (
                prepare_status,
                prepare_by.strip(),
                ts if prepare_status == "prepared" else "",
                ts,
                entry_id,
            ),
        )
        if prepare_status == "prepared":
            self._append_planning_audit(
                cur,
                entry_id=entry_id,
                action="prepared",
                actor=prepare_by,
                actor_user_id=actor_user_id,
            )
        conn.commit()
        conn.close()

    def list_planning_prepare_items(self, entry_id: int) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM planning_prepare_items
            WHERE entry_id = ?
            ORDER BY row_index ASC, id ASC
            """,
            (entry_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def save_planning_prepare_items(
        self,
        entry_id: int,
        items: list[dict[str, Any]],
        *,
        prepare_by: str = "",
        actor_user_id: int | None = None,
    ) -> None:
        ts = now_iso()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM planning_prepare_items WHERE entry_id = ?", (entry_id,))
        for item in items:
            cur.execute(
                """
                INSERT INTO planning_prepare_items(
                    entry_id, row_index, ma_npl, ten_npl, mo_ta, quantity, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    int(item.get("row_index", 0) or 0),
                    normalize_text(item.get("ma_npl")),
                    normalize_text(item.get("ten_npl")),
                    normalize_text(item.get("mo_ta")),
                    float(item.get("quantity", 0) or 0),
                    ts,
                ),
            )
        cur.execute(
            """
            UPDATE planning_entries
            SET prepare_status = 'prepared', prepare_by = ?, prepare_at = ?, updated_at = ?
            WHERE id = ? AND is_deleted = 0
            """,
            (prepare_by.strip(), ts, ts, entry_id),
        )
        self._append_planning_audit(
            cur,
            entry_id=entry_id,
            action="prepared",
            actor=prepare_by,
            actor_user_id=actor_user_id,
            detail={"label_count": len(items)},
        )
        conn.commit()
        conn.close()

    def sync_planning_miss_flags(self, today_iso: str) -> None:
        ts = now_iso()
        conn = self._connect()
        conn.execute(
            f"""
            UPDATE planning_entries
            SET check_status = 'miss', updated_at = ?
            WHERE {PLANNING_ACTIVE_FILTER}
              AND check_status = 'pending'
              AND verify_date_iso != ''
              AND verify_date_iso <= ?
            """,
            (ts, today_iso),
        )
        conn.commit()
        conn.close()

    def soft_delete_planning_entry(
        self,
        entry_id: int,
        *,
        deleted_by: str = "",
        actor_user_id: int | None = None,
    ) -> bool:
        ts = now_iso()
        conn = self._connect()
        cur = conn.cursor()
        row = cur.execute(
            f"SELECT id FROM planning_entries WHERE id = ? AND {PLANNING_ACTIVE_FILTER}",
            (entry_id,),
        ).fetchone()
        if not row:
            conn.close()
            return False
        cur.execute(
            """
            UPDATE planning_entries
            SET is_deleted = 1, deleted_at = ?, deleted_by = ?, updated_at = ?
            WHERE id = ?
            """,
            (ts, deleted_by.strip(), ts, entry_id),
        )
        self._append_planning_audit(
            cur,
            entry_id=entry_id,
            action="deleted",
            actor=deleted_by,
            actor_user_id=actor_user_id,
        )
        conn.commit()
        conn.close()
        return True

    def delete_planning_entry(self, entry_id: int) -> None:
        """Hard delete — reserved for tests/admin; app uses soft_delete_planning_entry."""
        conn = self._connect()
        conn.execute("DELETE FROM planning_audit_log WHERE entry_id = ?", (entry_id,))
        conn.execute("DELETE FROM planning_entries WHERE id = ?", (entry_id,))
        conn.commit()
        conn.close()

    def list_planning_audit_log(
        self,
        *,
        limit: int = 200,
        year: int | None = None,
        month: int | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        sql = """
            SELECT
                a.id AS audit_id,
                a.entry_id,
                a.action,
                a.actor,
                a.actor_user_id,
                a.detail_json,
                a.created_at,
                e.dg_case,
                e.item_code,
                e.supplier,
                e.quantity,
                e.plan_date,
                e.verify_date,
                e.deleted_at,
                e.deleted_by
            FROM planning_audit_log a
            LEFT JOIN planning_entries e ON e.id = a.entry_id
        """
        params: list[Any] = []
        if year is not None and month is not None:
            start = f"{year:04d}-{month:02d}-01"
            if month == 12:
                end = f"{year + 1:04d}-01-01"
            else:
                end = f"{year:04d}-{month + 1:02d}-01"
            sql += " WHERE a.created_at >= ? AND a.created_at < ?"
            params.extend([start, end])
        sql += " ORDER BY a.created_at DESC, a.id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            try:
                item["detail"] = json.loads(item.pop("detail_json") or "{}")
            except json.JSONDecodeError:
                item["detail"] = {}
            out.append(item)
        return out

    def list_planning_pending_verify(self, *, up_to_iso: str) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM planning_entries
            WHERE {PLANNING_ACTIVE_FILTER}
              AND check_status != 'confirmed'
              AND verify_date_iso != ''
              AND verify_date_iso <= ?
            ORDER BY verify_date_iso ASC, plan_date_iso ASC, id ASC
            """,
            (up_to_iso,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def list_planning_reminders(self, *, from_iso: str, to_iso: str) -> list[dict[str, Any]]:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM planning_entries
            WHERE {PLANNING_ACTIVE_FILTER}
              AND check_status != 'confirmed'
              AND verify_date_iso >= ?
              AND verify_date_iso <= ?
            ORDER BY verify_date_iso ASC, id ASC
            """,
            (from_iso, to_iso),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_setup(self, key: str, default: str = "") -> str:
        conn = self._connect()
        row = conn.execute(
            "SELECT value FROM setup WHERE key = ?",
            (self._sk(key),),
        ).fetchone()
        conn.close()
        return str(row[0]) if row and row[0] is not None else default

    def set_setup(self, key: str, value: str, *, sync_cloud: bool = True) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO setup(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (self._sk(key), value),
        )
        conn.commit()
        conn.close()
        if sync_cloud and self.cloud is not None:
            self.cloud.set_setting(key, value)

    def get_file_hash(self, file_path: str) -> str | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT file_hash FROM ol_file_hash WHERE owner_id = ? AND file_path = ?",
            (self._oid(), file_path),
        ).fetchone()
        conn.close()
        return str(row[0]) if row else None

    def set_file_hash(self, file_path: str, file_hash: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO ol_file_hash(owner_id, file_path, file_hash, last_read_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(owner_id, file_path) DO UPDATE SET
                file_hash = excluded.file_hash,
                last_read_at = excluded.last_read_at
            """,
            (self._oid(), file_path, file_hash, now),
        )
        conn.commit()
        conn.close()

    def get_ol_dataset(self, file_name: str, file_hash: str) -> dict[str, Any] | None:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, file_name, file_path, file_hash, imported_at, row_count
            FROM ol_datasets
            WHERE owner_id = ? AND file_name = ? AND file_hash = ?
            """,
            (self._oid(), file_name, file_hash),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_ol_dataset_by_id(self, dataset_id: int) -> dict[str, Any] | None:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, file_name, file_path, file_hash, imported_at, row_count
            FROM ol_datasets WHERE id = ? AND owner_id = ?
            """,
            (dataset_id, self._oid()),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def set_active_ol_dataset(self, dataset_id: int) -> None:
        meta = self.get_ol_dataset_by_id(dataset_id)
        if not meta:
            return
        ts = now_iso()
        self.set_setup("ol_active_dataset_id", str(dataset_id))
        self.set_setup("ol_active_read_at", ts)
        self.set_setup("ol_active_file_name", normalize_text(meta.get("file_name")))
        self.set_setup("ol_active_file_path", normalize_text(meta.get("file_path")))
        if self.cloud is not None:
            self.cloud.set_active_dataset("ol", str(meta.get("file_hash", "")))
            self.cloud.upsert_dataset(
                dataset_type="ol",
                file_name=str(meta.get("file_name", "")),
                file_path=str(meta.get("file_path", "")),
                file_hash=str(meta.get("file_hash", "")),
                content_hash=str(meta.get("file_hash", "")),
                row_count=int(meta.get("row_count", 0) or 0),
                is_active=True,
            )

    def get_active_ol_dataset_meta(self) -> dict[str, Any] | None:
        raw = self.get_setup("ol_active_dataset_id", "")
        if not raw.isdigit():
            return None
        return self.get_ol_dataset_by_id(int(raw))

    def load_active_ol_df(self) -> pd.DataFrame | None:
        meta = self.get_active_ol_dataset_meta()
        if not meta:
            return None
        return self._load_ol_rows_df(int(meta["id"]))

    def save_ol_dataset(self, file_path: str, file_hash: str, df: pd.DataFrame) -> int:
        path = str(Path(file_path).resolve())
        file_name = Path(path).name
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ol_datasets(owner_id, file_name, file_path, file_hash, imported_at, row_count)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, file_name, file_hash) DO UPDATE SET
                file_path = excluded.file_path,
                imported_at = excluded.imported_at,
                row_count = excluded.row_count
            """,
            (self._oid(), file_name, path, file_hash, now, len(df)),
        )
        row = cur.execute(
            "SELECT id FROM ol_datasets WHERE owner_id = ? AND file_name = ? AND file_hash = ?",
            (self._oid(), file_name, file_hash),
        ).fetchone()
        dataset_id = int(row[0])
        cur.execute("DELETE FROM ol_rows WHERE dataset_id = ?", (dataset_id,))
        if not df.empty:
            rows = []
            for _, r in df.iterrows():
                rows.append(
                    (
                        dataset_id,
                        int(r.get("excel_row", 0) or 0),
                        self._serialize_dt(r.get("order_date")),
                        normalize_text(r.get("order_date_str")),
                        normalize_text(r.get("order_no")),
                        normalize_text(r.get("dg_case")),
                        normalize_text(r.get("customer")),
                        self._safe_float(r.get("qty")),
                        normalize_text(r.get("production_no")),
                        normalize_text(r.get("production_name")),
                        normalize_text(r.get("logo")),
                        normalize_text(r.get("color")),
                        normalize_text(r.get("supplier")),
                        normalize_text(r.get("shipdate")),
                        normalize_text(r.get("material")),
                        self._serialize_dt(r.get("cutting")),
                        normalize_text(r.get("cutting_str")),
                        self._serialize_dt(r.get("stock")),
                        normalize_text(r.get("stock_str")),
                        self._serialize_dt(r.get("estimate_delivery")),
                        normalize_text(r.get("estimate_delivery_str")),
                        normalize_text(r.get("customer_code")),
                        normalize_text(r.get("item_code")),
                    )
                )
            cur.executemany(
                """
                INSERT INTO ol_rows(
                    dataset_id, excel_row, order_date, order_date_str, order_no, dg_case,
                    customer, qty, production_no, production_name, logo, color, supplier,
                    shipdate, material, cutting, cutting_str, stock, stock_str,
                    estimate_delivery, estimate_delivery_str, customer_code, item_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        conn.commit()
        conn.close()
        if self.cloud is not None:
            self.cloud.upsert_dataset(
                dataset_type="ol",
                file_name=file_name,
                file_path=path,
                file_hash=file_hash,
                content_hash=file_hash,
                row_count=len(df),
                is_active=False,
            )
        return dataset_id

    def load_ol_dataset_df(self, file_name: str, file_hash: str) -> pd.DataFrame | None:
        meta = self.get_ol_dataset(file_name, file_hash)
        if not meta:
            return None
        return self._load_ol_rows_df(int(meta["id"]))

    def query_ol_rows(
        self,
        file_name: str,
        file_hash: str,
        *,
        dg_case: str = "",
        order_no: str = "",
        production_no: str = "",
    ) -> pd.DataFrame:
        meta = self.get_ol_dataset(file_name, file_hash)
        if not meta:
            return pd.DataFrame()
        sql = "SELECT * FROM ol_rows WHERE dataset_id = ?"
        params: list[Any] = [int(meta["id"])]
        if dg_case:
            sql += " AND dg_case LIKE ?"
            params.append(f"%{dg_case}%")
        if order_no:
            sql += " AND order_no = ?"
            params.append(order_no)
        if production_no:
            sql += " AND production_no = ?"
            params.append(production_no)
        sql += " ORDER BY excel_row ASC"
        conn = self._connect()
        df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        return self._ol_rows_to_dataframe(df)

    def get_bom_ke_dataset(self, a6_hash: str) -> dict[str, Any] | None:
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, file_name, file_path, a6_text, a6_hash, file_hash, imported_at, row_count
            FROM bom_ke_datasets WHERE owner_id = ? AND a6_hash = ?
            """,
            (self._oid(), a6_hash),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def save_bom_ke_dataset(
        self,
        file_path: str,
        file_hash: str,
        a6_text: str,
        a6_hash: str,
        df: pd.DataFrame,
    ) -> int:
        path = str(Path(file_path).resolve())
        file_name = Path(path).name
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO bom_ke_datasets(
                owner_id, file_name, file_path, a6_text, a6_hash, file_hash, imported_at, row_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, a6_hash) DO UPDATE SET
                file_name = excluded.file_name,
                file_path = excluded.file_path,
                file_hash = excluded.file_hash,
                a6_text = excluded.a6_text,
                imported_at = excluded.imported_at,
                row_count = excluded.row_count
            """,
            (self._oid(), file_name, path, a6_text, a6_hash, file_hash, now, len(df)),
        )
        row = cur.execute(
            "SELECT id FROM bom_ke_datasets WHERE owner_id = ? AND a6_hash = ?",
            (self._oid(), a6_hash),
        ).fetchone()
        dataset_id = int(row[0])
        cur.execute("DELETE FROM bom_ke_rows WHERE dataset_id = ?", (dataset_id,))
        if not df.empty:
            rows = []
            for _, r in df.iterrows():
                rows.append(
                    (
                        dataset_id,
                        int(r.get("row_index", 0) or 0),
                        normalize_text(r.get("dg_case")),
                        self._serialize_dt(r.get("order_date")),
                        normalize_text(r.get("product_code")),
                        self._safe_float(r.get(ORDER_QTY)),
                        normalize_text(r.get("ma_npl")),
                        normalize_text(r.get("ten_npl")),
                        normalize_text(r.get("mo_ta")),
                        normalize_text(r.get("don_vi_tinh")),
                        self._safe_float(r.get(NPL_QTY_PER_UNIT)),
                        self._safe_float(r.get(NPL_QTY_ORDER)),
                        normalize_text(r.get("customer_code")),
                        normalize_text(r.get("item_code")),
                    )
                )
            cur.executemany(
                """
                INSERT INTO bom_ke_rows(
                    dataset_id, row_index, dg_case, order_date, product_code, order_qty,
                    ma_npl, ten_npl, mo_ta, don_vi_tinh, npl_qty_per_unit, npl_qty_order,
                    customer_code, item_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        conn.commit()
        conn.close()
        if self.cloud is not None:
            self.cloud.upsert_dataset(
                dataset_type="bom_ke",
                file_name=file_name,
                file_path=path,
                file_hash=file_hash,
                content_hash=a6_hash,
                row_count=len(df),
                is_active=False,
            )
        return dataset_id

    def load_bom_ke_dataset_df(self, a6_hash: str) -> pd.DataFrame | None:
        meta = self.get_bom_ke_dataset(a6_hash)
        if not meta:
            return None
        return self._load_bom_ke_rows_df(int(meta["id"]))

    def query_bom_ke_rows(
        self,
        a6_hash: str,
        *,
        dg_case: str = "",
        product_code: str = "",
        ma_npl: str = "",
    ) -> pd.DataFrame:
        meta = self.get_bom_ke_dataset(a6_hash)
        if not meta:
            return pd.DataFrame()
        sql = "SELECT * FROM bom_ke_rows WHERE dataset_id = ?"
        params: list[Any] = [int(meta["id"])]
        if dg_case:
            sql += " AND dg_case LIKE ?"
            params.append(f"%{dg_case}%")
        if product_code:
            sql += " AND product_code = ?"
            params.append(product_code)
        if ma_npl:
            sql += " AND ma_npl = ?"
            params.append(ma_npl)
        sql += " ORDER BY row_index ASC"
        conn = self._connect()
        df = pd.read_sql_query(sql, conn, params=params)
        conn.close()
        return self._bom_ke_rows_to_dataframe(df)

    @staticmethod
    def _serialize_dt(value: object) -> str | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        if isinstance(value, pd.Timestamp):
            if pd.isna(value):
                return None
            return value.to_pydatetime().isoformat(timespec="seconds")
        text = normalize_text(value)
        return text or None

    @staticmethod
    def _deserialize_dt(value: object) -> datetime | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = normalize_text(value)
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _load_ol_rows_df(self, dataset_id: int) -> pd.DataFrame:
        conn = self._connect()
        df = pd.read_sql_query(
            "SELECT * FROM ol_rows WHERE dataset_id = ? ORDER BY excel_row ASC",
            conn,
            params=(dataset_id,),
        )
        conn.close()
        return self._ol_rows_to_dataframe(df)

    def _ol_rows_to_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(
                columns=[
                    "order_date",
                    "order_date_str",
                    "order_no",
                    "dg_case",
                    "customer",
                    "qty",
                    "production_no",
                    "production_name",
                    "logo",
                    "color",
                    "supplier",
                    "shipdate",
                    "material",
                    "cutting",
                    "cutting_str",
                    "stock",
                    "stock_str",
                    "estimate_delivery",
                    "estimate_delivery_str",
                    "customer_code",
                    "item_code",
                    "excel_row",
                ]
            )
        out = pd.DataFrame(
            {
                "order_date": df["order_date"].map(self._deserialize_dt),
                "order_date_str": df["order_date_str"].fillna("").astype(str),
                "order_no": df["order_no"].fillna("").astype(str),
                "dg_case": df["dg_case"].fillna("").astype(str),
                "customer": df["customer"].fillna("").astype(str),
                "qty": df["qty"],
                "production_no": df["production_no"].fillna("").astype(str),
                "production_name": df["production_name"].fillna("").astype(str),
                "logo": df["logo"].fillna("").astype(str),
                "color": df["color"].fillna("").astype(str),
                "supplier": df["supplier"].fillna("").astype(str),
                "shipdate": df["shipdate"].fillna("").astype(str),
                "material": df["material"].fillna("").astype(str),
                "cutting": df["cutting"].map(self._deserialize_dt),
                "cutting_str": df["cutting_str"].fillna("").astype(str),
                "stock": df["stock"].map(self._deserialize_dt),
                "stock_str": df["stock_str"].fillna("").astype(str),
                "estimate_delivery": df["estimate_delivery"].map(self._deserialize_dt),
                "estimate_delivery_str": df["estimate_delivery_str"].fillna("").astype(str),
                "customer_code": df["customer_code"].fillna("").astype(str),
                "item_code": df["item_code"].fillna("").astype(str),
                "excel_row": df["excel_row"].fillna(0).astype(int),
            }
        )
        return out

    def _load_bom_ke_rows_df(self, dataset_id: int) -> pd.DataFrame:
        conn = self._connect()
        df = pd.read_sql_query(
            "SELECT * FROM bom_ke_rows WHERE dataset_id = ? ORDER BY row_index ASC",
            conn,
            params=(dataset_id,),
        )
        conn.close()
        return self._bom_ke_rows_to_dataframe(df)

    @staticmethod
    def _bom_col(df: pd.DataFrame, new_name: str, legacy: str) -> pd.Series:
        if new_name in df.columns:
            return df[new_name]
        if legacy in df.columns:
            return df[legacy]
        return pd.Series([None] * len(df), index=df.index)

    def _bom_ke_rows_to_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(
                columns=[
                    "row_index",
                    "dg_case",
                    "order_date",
                    "product_code",
                    ORDER_QTY,
                    "ma_npl",
                    "ten_npl",
                    "mo_ta",
                    "don_vi_tinh",
                    NPL_QTY_PER_UNIT,
                    NPL_QTY_ORDER,
                    "customer_code",
                    "item_code",
                ]
            )
        out = pd.DataFrame(
            {
                "row_index": df["row_index"].fillna(0).astype(int),
                "dg_case": df["dg_case"].fillna("").astype(str),
                "order_date": pd.to_datetime(df["order_date"], errors="coerce"),
                "product_code": df["product_code"].fillna("").astype(str),
                ORDER_QTY: pd.to_numeric(self._bom_col(df, ORDER_QTY, "qty_divisor"), errors="coerce"),
                "ma_npl": df["ma_npl"].fillna("").astype(str),
                "ten_npl": df["ten_npl"].fillna("").astype(str),
                "mo_ta": df["mo_ta"].fillna("").astype(str),
                "don_vi_tinh": df["don_vi_tinh"].fillna("").astype(str),
                NPL_QTY_PER_UNIT: pd.to_numeric(
                    self._bom_col(df, NPL_QTY_PER_UNIT, "so_luong_dm_1"), errors="coerce"
                ),
                NPL_QTY_ORDER: pd.to_numeric(
                    self._bom_col(df, NPL_QTY_ORDER, "so_luong"), errors="coerce"
                ),
                "customer_code": df["customer_code"].fillna("").astype(str),
                "item_code": df["item_code"].fillna("").astype(str),
            }
        )
        return out

    def list_snapshot_dates(self) -> list[str]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT snapshot_date FROM ol_snapshots WHERE owner_id = ? ORDER BY snapshot_date DESC",
            (self._oid(),),
        ).fetchall()
        conn.close()
        return [str(r[0]) for r in rows]

    def get_snapshot_meta(self, snapshot_date: str) -> tuple | None:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT id, snapshot_date, file_path, file_hash, imported_at, row_count
            FROM ol_snapshots WHERE owner_id = ? AND snapshot_date = ?
            """,
            (self._oid(), snapshot_date),
        ).fetchone()
        conn.close()
        return row

    def get_snapshot_data_path(self, snapshot_id: int) -> Path:
        cache_dir = Path(self.db_file).parent / "ol_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        owner = self._oid() or "global"
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in owner)[:48]
        return cache_dir / f"snapshot_{safe}_{snapshot_id}.pkl"

    def load_snapshot_df(self, snapshot_date: str) -> pd.DataFrame | None:
        meta = self.get_snapshot_meta(snapshot_date)
        if not meta:
            return None
        file_path = str(meta[2])
        file_hash = str(meta[3])
        file_name = Path(file_path).name
        df = self.load_ol_dataset_df(file_name, file_hash)
        if df is not None:
            return df
        snap_id = int(meta[0])
        path = self.get_snapshot_data_path(snap_id)
        if not path.exists():
            return None
        with open(path, "rb") as f:
            df = pickle.load(f)
        if df is not None and not df.empty:
            self.save_ol_dataset(file_path, file_hash, df)
        return df

    def save_snapshot(
        self,
        snapshot_date: str,
        file_path: str,
        file_hash: str,
        df: pd.DataFrame,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self.save_ol_dataset(file_path, file_hash, df)
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM ol_snapshots WHERE owner_id = ? AND snapshot_date = ?",
            (self._oid(), snapshot_date),
        )
        existing = cur.fetchone()
        if existing:
            snap_id = int(existing[0])
            cur.execute(
                """
                UPDATE ol_snapshots
                SET file_path = ?, file_hash = ?, imported_at = ?, row_count = ?
                WHERE id = ? AND owner_id = ?
                """,
                (file_path, file_hash, now, len(df), snap_id, self._oid()),
            )
        else:
            cur.execute(
                """
                INSERT INTO ol_snapshots(
                    owner_id, snapshot_date, file_path, file_hash, imported_at, row_count
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (self._oid(), snapshot_date, file_path, file_hash, now, len(df)),
            )
            snap_id = int(cur.lastrowid)
        conn.commit()
        conn.close()

        blob_path = self.get_snapshot_data_path(snap_id)
        with open(blob_path, "wb") as f:
            pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)

    def delete_snapshot(self, snapshot_date: str) -> None:
        meta = self.get_snapshot_meta(snapshot_date)
        if not meta:
            return
        snap_id = int(meta[0])
        path = self.get_snapshot_data_path(snap_id)
        conn = self._connect()
        conn.execute("DELETE FROM ol_snapshots WHERE id = ?", (snap_id,))
        conn.commit()
        conn.close()
        if path.exists():
            path.unlink()

    def purge_snapshots_older_than(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, snapshot_date FROM ol_snapshots WHERE owner_id = ? AND snapshot_date < ?",
            (self._oid(), cutoff),
        ).fetchall()
        for snap_id, snap_date in rows:
            path = self.get_snapshot_data_path(int(snap_id))
            if path.exists():
                path.unlink()
            conn.execute("DELETE FROM ol_snapshots WHERE id = ?", (snap_id,))
        conn.commit()
        conn.close()
        return len(rows)
