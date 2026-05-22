"""SQLite CRUD — supplier slips."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from core.db.dialect import now_iso
from core.utils import normalize_text


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
    code = _next_slip_code(conn, db._oid())
    cur.execute(
        """
        INSERT INTO supplier_slips(
            slip_code, supplier, proposed_by, reason, status,
            created_at, checked_at, checked_by, updated_at, owner_id
        )
        VALUES (?, ?, ?, ?, 'pending', ?, '', '', ?, ?)
        """,
        (code, normalize_text(supplier), normalize_text(proposed_by), normalize_text(reason) or "giao lần đầu", ts, ts, db._oid()),
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
        (normalize_text(supplier), normalize_text(reason), ts, slip_id, db._oid()),
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


def get_supplier_slip(db, slip_id: int) -> dict[str, Any] | None:
    conn = db._connect()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM supplier_slips WHERE id = ? AND owner_id = ?",
        (slip_id, db._oid()),
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


def list_supplier_slips(
    db,
    *,
    supplier_filter: str = "",
    product_filter: str = "",
    dg_filter: str = "",
) -> list[dict[str, Any]]:
    conn = db._connect()
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM supplier_slips WHERE owner_id = ?"
    params: list[Any] = [db._oid()]
    if supplier_filter:
        sql += " AND supplier LIKE ?"
        params.append(f"%{supplier_filter}%")
    sql += " ORDER BY created_at DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    out: list[dict[str, Any]] = []
    pf = product_filter.strip().lower()
    df = dg_filter.strip().lower()
    for r in rows:
        slip = dict(r)
        if pf or df:
            lines = conn.execute(
                "SELECT product_code, dg_case FROM supplier_slip_lines WHERE slip_id = ?",
                (slip["id"],),
            ).fetchall()
            if pf and not any(pf in normalize_text(l["product_code"]).lower() for l in lines):
                continue
            if df and not any(df in normalize_text(l["dg_case"]).lower() for l in lines):
                continue
        out.append(slip)
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
    return [dict(r) for r in rows]


def check_supplier_slip(
    db,
    slip_id: int,
    *,
    actor: str,
    actor_user_id: int | None = None,
) -> None:
    ts = now_iso()
    conn = db._connect()
    conn.execute(
        """
        UPDATE supplier_slips
        SET status = 'done', checked_at = ?, checked_by = ?, updated_at = ?
        WHERE id = ? AND owner_id = ? AND status = 'pending'
        """,
        (ts, normalize_text(actor), ts, slip_id, db._oid()),
    )
    supplier_insert_audit(conn, slip_id=slip_id, action="checked", actor=actor, actor_user_id=actor_user_id)
    conn.commit()
    conn.close()


def uncheck_supplier_slip(
    db,
    slip_id: int,
    *,
    actor: str,
    actor_user_id: int | None = None,
    note: str = "",
) -> None:
    ts = now_iso()
    conn = db._connect()
    conn.execute(
        """
        UPDATE supplier_slips
        SET status = 'pending', checked_at = '', checked_by = '', updated_at = ?
        WHERE id = ? AND owner_id = ? AND status = 'done'
        """,
        (ts, slip_id, db._oid()),
    )
    supplier_insert_audit(
        conn,
        slip_id=slip_id,
        action="unchecked",
        actor=actor,
        actor_user_id=actor_user_id,
        detail={"note": note},
    )
    conn.commit()
    conn.close()


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
