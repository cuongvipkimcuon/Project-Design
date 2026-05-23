"""Đồng bộ plan / phiếu / tồn NPL lên Supabase — team shared."""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from core.team_dataset_store import _bytea_for_rest, _bytea_from_rest
from core.utils import normalize_text

TEAM_OPS_SCOPE = "team"
TEAM_OPS_ROW_ID = "default"
SETUP_OPS_VERSION = "team_ops_version"
SETUP_OPS_HASH = "team_ops_hash"
SETUP_OPS_SYNCED_AT = "team_ops_synced_at"

OPS_TABLES_CHILD_FIRST = (
    "npl_stock_ledger",
    "npl_stock_batches",
    "npl_stock_balances",
    "supplier_slip_audit",
    "supplier_slip_lines",
    "planning_prepare_items",
    "planning_audit_log",
    "supplier_slips",
    "planning_entries",
    "npl_stock_types",
)

PUSH_DEBOUNCE_SEC = 1.5
POLL_INTERVAL_SEC = 18

_push_timer: threading.Timer | None = None
_push_lock = threading.Lock()
_last_push_scheduled = 0.0


@dataclass
class TeamOpsSyncResult:
    pulled: bool = False
    pushed: bool = False
    version: int = 0
    message: str = ""
    errors: list[str] = field(default_factory=list)
    needs_overwrite_confirm: bool = False


def team_ops_owner_id(db) -> str:
    if getattr(db, "cloud", None) and db.cloud.enabled:
        return TEAM_OPS_SCOPE
    return db._oid()


