"""SQLite CRUD — supplier slips."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from core.db.dialect import now_iso
from core.utils import normalize_text


def _ops_oid(db) -> str:
    from core.team_ops_sync import team_ops_owner_id

    return team_ops_owner_id(db)


def _ops_changed(db, *, actor: str = "") -> None:
    from core.team_ops_sync import notify_team_ops_changed

    notify_team_ops_changed(db, actor_name=actor)


class SupplierDbMixin:
    """Methods mixed into HubDatabase via duplicate — use standalone functions on HubDatabase."""

    pass


def _next_slip_code(conn: sqlite3.Connection, owner_id: str) -> str:
    prefix = datetime.now().strftime("%y%m")
    row = conn.execute(
        """
        SELECT COUNT(*) FROM supplier_slips
        WHERE owner_id = ? AND slip_code LIKE ?
        """,
        (owner_id, f"PX-{prefix}-%"),
    ).fetchone()
    n = int(row[0]) + 1
    return f"PX-{prefix}-{n:03d}"


def supplier_insert_audit(
    conn: sqlite3.Connection,
    *,
    slip_id: int,
    action: str,
    actor: str,
    actor_user_id: int | None,
    detail: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO supplier_slip_audit(slip_id, action, actor, actor_user_id, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            slip_id,
            action,
            actor.strip(),
            actor_user_id,
            json.dumps(detail or {}, ensure_ascii=False),
            now_iso(),
        ),
    )


def planning_insert_audit(
    conn: sqlite3.Connection,
    *,
    entry_id: int,
    action: str,
    actor: str,
    actor_user_id: int | None,
    detail: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO planning_audit_log(entry_id, action, actor, actor_user_id, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            entry_id,
            action,
            normalize_text(actor),
            actor_user_id,
            json.dumps(detail or {}, ensure_ascii=False),
            now_iso(),
        ),
    )


def slip_plan_ids(slip: dict[str, Any]) -> set[int]:
    ids: set[int] = set()
    for line in slip.get("lines") or []:
        pid = line.get("plan_entry_id")
        if pid:
            ids.add(int(pid))
    return ids


def find_pending_slip_id_for_plan(db, plan_id: int) -> int | None:
    conn = db._connect()
    row = conn.execute(
        """
        SELECT s.id
        FROM supplier_slips s
        JOIN supplier_slip_lines l ON l.slip_id = s.id
        WHERE s.owner_id = ? AND s.status = 'pending' AND l.plan_entry_id = ?
        ORDER BY s.id DESC
        LIMIT 1
        """,
        (_ops_oid(db), int(plan_id)),
    ).fetchone()
    conn.close()
    return int(row[0]) if row else None


def plan_ids_on_pending_slips(db) -> set[int]:
    conn = db._connect()
    rows = conn.execute(
        """
        SELECT DISTINCT l.plan_entry_id
        FROM supplier_slip_lines l
        JOIN supplier_slips s ON s.id = l.slip_id
        WHERE s.owner_id = ? AND s.status = 'pending' AND l.plan_entry_id IS NOT NULL
        """,
        (_ops_oid(db),),
    ).fetchall()
    conn.close()
    return {int(r[0]) for r in rows if r[0] is not None}


def _sync_plans_saved(
    conn: sqlite3.Connection,
    db,
    plan_ids: set[int],
    *,
    saved: bool,
    actor: str,
    actor_user_id: int | None,
    slip_id: int | None = None,
) -> None:
    if not plan_ids:
        return
    ts = now_iso()
    for pid in plan_ids:
        if saved:
            conn.execute(
                """
                UPDATE planning_entries
                SET check_status = 'confirmed', status = 'verified',
                    check_by = ?, check_at = ?, updated_at = ?
                WHERE id = ? AND is_deleted = 0
                """,
                (normalize_text(actor), ts, ts, pid),
            )
            planning_insert_audit(
                conn,
                entry_id=pid,
                action="check_confirmed",
                actor=actor,
                actor_user_id=actor_user_id,
                detail={"via": "slip_check", "slip_id": slip_id},
            )
            continue
        other = conn.execute(
            """
            SELECT 1
            FROM supplier_slip_lines l
            JOIN supplier_slips s ON s.id = l.slip_id
            WHERE l.plan_entry_id = ? AND s.owner_id = ? AND s.status = 'done'
              AND (? IS NULL OR s.id != ?)
            LIMIT 1
            """,
            (pid, _ops_oid(db), slip_id, slip_id or -1),
        ).fetchone()
        if other:
            continue
        conn.execute(
            """
            UPDATE planning_entries
            SET check_status = 'pending', status = 'planned',
                check_by = '', check_at = '', updated_at = ?
            WHERE id = ? AND is_deleted = 0
            """,
            (ts, pid),
        )


def mark_plan_saved(
    db,
    plan_id: int,
    *,
    actor: str,
    actor_user_id: int | None = None,
) -> tuple[bool, str]:
    """Đánh dấu plan đã lưu = check phiếu pending chứa plan đó."""
    plan = db.get_planning_entry(plan_id)
    if plan and not normalize_text(plan.get("plan_date_iso")):
        return (
            False,
            "Plan chưa có hạn giao tem.\n\n"
            "Cập nhật hạn giao trước khi check phiếu.",
        )
    slip_id = find_pending_slip_id_for_plan(db, plan_id)
    if not slip_id:
        return (
            False,
            "Plan chưa có phiếu Supplier.\n\n"
            "Luồng: Planning → Prepare → Supplier → Tạo phiếu → Check phiếu.",
        )
    slip = get_supplier_slip(db, slip_id)
    if not slip:
        return False, "Không tìm thấy phiếu pending."
    code = normalize_text(slip.get("slip_code")) or f"#{slip_id}"
    check_supplier_slip(db, slip_id, actor=actor, actor_user_id=actor_user_id)
    return True, f"Đã check phiếu {code} — tem đã lưu."


def create_supplier_slip(
    db,
    *,
    supplier: str,
    proposed_by: str,
    reason: str,
    lines: list[dict[str, Any]],
    actor_user_id: int | None = None,
) -> int:
    ts = now_iso()
    conn = db._connect()
    cur = conn.cursor()
    code = _next_slip_code(conn, _ops_oid(db))
    cur.execute(
        """
        INSERT INTO supplier_slips(
            slip_code, supplier, proposed_by, reason, status,
            created_at, checked_at, checked_by, updated_at, owner_id
        )
        VALUES (?, ?, ?, ?, 'pending', ?, '', '', ?, ?)
        """,
        (code, normalize_text(supplier), normalize_text(proposed_by), normalize_text(reason) or "giao lần đầu", ts, ts, _ops_oid(db)),
    )
    slip_id = int(cur.lastrowid)
    for line in lines:
        cur.execute(
            """
            INSERT INTO supplier_slip_lines(
                slip_id, line_no, material_code, product_code, dg_case,
                color, logo, quantity, detail, plan_entry_id, prepare_item_id, is_custom
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slip_id,
                int(line.get("line_no", 0)),
                normalize_text(line.get("material_code")),
                normalize_text(line.get("product_code")),
                normalize_text(line.get("dg_case")),
                normalize_text(line.get("color")),
                normalize_text(line.get("logo")),
                float(line.get("quantity") or 0),
                normalize_text(line.get("detail")),
                line.get("plan_entry_id"),
                line.get("prepare_item_id"),
                1 if line.get("is_custom") else 0,
            ),
        )
    supplier_insert_audit(
        conn,
        slip_id=slip_id,
        action="created",
        actor=proposed_by,
        actor_user_id=actor_user_id,
        detail={"line_count": len(lines), "supplier": supplier},
    )
    conn.commit()
    conn.close()
    _ops_changed(db, actor=proposed_by)
    return slip_id


