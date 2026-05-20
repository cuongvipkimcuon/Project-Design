"""SQLite persistence for OL snapshots, users, and weekly plans."""

from __future__ import annotations

import pickle
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import hash_password

DB_FILE = "dg_hub.db"


class HubDatabase:
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS setup (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ol_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                row_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(snapshot_date)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ol_file_hash (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                last_read_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS weekly_label_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            """
        )
        conn.commit()
        conn.close()

    # --- Users (admin thêm trực tiếp DB hoặc tools/add_user.py) ---

    def count_users(self) -> int:
        conn = self._connect()
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        return int(n)

    def create_user(self, username: str, password: str, display_name: str = "") -> int:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO users(username, password_hash, display_name, is_active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (username.strip(), hash_password(password), display_name.strip() or username.strip(), now),
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

    def get_setup(self, key: str, default: str = "") -> str:
        conn = self._connect()
        row = conn.execute("SELECT value FROM setup WHERE key = ?", (key,)).fetchone()
        conn.close()
        return str(row[0]) if row and row[0] is not None else default

    def set_setup(self, key: str, value: str) -> None:
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO setup(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()
        conn.close()

    def get_file_hash(self, file_path: str) -> str | None:
        conn = self._connect()
        row = conn.execute(
            "SELECT file_hash FROM ol_file_hash WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        conn.close()
        return str(row[0]) if row else None

    def set_file_hash(self, file_path: str, file_hash: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        conn.execute(
            """
            INSERT INTO ol_file_hash(file_path, file_hash, last_read_at)
            VALUES (?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_hash = excluded.file_hash,
                last_read_at = excluded.last_read_at
            """,
            (file_path, file_hash, now),
        )
        conn.commit()
        conn.close()

    def list_snapshot_dates(self) -> list[str]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT snapshot_date FROM ol_snapshots ORDER BY snapshot_date DESC"
        ).fetchall()
        conn.close()
        return [str(r[0]) for r in rows]

    def get_snapshot_meta(self, snapshot_date: str) -> tuple | None:
        conn = self._connect()
        row = conn.execute(
            """
            SELECT id, snapshot_date, file_path, file_hash, imported_at, row_count
            FROM ol_snapshots WHERE snapshot_date = ?
            """,
            (snapshot_date,),
        ).fetchone()
        conn.close()
        return row

    def get_snapshot_data_path(self, snapshot_id: int) -> Path:
        cache_dir = Path(self.db_file).parent / "ol_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"snapshot_{snapshot_id}.pkl"

    def load_snapshot_df(self, snapshot_date: str) -> pd.DataFrame | None:
        meta = self.get_snapshot_meta(snapshot_date)
        if not meta:
            return None
        snap_id = int(meta[0])
        path = self.get_snapshot_data_path(snap_id)
        if not path.exists():
            return None
        with open(path, "rb") as f:
            return pickle.load(f)

    def save_snapshot(
        self,
        snapshot_date: str,
        file_path: str,
        file_hash: str,
        df: pd.DataFrame,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM ol_snapshots WHERE snapshot_date = ?",
            (snapshot_date,),
        )
        existing = cur.fetchone()
        if existing:
            snap_id = int(existing[0])
            cur.execute(
                """
                UPDATE ol_snapshots
                SET file_path = ?, file_hash = ?, imported_at = ?, row_count = ?
                WHERE id = ?
                """,
                (file_path, file_hash, now, len(df), snap_id),
            )
        else:
            cur.execute(
                """
                INSERT INTO ol_snapshots(snapshot_date, file_path, file_hash, imported_at, row_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snapshot_date, file_path, file_hash, now, len(df)),
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
            "SELECT id, snapshot_date FROM ol_snapshots WHERE snapshot_date < ?",
            (cutoff,),
        ).fetchall()
        for snap_id, snap_date in rows:
            path = self.get_snapshot_data_path(int(snap_id))
            if path.exists():
                path.unlink()
            conn.execute("DELETE FROM ol_snapshots WHERE id = ?", (snap_id,))
        conn.commit()
        conn.close()
        return len(rows)