def migrate_user_ops_to_team(db) -> None:
    """Gộp dữ liệu ops cũ (owner_id = user / rỗng) sang scope team."""
    if not getattr(db, "cloud", None) or not db.cloud.enabled:
        return
    user_oid = normalize_text(db.owner_id)
    if not user_oid or user_oid == TEAM_OPS_SCOPE:
        return
    conn = db._connect()
    try:
        conn.execute(
            "UPDATE supplier_slips SET owner_id = ? WHERE owner_id = ? OR owner_id = ''",
            (TEAM_OPS_SCOPE, user_oid),
        )
        _migrate_npl_stock_to_team(conn, user_oid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_npl_stock_to_team(conn: sqlite3.Connection, user_oid: str) -> None:
    """Gộp loại tồn trùng module+code — tránh UNIQUE (owner_id, module, code)."""
    team = TEAM_OPS_SCOPE
    legacy_types = conn.execute(
        """
        SELECT id, owner_id, module, code
        FROM npl_stock_types
        WHERE owner_id = ? OR owner_id = ''
        ORDER BY id ASC
        """,
        (user_oid,),
    ).fetchall()

    for old_id, old_owner, module, code in legacy_types:
        old_id = int(old_id)
        team_row = conn.execute(
            """
            SELECT id FROM npl_stock_types
            WHERE owner_id = ? AND module = ? AND code = ?
            """,
            (team, module, code),
        ).fetchone()
        if team_row:
            team_id = int(team_row[0])
            if team_id == old_id:
                continue
            for bal_owner in {normalize_text(old_owner), user_oid, "", team}:
                row = conn.execute(
                    """
                    SELECT balance FROM npl_stock_balances
                    WHERE owner_id = ? AND stock_type_id = ?
                    """,
                    (bal_owner, old_id),
                ).fetchone()
                if not row or float(row[0] or 0) == 0:
                    continue
                extra = float(row[0])
                updated = conn.execute(
                    """
                    UPDATE npl_stock_balances
                    SET balance = balance + ?
                    WHERE owner_id = ? AND stock_type_id = ?
                    """,
                    (extra, team, team_id),
                ).rowcount
                if not updated:
                    conn.execute(
                        """
                        INSERT INTO npl_stock_balances(owner_id, stock_type_id, balance)
                        VALUES (?, ?, ?)
                        """,
                        (team, team_id, extra),
                    )
                conn.execute(
                    "DELETE FROM npl_stock_balances WHERE owner_id = ? AND stock_type_id = ?",
                    (bal_owner, old_id),
                )
            conn.execute(
                "UPDATE npl_stock_batches SET owner_id = ?, stock_type_id = ? WHERE stock_type_id = ?",
                (team, team_id, old_id),
            )
            conn.execute(
                "UPDATE npl_stock_ledger SET owner_id = ?, stock_type_id = ? WHERE stock_type_id = ?",
                (team, team_id, old_id),
            )
            conn.execute("DELETE FROM npl_stock_types WHERE id = ?", (old_id,))
        else:
            conn.execute(
                "UPDATE npl_stock_types SET owner_id = ? WHERE id = ?",
                (team, old_id),
            )

    conn.execute(
        """
        UPDATE npl_stock_balances SET owner_id = ?
        WHERE owner_id = ? OR owner_id = ''
        """,
        (team, user_oid),
    )
    conn.execute(
        """
        UPDATE npl_stock_batches SET owner_id = ?
        WHERE owner_id = ? OR owner_id = ''
        """,
        (team, user_oid),
    )
    conn.execute(
        """
        UPDATE npl_stock_ledger SET owner_id = ?
        WHERE owner_id = ? OR owner_id = ''
        """,
        (team, user_oid),
    )

    dupes = conn.execute(
        """
        SELECT stock_type_id, SUM(balance) AS total, COUNT(*) AS cnt
        FROM npl_stock_balances
        WHERE owner_id = ?
        GROUP BY stock_type_id
        HAVING cnt > 1
        """,
        (team,),
    ).fetchall()
    for type_id, total, _cnt in dupes:
        conn.execute(
            "DELETE FROM npl_stock_balances WHERE owner_id = ? AND stock_type_id = ?",
            (team, int(type_id)),
        )
        conn.execute(
            """
            INSERT INTO npl_stock_balances(owner_id, stock_type_id, balance)
            VALUES (?, ?, ?)
            """,
            (team, int(type_id), float(total or 0)),
        )


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def export_team_ops(db) -> dict[str, list[dict[str, Any]]]:
    oid = team_ops_owner_id(db)
    conn = db._connect()
    conn.row_factory = sqlite3.Row
    out: dict[str, list[dict[str, Any]]] = {}
    try:
        out["planning_entries"] = [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM planning_entries ORDER BY id ASC"
            ).fetchall()
        ]
        out["planning_prepare_items"] = [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM planning_prepare_items ORDER BY id ASC"
            ).fetchall()
        ]
        out["planning_audit_log"] = [
            _row_to_dict(r)
            for r in conn.execute(
                """
                SELECT * FROM planning_audit_log
                ORDER BY created_at DESC, id DESC
                LIMIT 400
                """
            ).fetchall()
        ]
        out["supplier_slips"] = [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM supplier_slips WHERE owner_id = ? ORDER BY id ASC",
                (oid,),
            ).fetchall()
        ]
        slip_ids = [int(r["id"]) for r in out["supplier_slips"]]
        if slip_ids:
            placeholders = ",".join("?" * len(slip_ids))
            out["supplier_slip_lines"] = [
                _row_to_dict(r)
                for r in conn.execute(
                    f"SELECT * FROM supplier_slip_lines WHERE slip_id IN ({placeholders}) ORDER BY id ASC",
                    slip_ids,
                ).fetchall()
            ]
            out["supplier_slip_audit"] = [
                _row_to_dict(r)
                for r in conn.execute(
                    f"""
                    SELECT * FROM supplier_slip_audit
                    WHERE slip_id IN ({placeholders})
                    ORDER BY id DESC LIMIT 500
                    """,
                    slip_ids,
                ).fetchall()
            ]
        else:
            out["supplier_slip_lines"] = []
            out["supplier_slip_audit"] = []
        out["npl_stock_types"] = [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM npl_stock_types WHERE owner_id = ? ORDER BY id ASC",
                (oid,),
            ).fetchall()
        ]
        out["npl_stock_balances"] = [
            _row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM npl_stock_balances WHERE owner_id = ?",
                (oid,),
            ).fetchall()
        ]
        out["npl_stock_batches"] = [
            _row_to_dict(r)
            for r in conn.execute(
                """
                SELECT * FROM npl_stock_batches
                WHERE owner_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (oid,),
            ).fetchall()
        ]
        out["npl_stock_ledger"] = [
            _row_to_dict(r)
            for r in conn.execute(
                """
                SELECT * FROM npl_stock_ledger
                WHERE owner_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 2500
                """,
                (oid,),
            ).fetchall()
        ]
    finally:
        conn.close()
    return out


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def _gzip_payload(payload: dict) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    return gzip.compress(raw, compresslevel=6)


def _gunzip_payload(blob: bytes) -> dict:
    raw = gzip.decompress(blob)
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def import_team_ops(db, payload: dict[str, list[dict[str, Any]]]) -> None:
    oid = team_ops_owner_id(db)
    conn = db._connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in OPS_TABLES_CHILD_FIRST:
            conn.execute(f"DELETE FROM {table}")
        insert_order = list(reversed(OPS_TABLES_CHILD_FIRST))
        for table in insert_order:
            rows = payload.get(table) or []
            if not rows:
                continue
            cols = list(rows[0].keys())
            col_sql = ", ".join(cols)
            placeholders = ", ".join("?" for _ in cols)
            batch: list[list[Any]] = []
            for row in rows:
                item = dict(row)
                if table in (
                    "supplier_slips",
                    "npl_stock_types",
                    "npl_stock_balances",
                    "npl_stock_ledger",
                    "npl_stock_batches",
                ):
                    item["owner_id"] = oid
                values = [item.get(c) for c in cols]
                batch.append(values)
            if batch:
                conn.executemany(
                    f"INSERT INTO {table} ({col_sql}) VALUES ({placeholders})",
                    batch,
                )
        conn.execute("PRAGMA foreign_keys = ON")
        for table in insert_order:
            if table == "npl_stock_balances":
                continue
            row = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()
            if row and row[0]:
                try:
                    conn.execute(
                        "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
                        (int(row[0]), table),
                    )
                except sqlite3.OperationalError:
                    pass
        conn.commit()
    except Exception:
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        raise
    finally:
        conn.close()


def _coerce_blob(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, list):
        return bytes(value)
    text = str(value).strip()
    if text.startswith("\\x"):
        return bytes.fromhex(text[2:])
    if text.startswith("0x"):
        return bytes.fromhex(text[2:])
    import base64

    try:
        return base64.b64decode(text)
    except Exception:
        return b""


class TeamOpsSyncService:
    def __init__(self, db) -> None:
        self.db = db
        self.cloud = db.cloud

    @property
    def enabled(self) -> bool:
        return self.cloud is not None and self.cloud.enabled

    def _local_version(self) -> int:
        try:
            return int(self.db.get_setup(SETUP_OPS_VERSION, "0") or 0)
        except ValueError:
            return 0

    def _set_local_meta(self, *, version: int, content_hash: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        self.db.set_setup(SETUP_OPS_VERSION, str(version), sync_cloud=False)
        self.db.set_setup(SETUP_OPS_HASH, content_hash, sync_cloud=False)
        self.db.set_setup(SETUP_OPS_SYNCED_AT, ts, sync_cloud=False)

    def fetch_remote(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        client = self.cloud._get_client()
        rows = (
            client.table("team_ops_sync")
            .select("*")
            .eq("id", TEAM_OPS_ROW_ID)
            .limit(1)
            .execute()
            .data
            or []
        )
        return rows[0] if rows else None

    def pull_if_newer(self, *, notify: Callable[[], None] | None = None) -> TeamOpsSyncResult:
        result = TeamOpsSyncResult()
        if not self.enabled:
            result.message = "Cloud chưa bật."
            return result
        try:
            remote = self.fetch_remote()
            if not remote:
                result.message = "Chưa có dữ liệu ops trên cloud."
                return result
            remote_version = int(remote.get("version") or 0)
            remote_hash = normalize_text(remote.get("content_hash"))
            local_version = self._local_version()
            local_hash = normalize_text(self.db.get_setup(SETUP_OPS_HASH, ""))
            if remote_version <= local_version and remote_hash == local_hash:
                result.version = local_version
                result.message = "Đã mới nhất."
                return result
            blob = _bytea_from_rest(remote.get("payload_gzip")) or _coerce_blob(
                remote.get("payload_gzip")
            )
            if not blob:
                result.errors.append("Payload cloud trống.")
                return result
            payload = _gunzip_payload(blob)
            import_team_ops(self.db, payload)
            self._set_local_meta(version=remote_version, content_hash=remote_hash)
            result.pulled = True
            result.version = remote_version
            who = normalize_text(remote.get("updated_by_name")) or "team"
            when = normalize_text(remote.get("updated_at"))[:16].replace("T", " ")
            result.message = f"Đã tải plan/phiếu/tồn từ cloud (v{remote_version}) — {who}, {when}."
            if notify:
                notify()
        except Exception as exc:
            result.errors.append(str(exc))
            result.message = f"Lỗi pull ops: {exc}"
        return result

    def push(self, *, actor_name: str = "", force: bool = False) -> TeamOpsSyncResult:
        result = TeamOpsSyncResult()
        if not self.enabled:
            result.message = "Cloud chưa bật."
            return result
        try:
            remote = self.fetch_remote()
            remote_version = int(remote.get("version") or 0) if remote else 0
            local_version = self._local_version()
            payload = export_team_ops(self.db)
            content_hash = _payload_hash(payload)
            local_hash = normalize_text(self.db.get_setup(SETUP_OPS_HASH, ""))
            if remote and normalize_text(remote.get("content_hash")) == content_hash and content_hash == local_hash:
                result.message = "Không có thay đổi để đẩy."
                result.version = remote_version
                return result
            if (
                not force
                and remote
                and remote_version > local_version
                and normalize_text(remote.get("content_hash")) != content_hash
            ):
                who = normalize_text(remote.get("updated_by_name")) or "team"
                when = normalize_text(remote.get("updated_at"))[:16].replace("T", " ")
                result.needs_overwrite_confirm = True
                result.version = remote_version
                result.message = (
                    f"Cloud đã có bản mới hơn (v{remote_version}, {who}, {when}). "
                    f"Local v{local_version}. Ghi đè lên cloud?"
                )
                return result
            new_version = max(remote_version, local_version) + 1
            gzip_blob = _gzip_payload(payload)
            client = self.cloud._get_client()
            row = {
                "id": TEAM_OPS_ROW_ID,
                "version": new_version,
                "content_hash": content_hash,
                "payload_gzip": _bytea_for_rest(gzip_blob),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": self.cloud.owner_id,
                "updated_by_name": normalize_text(actor_name) or "user",
            }
            client.table("team_ops_sync").upsert(row).execute()
            self._set_local_meta(version=new_version, content_hash=content_hash)
            result.pushed = True
            result.version = new_version
            kb = len(gzip_blob) // 1024
            result.message = f"Đã đẩy plan/phiếu/tồn lên cloud (v{new_version}, ~{kb} KB)."
        except Exception as exc:
            result.errors.append(str(exc))
            result.message = f"Lỗi push ops: {exc}"
        return result

    def sync_bidirectional(self, *, actor_name: str = "", notify: Callable[[], None] | None = None, force: bool = False) -> TeamOpsSyncResult:
        if not self.enabled:
            return TeamOpsSyncResult(message="Cloud chưa bật.")
        pull_result = self.pull_if_newer(notify=notify)
        local = export_team_ops(self.db)
        local_hash = _payload_hash(local)
        remote = self.fetch_remote()
        remote_hash = normalize_text(remote.get("content_hash")) if remote else ""
        if local_hash != remote_hash:
            push_result = self.push(actor_name=actor_name, force=force)
            pull_result.pushed = push_result.pushed
            pull_result.needs_overwrite_confirm = push_result.needs_overwrite_confirm
            if push_result.message and (push_result.pushed or push_result.needs_overwrite_confirm):
                pull_result.message = push_result.message
            elif pull_result.pulled and not push_result.pushed:
                pass
            elif push_result.errors:
                pull_result.errors.extend(push_result.errors)
        return pull_result


def get_team_ops_status(db) -> dict[str, Any]:
    """Trạng thái đồng bộ ops (local + remote nếu cloud bật)."""
    local_version = 0
    try:
        local_version = int(db.get_setup(SETUP_OPS_VERSION, "0") or 0)
    except ValueError:
        pass
    synced_at = normalize_text(db.get_setup(SETUP_OPS_SYNCED_AT, ""))
    out: dict[str, Any] = {
        "local_version": local_version,
        "synced_at": synced_at,
        "remote_version": 0,
        "remote_updated_at": "",
        "remote_updated_by": "",
        "has_remote": False,
    }
    if getattr(db, "cloud", None) and db.cloud.enabled:
        try:
            remote = TeamOpsSyncService(db).fetch_remote()
            if remote:
                out["has_remote"] = True
                out["remote_version"] = int(remote.get("version") or 0)
                out["remote_updated_at"] = normalize_text(remote.get("updated_at"))
                out["remote_updated_by"] = normalize_text(remote.get("updated_by_name"))
        except Exception:
            pass
    return out


def notify_team_ops_changed(db, *, actor_name: str = "") -> None:
    if not getattr(db, "cloud", None) or not db.cloud.enabled:
        return
    schedule_team_ops_push(db, actor_name=actor_name)


def schedule_team_ops_push(db, *, actor_name: str = "", force: bool = False) -> None:
    global _push_timer, _last_push_scheduled
    if not getattr(db, "cloud", None) or not db.cloud.enabled:
        return

    def _run() -> None:
        try:
            svc = TeamOpsSyncService(db)
            result = svc.push(actor_name=actor_name, force=force)
            if result.needs_overwrite_confirm:
                cb = getattr(db, "_ops_overwrite_callback", None)
                scheduler = getattr(db, "_ops_ui_scheduler", None)
                if cb and scheduler:
                    scheduler(
                        lambda r=result: cb(
                            r, lambda: schedule_team_ops_push(db, actor_name=actor_name, force=True)
                        )
                    )
                elif cb:
                    cb(result, lambda: schedule_team_ops_push(db, actor_name=actor_name, force=True))
                else:
                    print(f"[TeamOpsSync] conflict: {result.message}")
                return
            if hasattr(db, "_ops_notify_callback") and db._ops_notify_callback:
                db._ops_notify_callback()
        except Exception as exc:
            print(f"[TeamOpsSync] push: {exc}")

    with _push_lock:
        _last_push_scheduled = time.time()
        if _push_timer is not None:
            _push_timer.cancel()
        _push_timer = threading.Timer(PUSH_DEBOUNCE_SEC, _run)
        _push_timer.daemon = True
        _push_timer.start()


def start_team_ops_polling(
    db,
    *,
    on_pulled: Callable[[TeamOpsSyncResult], None] | None = None,
) -> threading.Event:
    """Poll cloud mỗi POLL_INTERVAL_SEC — trả stop event."""
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(POLL_INTERVAL_SEC):
            if not getattr(db, "cloud", None) or not db.cloud.enabled:
                continue
            with _push_lock:
                if time.time() - _last_push_scheduled < PUSH_DEBOUNCE_SEC + 2:
                    continue
            try:
                result = TeamOpsSyncService(db).pull_if_newer()
                if result.pulled and on_pulled:
                    on_pulled(result)
            except Exception as exc:
                print(f"[TeamOpsSync] poll: {exc}")

    threading.Thread(target=_loop, daemon=True, name="team-ops-poll").start()
    return stop