def update_supplier_slip(
    db,
    slip_id: int,
    *,
    supplier: str,
    reason: str,
    lines: list[dict[str, Any]],
    actor: str,
    actor_user_id: int | None = None,
) -> None:
    ts = now_iso()
    conn = db._connect()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE supplier_slips
        SET supplier = ?, reason = ?, updated_at = ?
        WHERE id = ? AND owner_id = ? AND status = 'pending'
        """,
        (normalize_text(supplier), normalize_text(reason), ts, slip_id, _ops_oid(db)),
    )
    cur.execute("DELETE FROM supplier_slip_lines WHERE slip_id = ?", (slip_id,))
    for line in lines:
        cur.execute(
            """
            INSERT INTO supplier_slip_lines(
                slip_id, line_no, material_code, product_code, dg_case,
                color, logo, quantity, detail, plan_entry_id, prepare_item_id, is_custom
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slip_id,
                int(line.get("line_no", 0)),
                normalize_text(line.get("material_code")),
                normalize_text(line.get("product_code")),
                normalize_text(line.get("dg_case")),
                normalize_text(line.get("color")),
                normalize_text(line.get("logo")),
                float(line.get("quantity") or 0),
                normalize_text(line.get("detail")),
                line.get("plan_entry_id"),
                line.get("prepare_item_id"),
                1 if line.get("is_custom") else 0,
            ),
        )
    supplier_insert_audit(
        conn,
        slip_id=slip_id,
        action="updated",
        actor=actor,
        actor_user_id=actor_user_id,
        detail={"line_count": len(lines)},
    )
    conn.commit()
    conn.close()
    _ops_changed(db, actor=actor)


def cancel_supplier_slip(
    db,
    slip_id: int,
    *,
    actor: str,
    actor_user_id: int | None = None,
    note: str = "",
) -> None:
    slip = get_supplier_slip(db, slip_id)
    if not slip:
        raise ValueError("Không tìm thấy phiếu.")
    if normalize_text(slip.get("status")) != "pending":
        raise ValueError("Chỉ hủy được phiếu pending.")

    conn = db._connect()
    try:
        conn.execute("DELETE FROM supplier_slip_lines WHERE slip_id = ?", (slip_id,))
        conn.execute("DELETE FROM supplier_slip_audit WHERE slip_id = ?", (slip_id,))
        conn.execute(
            "DELETE FROM supplier_slips WHERE id = ? AND owner_id = ? AND status = 'pending'",
            (slip_id, _ops_oid(db)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _ops_changed(db, actor=actor)


def get_supplier_slip(db, slip_id: int) -> dict[str, Any] | None:
    conn = db._connect()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM supplier_slips WHERE id = ? AND owner_id = ?",
        (slip_id, _ops_oid(db)),
    ).fetchone()
    if not row:
        conn.close()
        return None
    slip = dict(row)
    lines = conn.execute(
        "SELECT * FROM supplier_slip_lines WHERE slip_id = ? ORDER BY line_no ASC, id ASC",
        (slip_id,),
    ).fetchall()
    conn.close()
    slip["lines"] = [dict(l) for l in lines]
    return slip


def list_supplier_slips(db) -> list[dict[str, Any]]:
    conn = db._connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            s.*,
            GROUP_CONCAT(
                COALESCE(l.product_code, '') || ' ' ||
                COALESCE(l.dg_case, '') || ' ' ||
                COALESCE(l.material_code, ''),
                ' '
            ) AS _line_search
        FROM supplier_slips s
        LEFT JOIN supplier_slip_lines l ON l.slip_id = s.id
        WHERE s.owner_id = ?
        GROUP BY s.id
        ORDER BY s.created_at DESC, s.id DESC
        """,
        (_ops_oid(db),),
    ).fetchall()
    out = [dict(r) for r in rows]
    conn.close()
    return out


def list_plans_unchecked(
    db,
    *,
    customer_code: str = "",
    item_code: str = "",
    plan_date: str = "",
    dg_case: str = "",
) -> list[dict[str, Any]]:
    from core.db.schema import PLANNING_ACTIVE_FILTER

    sql = f"""
        SELECT * FROM planning_entries
        WHERE {PLANNING_ACTIVE_FILTER}
          AND check_status != 'confirmed'
    """
    params: list[Any] = []
    gc = normalize_text(customer_code).lower()
    if gc:
        sql += " AND LOWER(COALESCE(customer_code, '')) LIKE ?"
        params.append(f"%{gc}%")
    code = normalize_text(item_code).lower()
    if code:
        sql += " AND LOWER(COALESCE(item_code, '')) LIKE ?"
        params.append(f"%{code}%")
    dg = normalize_text(dg_case).lower()
    if dg:
        sql += " AND LOWER(COALESCE(dg_case, '')) LIKE ?"
        params.append(f"%{dg}%")
    date_q = normalize_text(plan_date).lower()
    if date_q:
        sql += " AND (LOWER(COALESCE(plan_date, '')) LIKE ? OR LOWER(COALESCE(plan_date_iso, '')) LIKE ?)"
        params.extend([f"%{date_q}%", f"%{date_q}%"])
    sql += " ORDER BY plan_date_iso ASC, supplier ASC, id ASC"

    conn = db._connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    pending_plan_ids = plan_ids_on_pending_slips(db)
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        if int(item["id"]) in pending_plan_ids:
            continue
        out.append(item)
    return out


def check_supplier_slip(
    db,
    slip_id: int,
    *,
    actor: str,
    actor_user_id: int | None = None,
) -> list[dict[str, Any]]:
    slip = get_supplier_slip(db, slip_id)
    if not slip:
        raise ValueError("Không tìm thấy phiếu.")
    if normalize_text(slip.get("status")) != "pending":
        raise ValueError("Phiếu không ở trạng thái pending.")

    from core.npl_stock_service import NplStockService

    ts = now_iso()
    conn = db._connect()
    stock_svc = NplStockService(db)
    try:
        applied = stock_svc.apply_slip_check(conn, slip, actor=actor)
        conn.execute(
            """
            UPDATE supplier_slips
            SET status = 'done', checked_at = ?, checked_by = ?, updated_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'pending'
            """,
            (ts, normalize_text(actor), ts, slip_id, _ops_oid(db)),
        )
        supplier_insert_audit(
            conn,
            slip_id=slip_id,
            action="checked",
            actor=actor,
            actor_user_id=actor_user_id,
            detail={"npl_stock_applied": applied},
        )
        _sync_plans_saved(
            conn,
            db,
            slip_plan_ids(slip),
            saved=True,
            actor=actor,
            actor_user_id=actor_user_id,
            slip_id=slip_id,
        )
        conn.commit()
        applied_out = applied
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _ops_changed(db, actor=actor)
    return applied_out


def uncheck_supplier_slip(
    db,
    slip_id: int,
    *,
    actor: str,
    actor_user_id: int | None = None,
    note: str = "",
) -> None:
    from core.npl_stock_service import NplStockService

    ts = now_iso()
    conn = db._connect()
    stock_svc = NplStockService(db)
    try:
        reverted = stock_svc.revert_slip_check(conn, slip_id, actor=actor, note=note)
        conn.execute(
            """
            UPDATE supplier_slips
            SET status = 'pending', checked_at = '', checked_by = '', updated_at = ?
            WHERE id = ? AND owner_id = ? AND status = 'done'
            """,
            (ts, slip_id, _ops_oid(db)),
        )
        supplier_insert_audit(
            conn,
            slip_id=slip_id,
            action="unchecked",
            actor=actor,
            actor_user_id=actor_user_id,
            detail={"note": note, "npl_stock_reverted": reverted},
        )
        slip = get_supplier_slip(db, slip_id)
        if slip:
            _sync_plans_saved(
                conn,
                db,
                slip_plan_ids(slip),
                saved=False,
                actor=actor,
                actor_user_id=actor_user_id,
                slip_id=slip_id,
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _ops_changed(db, actor=actor)


def list_supplier_audit(db, slip_id: int) -> list[dict[str, Any]]:
    conn = db._connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM supplier_slip_audit
        WHERE slip_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (slip_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
